"""Fetching a reference database onto this machine.

A database timon cannot find is the commonest thing standing between a fresh
install and a first run, and every user fixes it the same way: read the
publisher's page, copy a URL, wait for some gigabytes, unpack them, and point
timon at what came out. This module does that act instead, from the sources
declared in ``config.DB_SOURCES`` — which is the only place a URL is written
down, so the page offers exactly what timon knows how to fetch.

It is handed databases and either refuses up front (nothing declared to fetch
it from, one already going, something already there, a variable pointing
timon somewhere a download would not land) or gets on with it. It lands each
one under the name ``timon.paths`` looks for, which is the whole of how a
pipeline comes to be pointed at it: nothing has to be told where it went.
Which databases a run is missing is the experiment's answer, and how a
half-finished download is worded is the presenter's.

**A download is not a run.** It is held in this process and dies with it: an
interrupted one leaves a ``.part`` file that the next attempt overwrites, and
nothing is written where timon looks until the whole file is there and, if it
is an archive, has been unpacked. So a database that exists is a database that
is complete, and quitting timon halfway through can leave a partial one behind
but never a broken one. That is also why nothing here writes to
``paths.state_root()`` the way a workflow does — there is nothing for another
timon to find.
"""

from __future__ import annotations

import shutil
import tarfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ...paths import REFERENCE_DATA, db_root
from ..config import DATABASE_BUNDLE, DB_SOURCES

# Big enough that the loop is not the bottleneck on a fast link, small enough
# that a cancel is acted on promptly: the flag is only read between chunks.
CHUNK = 1 << 20
# Applies to making the connection and to each read, not to the download as a
# whole — a 100 GB package is hours, and hours is not a fault.
TIMEOUT = 60

DOWNLOADING = "downloading"
UNPACKING   = "unpacking"
DONE        = "done"
FAILED      = "failed"
CANCELLED   = "cancelled"

LIVE_STATES = (DOWNLOADING, UNPACKING)


class DownloadError(Exception):
    """A download that was refused before anything was fetched."""


@dataclass(frozen=True)
class Source:
    """One declared way to get one database, from config.DB_SOURCES.

    One per build where a database is published in more than one — the two
    caps of the Kraken2 index — and exactly one otherwise, which is what lets
    everything past here treat both declarations the same way.
    """

    db: str
    variant: str          # "" for a database published only one way
    label: str
    size: str
    url: str
    archive: bool
    install_as: str
    description: str
    note: str             # what sets this build apart from its siblings

    def destination(self) -> Path:
        """Where it lands. Resolved on each ask, as TIMON_DB_DIR is."""
        return db_root() / self.install_as


def variants(db: str) -> list[Source]:
    """Every build this database is published in, the default one first.

    A database declared without variants *is* its one variant: the entry is
    read as the build, so a caller never has to ask which shape it was
    written in. Empty for a database nothing is published for.
    """
    entry = DB_SOURCES.get(db)
    if entry is None:
        return []

    shared = {key: value for key, value in entry.items()
              if key not in ("variants", "default")}
    declared = entry.get("variants") or [{"id": ""}]
    built = [_source(db, {**shared, **one}) for one in declared]
    # The default first, so a caller that wants "the build to fetch" can take
    # the head of the list and the page can offer them in a settled order.
    wanted = entry.get("default")
    built.sort(key=lambda src: src.variant != wanted)
    return built


def _source(db: str, entry: dict) -> Source:
    return Source(db=db, variant=entry.get("id", ""), label=entry["label"],
                  size=entry.get("size", ""), url=entry["url"],
                  archive=bool(entry.get("archive")),
                  install_as=entry["install_as"],
                  description=entry.get("description", ""),
                  note=entry.get("note", ""))


def source(db: str, variant: str | None = None) -> Source | None:
    """Where one database can be fetched from, or None.

    None for a database nothing is published for, and for a build that is not
    declared — both are normal answers and not failures: the page says what is
    missing either way, and only offers to fetch what it can. No variant asked
    for is the declared default, which is what the install button fetches.
    """
    built = variants(db)
    if not built:
        return None
    if not variant:
        return built[0]
    return next((src for src in built if src.variant == variant), None)


def refusal(db: str, variant: str | None = None) -> str:
    """Why this database cannot be fetched right now, or "" if it can.

    The one rule for "can the button do anything about it", asked by
    ``start`` before it starts and by the page before it offers. Worded
    because it goes back to the user as it is; the facts behind it are all
    plain, and there is only one way to say each.
    """
    reference = REFERENCE_DATA.get(db)
    if reference is None:
        return f"timon knows of no database called {db!r}"
    if not variants(db):
        return f"there is nowhere declared to download the {reference.label} from"
    src = source(db, variant)
    if src is None:
        return f"there is no {reference.label} build called {variant!r}"
    going = DOWNLOADS.get(db)
    if going is not None and going.running:
        return f"{going.source.label} is already downloading"
    # Asked of the database and not of this build: any build of it is the
    # database, and a second one would be gigabytes for a file timon would
    # not even look at (paths.py takes the first that is there).
    if reference.present():
        return f"{reference.label} is already installed"
    if not reference.installed_here():
        # A download goes to db_root(), and timon is looking elsewhere: it
        # would arrive and still be reported missing.
        return (f"{reference.env} points at {reference.locate()}, which is not "
                f"there — fix it or unset it to let timon install one")
    if src.destination().exists():
        return f"{src.label} is already there"
    return ""


class Download:
    """One database being fetched, and what can be said about it while it is.

    The thread owns the files; everything else only ever reads the counters,
    which is why they are plain attributes and not a lock-guarded structure —
    an integer that is one chunk out of date is a progress bar one chunk out
    of date.
    """

    def __init__(self, src: Source):
        self.source = src
        self.state  = DOWNLOADING
        self.done   = 0
        # 0 when the server sends no Content-Length, which is the difference
        # between a progress bar and a byte count; the page decides which.
        self.total  = 0
        self.error  = ""
        self.path   = ""
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # ── what it is doing ────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self.state in LIVE_STATES

    def snapshot(self) -> dict:
        """The facts, with nothing worded — presenters.database_view words them."""
        return {
            "db":          self.source.db,
            # Which build is arriving, so the card can say so while it does:
            # the row names the database, and two of them are the same size
            # of nothing until this says which was picked.
            "variant":     self.source.variant,
            "label":       self.source.label,
            "url":         self.source.url,
            "state":       self.state,
            "running":     self.running,
            "done":        self.done,
            "total":       self.total,
            "path":        self.path,
            "error":       self.error,
        }

    def cancel(self) -> None:
        """Ask it to stop. Read between chunks, so it takes effect at once."""
        self._cancel.set()

    def wait(self, timeout: float | None = None) -> None:
        """Block until it is over — for the tests, and for nothing else."""
        if self._thread is not None:
            self._thread.join(timeout)

    # ── doing it ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        dest    = self.source.destination()
        part    = dest.with_name(dest.name + ".part")
        staging = dest.with_name("." + dest.name + ".unpack")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            self._fetch(part)
            if self._cancel.is_set():
                self._clean(part, staging)
                self.state = CANCELLED
                return
            self._install(part, dest, staging)
        except Exception as exc:                       # noqa: BLE001
            # Anything at all: a name that does not resolve, a 404, a full
            # disk, a tarball that is not one. None of them is timon's fault
            # to hide, and all of them read the same way to the user — it did
            # not arrive, and here is what the machine said.
            self._clean(part, staging)
            self.error = f"{type(exc).__name__}: {exc}"
            self.state = FAILED
        else:
            self.path  = str(dest)
            self.state = DONE

    def _fetch(self, part: Path) -> None:
        """Stream the URL into ``part``, a chunk at a time.

        Never into the destination itself: a file under db_root() is a
        database timon will offer to a run, and a half-downloaded one would
        be offered exactly the same way.
        """
        with urllib.request.urlopen(self.source.url, timeout=TIMEOUT) as response:
            self.total = int(response.headers.get("Content-Length") or 0)
            with open(part, "wb") as out:
                while not self._cancel.is_set():
                    chunk = response.read(CHUNK)
                    if not chunk:
                        return
                    out.write(chunk)
                    self.done += len(chunk)

    def _install(self, part: Path, dest: Path, staging: Path) -> None:
        """Put what arrived where timon looks, in one move.

        The rename is the last thing that happens, so the destination appears
        complete or not at all — which is what lets ``present()`` stay the
        simple existence check it is everywhere else in timon.
        """
        if not self.source.archive:
            part.replace(dest)
            return

        self.state = UNPACKING
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        with tarfile.open(part) as tar:
            # A tarball from the network may name ../.. or an absolute path,
            # and extractall would follow it. The data filter refuses that;
            # it is the default from python 3.14 and available from 3.12, so
            # on an older interpreter this asks for it by name.
            if hasattr(tarfile, "data_filter"):
                tar.extractall(staging, filter="data")
            else:
                # A 3.10 older than 3.10.12 has no filter to ask for, so the
                # same rule is applied by hand rather than skipped.
                root = staging.resolve()
                for member in tar.getmembers():
                    target = (root / member.name).resolve()
                    if target != root and root not in target.parents:
                        raise tarfile.TarError(
                            f"{member.name!r} unpacks outside the archive")
                tar.extractall(staging)                # noqa: S202
        part.unlink()

        # Most packages are one directory with everything inside it (GTDB-Tk's
        # is a release folder), and a few are loose files (a Kraken2 index is).
        # Unwrapping the first kind is what makes the installed path the one a
        # pipeline is given rather than its parent.
        entries = list(staging.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            entries[0].replace(dest)
            shutil.rmtree(staging, ignore_errors=True)
        else:
            staging.replace(dest)

    def _clean(self, *paths: Path) -> None:
        """Leave nothing behind that a later attempt would have to reason about."""
        for path in paths:
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass


# What is being fetched right now, by database. Not a record of what has been
# fetched: that is the file on disk, and asking whether a database is there is
# asking the filesystem — the same question timon asks about one the user
# installed by hand.
DOWNLOADS: dict[str, Download] = {}
_LOCK = threading.Lock()


def start(db: str, variant: str | None = None) -> Download:
    """Begin fetching one database, or say why not.

    One at a time per database, and never over something already installed:
    the second is the important one, because the thing being replaced may be
    a hundred gigabytes the user downloaded last month. ``variant`` is which
    build, for a database published in more than one; without it, the
    declared default.
    """
    with _LOCK:
        reason = refusal(db, variant)
        if reason:
            raise DownloadError(reason)
        download = Download(source(db, variant))
        DOWNLOADS[db] = download

    download.start()
    return download


def install(dbs: list[str] | None = None,
            choices: dict[str, str] | None = None) -> list[Download]:
    """Fetch every one of ``dbs`` that is missing and can be fetched.

    What the install button asks for: the bundle by default
    (``config.DATABASE_BUNDLE``). Ones already there, or already arriving,
    are passed over rather than refused — pressing it again after one
    download failed should fetch that one and leave the rest alone. Refused
    only when there was nothing at all it could start, with the reason for
    each.

    ``choices`` is which build to take for a database published in more than
    one, by database. A database missing from it takes the declared default,
    which is what the button does for a user who never opened the choice.
    """
    wanted = DATABASE_BUNDLE if dbs is None else dbs
    choices = choices or {}
    started, reasons = [], []
    for db in wanted:
        reference = REFERENCE_DATA.get(db)
        going = DOWNLOADS.get(db)
        if (reference is not None and reference.present()) or (going and going.running):
            continue
        try:
            started.append(start(db, choices.get(db)))
        except DownloadError as exc:
            reasons.append(str(exc))
    if not started and reasons:
        raise DownloadError("; ".join(reasons))
    return started


def bundle_missing() -> list[str]:
    """The databases of the bundle that are not on this machine.

    Machine-wide rather than per run: the bundle is installed once, for every
    run after, so whether the button still has anything to do does not
    depend on which pipeline is picked.
    """
    return [db for db in DATABASE_BUNDLE if not REFERENCE_DATA[db].present()]


def current(db: str) -> Download | None:
    """The last download of this database in this process, going or over."""
    return DOWNLOADS.get(db)


def cancel(db: str | None = None) -> bool:
    """Stop the download of one database, or of every one. False if nothing was.

    Only while it is still arriving. Unpacking is a single call into tarfile
    with no way in, and it is the short half of a long job — stopping there
    would mean claiming something timon cannot do.
    """
    stopped = False
    for key, download in DOWNLOADS.items():
        if db is not None and key != db:
            continue
        if download.state == DOWNLOADING:
            download.cancel()
            stopped = True
    return stopped


def busy() -> bool:
    """Whether anything is being fetched — what tells the page to keep asking."""
    return any(download.running for download in DOWNLOADS.values())
