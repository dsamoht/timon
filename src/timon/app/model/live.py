"""Runs in flight: what is going right now, wherever it was started from.

A run outlives the timon that launched it. Nextflow is put in a session of
its own, so closing the browser, quitting the server, or losing the terminal
leaves the workflow going — which is the point, since a run is hours of
compute and timon is a page someone happens to have open.

That only helps if the next timon can find it again, and looking in the
workspace is not enough: timon is launched wherever the user happens to be.
So a launched run leaves a pointer in a per-user directory,
``paths.state_root()/running`` — which process is doing it, where it writes,
and where its output is being logged. Any timon on the machine reads that
directory, so a run started in one folder can be watched and stopped from
another.

This is not the memory of a run. The note in the output folder is that, and
it stays the only one (see ``history``): every entry here describes a
*process*, is believed only for as long as that process is alive, and is
thrown away when it is not. Delete the whole directory and nothing is lost
but the ability to watch a run this timon did not start.

Liveness is asked of the operating system, never of the file. A recorded pid
on its own proves nothing — the number is reused — so a process counts as
this run only if it also started when this run started and still carries the
run's output folder on its command line. Nothing else in timon decides
whether a run is going.
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional

from ...paths import state_root

# Everything nextflow writes goes here, inside the folder the run writes, and
# the leading dot is what keeps it out of the results browser — the same rule
# that hides the run's record. It is a file rather than a pipe because a pipe
# has two ends: if timon held one and then quit, nextflow's next write would
# fail. A file is read by whoever is interested, including nobody.
LOG_NAME = ".timon-run.log"

# A run of a configuration, and the pipeline's own quick test. The test is in
# here for one reason only: it is a nextflow that must not be started twice
# over the same folder.
RUN  = "run"
TEST = "test"

# How much of the log a page is given when it attaches to a run already in
# progress. A day-long run writes far more than a browser should be asked to
# render at once, and the tail is the part that says what is happening now.
REPLAY_BYTES = 256 * 1024


@dataclass(frozen=True)
class Live:
    """One nextflow that is running, as the pointer to it describes it."""

    exp_id: str
    pid: int
    out_dir: str
    launch_dir: str = ""
    output_folder: str = ""
    log: str = ""
    command: list = field(default_factory=list)
    kind: str = RUN
    started_at: float = 0.0
    # What ``ps`` said this process's start time was at the moment it was
    # registered. Held so that a pid handed out again later cannot be
    # mistaken for this run.
    proc_start: str = ""

    @property
    def is_test(self) -> bool:
        return self.kind == TEST


# ── where the pointers live ──────────────────────────────────────────────────

def registry() -> Path:
    return state_root() / "running"


def _pointer(out_dir: str) -> Path:
    """One pointer per output folder, named so it can be found again.

    Hashed rather than spelled out: the name has to be a filename and an
    output folder is a path. Which run it is, is inside the file.
    """
    digest = hashlib.sha1(str(out_dir).encode()).hexdigest()[:16]
    return registry() / f"{digest}.json"


def log_path(out_dir) -> str:
    return os.path.join(str(out_dir), LOG_NAME)


# ── asking the operating system ──────────────────────────────────────────────

# The state ``ps`` reports for a process that has ended but whose parent has
# not collected it yet. It is still in the table and still answers to its pid,
# and it is not a run: for the moment between a run ending and the timon that
# started it waiting on the process, a zombie is the only thing left of it.
ZOMBIE = "Z"


def _ps(pids: list[int]) -> Optional[dict[int, tuple[str, str]]]:
    """When each of these processes started, and what it is running.

    Anything that has already ended is left out. None — rather than an empty
    mapping — when the question could not be asked at all, which is the
    difference between "that run is over" and "this machine has no ps".
    """
    if not pids:
        return {}
    try:
        proc = subprocess.run(
            ["ps", "-ww", "-o", "pid=,state=,lstart=,args=",
             "-p", ",".join(str(p) for p in pids)],
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    found: dict[int, tuple[str, str]] = {}
    for line in proc.stdout.splitlines():
        # pid, state, then the five words of a date, then the command line.
        parts = line.split(maxsplit=7)
        if len(parts) < 8 or not parts[0].isdigit():
            continue
        if parts[1].startswith(ZOMBIE):
            continue
        found[int(parts[0])] = (" ".join(parts[2:7]), parts[7])
    return found


def process_start(pid: int) -> str:
    """When this process started, in whatever words ``ps`` uses here.

    Compared as text and never parsed: it only has to tell one process from
    another that happened to be given the same number.
    """
    seen = _ps([pid])
    return seen.get(pid, ("", ""))[0] if seen else ""


def _still_there(pid: int) -> bool:
    """Whether anything at all answers to this pid."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Someone else's process. It exists, which is all this asks.
        return True
    except OSError:
        return False
    return True


def _alive_in(entry: Live, seen: Optional[dict]) -> bool:
    """Whether this entry's run is one of the processes ``ps`` just reported.

    Split out from ``alive`` so that a whole directory of entries can be
    judged against one answer.
    """
    if not entry.pid:
        return False
    if seen is None:
        # No ps to ask. A bare pid is a weaker answer than the one below,
        # but refusing to answer would call every run dead.
        return _still_there(entry.pid)
    if entry.pid not in seen:
        return False
    start, args = seen[entry.pid]
    if entry.proc_start and start:
        return start == entry.proc_start
    return not entry.out_dir or entry.out_dir in args


def alive(entry: Live) -> bool:
    """Whether this entry's run is genuinely still going.

    A pid on its own proves nothing, because the number is handed out again
    once the process is gone, and what it would be handed to on a laptop
    that has been running for weeks is anybody's business. So the process
    has to be the same process: started at the same moment this run was
    registered, which is the answer ``ps`` gives that nothing else shares.

    Where that could not be asked for — a machine with no usable ``ps`` —
    the run's own output folder still being on the process's command line
    stands in for it, and a bare pid is the last resort. Both are weaker,
    and both are better than calling every run dead.
    """
    return _alive_in(entry, _ps([entry.pid]) if entry.pid else {})


# ── keeping the directory honest ─────────────────────────────────────────────

def _read(path: Path) -> Live | None:
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("out_dir"):
        return None
    fields = set(Live.__dataclass_fields__)
    return Live(**{k: v for k, v in data.items() if k in fields})


def register(entry: Live) -> Live:
    """Leave the pointer to a run that has just been launched.

    A failure to write is swallowed, as it is for a run's record: not being
    able to tell another timon about this run is worth less than the run.
    """
    try:
        registry().mkdir(parents=True, exist_ok=True)
        with open(_pointer(entry.out_dir), "w") as handle:
            json.dump(asdict(entry), handle, indent=2)
    except OSError:
        pass
    return entry


def forget(entry: Live | str) -> None:
    """Drop the pointer to a run that is over."""
    out_dir = entry if isinstance(entry, str) else entry.out_dir
    try:
        _pointer(out_dir).unlink()
    except OSError:
        pass


def running(output_folder: str = "") -> list[Live]:
    """Every run in flight on this machine, newest first.

    Reading the directory is also what cleans it: an entry whose process is
    gone is deleted as it is passed over, so a timon that died without
    tidying up is corrected by the next one that looks rather than leaving a
    run that is over listed for ever.

    ``output_folder`` narrows it to the runs of one workspace, which is what
    the page in front of one workspace is asking about.
    """
    try:
        pointers = sorted(registry().glob("*.json"))
    except OSError:
        return []
    entries = {path: _read(path) for path in pointers}
    # One question to the operating system rather than one per entry: this is
    # asked on every page load and on every save, and a subprocess apiece
    # would be felt.
    seen = _ps([entry.pid for entry in entries.values() if entry and entry.pid])

    found: list[Live] = []
    for path, entry in entries.items():
        if entry is None or not _alive_in(entry, seen):
            try:
                path.unlink()
            except OSError:
                pass
            continue
        if output_folder and entry.output_folder != str(output_folder):
            continue
        found.append(entry)
    found.sort(key=lambda e: e.started_at, reverse=True)
    return found


def find(out_dir) -> Live | None:
    """The run writing this folder, if one is. Prunes the pointer if not."""
    entry = _read(_pointer(str(out_dir)))
    if entry is None:
        return None
    if not alive(entry):
        forget(entry)
        return None
    return entry


# ── stopping one ─────────────────────────────────────────────────────────────

# Interrupt first, and give nextflow room to answer it: that is the signal it
# handles by killing the tasks it submitted and the containers they are in.
# A run killed outright leaves those behind, still holding the machine, with
# nothing left that knows about them. Terminate and kill follow only for a
# nextflow that has stopped answering.
STOP_SIGNALS = ((signal.SIGINT, 30.0), (signal.SIGTERM, 15.0), (signal.SIGKILL, 5.0))


def _signal(pid: int, sig) -> None:
    """Signal the whole run, not just the process at the top of it.

    Nextflow is launched in a session of its own, so it leads a process
    group, and the group is every task it spawned. Sending to the group is
    what reaches a task that has outlived a nextflow that is no longer
    listening.
    """
    try:
        os.killpg(os.getpgid(pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def wait_gone(entry: Live, timeout: float, poll: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not alive(entry):
            return True
        time.sleep(poll)
    return not alive(entry)


def stop(entry: Live) -> bool:
    """Stop a run, escalating only as far as it makes timon go.

    Blocking, and for as long as a minute in the worst case: it is waiting
    for nextflow to take its tasks down, which is the part worth waiting
    for. Callers run it off the request.
    """
    for sig, grace in STOP_SIGNALS:
        if not alive(entry):
            return True
        _signal(entry.pid, sig)
        if wait_gone(entry, grace):
            return True
    return not alive(entry)


# ── reading the log ──────────────────────────────────────────────────────────

def banner(command: list[str]) -> bytes:
    """What is written into the log before a run, so attempts can be told apart."""
    when = time.strftime("%Y-%m-%d %H:%M:%S")
    return f"\n── {when} ── {' '.join(command)}\n".encode()


class Tail:
    """A run's log, from somewhere in the middle of it, as it is written.

    The one way the console gets its text, whether this timon started the
    run or found it. Reading a file rather than a pipe is what makes those
    two the same thing, and what lets a page that was closed for an hour
    come back and pick the run up where it is.

    Bytes, decoded here: a chunk boundary can fall inside a character, and a
    pipeline that writes something that is not UTF-8 must not end the run.
    Chunks are handed on exactly as they were written — carriage returns and
    escape sequences included — because the console is what knows what to do
    with them.
    """

    CHUNK = 64 * 1024

    def __init__(self, path, replay: int = REPLAY_BYTES):
        self.path = str(path)
        self._replay = replay
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    def chunks(self, alive_now: Callable[[], bool],
               poll: float = 0.4, settle: float = 2.0) -> Iterator[str]:
        """Text as it arrives, ending once the run is over and read out.

        ``alive_now`` is asked rather than assumed, so this follows a run
        belonging to another process exactly as it follows its own. When it
        says the run is over the log is still read to the end — the last
        thing nextflow wrote is usually the reason it stopped — and only
        then does the iterator finish.
        """
        try:
            handle = open(self.path, "rb")
        except OSError:
            return
        with handle:
            handle.seek(0, os.SEEK_END)
            start = max(0, handle.tell() - self._replay)
            handle.seek(start)
            if start:
                # Start at a line of its own. Coming in at an arbitrary byte
                # would open the console on half a word, and worse, on half
                # an escape sequence — which is printed rather than obeyed.
                handle.readline()
            ending = 0.0
            while True:
                data = handle.read(self.CHUNK)
                if data:
                    ending = 0.0
                    text = self._decoder.decode(data)
                    if text:
                        yield text
                    continue
                if alive_now():
                    ending = 0.0
                    time.sleep(poll)
                    continue
                # Over. Keep reading for a moment: the process is gone but
                # what it wrote last may not have reached the disk yet.
                if not ending:
                    ending = time.monotonic() + settle
                elif time.monotonic() > ending:
                    break
                time.sleep(poll)
            rest = self._decoder.decode(b"", True)
            if rest:
                yield rest
