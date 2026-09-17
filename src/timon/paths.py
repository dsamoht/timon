"""Locations of on-disk reference data.

Resolution does not depend on how timon was installed: every database a
pipeline reads lives in one user data directory that TIMON_DB_DIR can override.
That directory is where the **install databases** button puts them, under fixed
names, so a pipeline is pointed at a database by timon rather than by the user
— nobody types a path.
The cyanotoxin gene database is not timon's — roshab-cli ships its own and is
left to use it.

Each database also has an environment variable that names it outright, for a
site that already has a copy (a shared Kraken2 index on a cluster, say). A
value there wins over db_root(), and a download never goes to it.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

# The names each database is installed under, inside db_root(). A dated
# build's date is part of the name, so a newer one is a new directory beside
# the old rather than a silent change to what a recorded run read.
#
# More than one name where the same database is published in more than one
# build: PlusPF is capped at 8 GB and at 16 GB, and the user picks which to
# fetch (config.DB_SOURCES). Whichever they chose is the one to be found, so
# the names are looked through in order and the first that is there wins —
# which keeps "is it installed" the plain existence check it is everywhere
# else. The first is also what a download would land as, so it is what a
# "not found" message points at.
KRAKEN_DB_NAMES = ("k2_pluspf_16_GB_20260626", "k2_pluspf_08_GB_20260626")
GTDBTK_DB_NAMES  = ("gtdbtk_data",)
GENOMES_DB_NAMES = ("cyanobacteriota_ncbi_dRep_n220",)

# The variables that name each one outright, wherever it is.
KRAKEN_DB_ENV  = "KRAKEN_DB"
GTDBTK_DB_ENV  = "GTDBTK_DB"
GENOMES_DB_ENV = "TIMON_GENOMES_DB"


def db_root() -> Path:
    """Directory holding downloaded reference data."""
    env = os.getenv("TIMON_DB_DIR")
    if env:
        return Path(env).expanduser()
    base = os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "timon"


def _named_or_installed(env: str, names: tuple[str, ...]) -> Path:
    """What ``env`` names, or else whichever of ``names`` timon has installed.

    Read on every call, like everything else here: setting a variable and
    restarting, or installing and reloading, is enough for timon to see it.
    The first name is the answer when none of them is there — nothing is
    installed, and that is the one a download would create.
    """
    value = os.getenv(env)
    if value:
        return Path(value).expanduser()
    root = db_root()
    return next((root / name for name in names if (root / name).exists()),
                root / names[0])


def kraken_db() -> Path:
    """The Kraken2 index. A directory or a ``.tar.gz`` — the pipeline takes both.

    Either cap of PlusPF is a Kraken2 index and the pipeline cannot tell them
    apart, so which one is installed is the machine's business and never the
    run's: nothing above this asks which build it got.
    """
    return _named_or_installed(KRAKEN_DB_ENV, KRAKEN_DB_NAMES)


# Bracken reads one k-mer distribution per read length, built into the index
# beside the Kraken2 hash; a length with no file of its own is one Bracken
# fails on after classification has already run.
_BRACKEN_DISTRIB = re.compile(r"database(\d+)mers\.kmer_distrib")


def bracken_lengths(index: Path) -> list[str] | None:
    """The read lengths ``index`` carries a Bracken distribution for, shortest first.

    None when there is no looking inside it: not installed, or a tarball,
    which only the pipeline unpacks — reading the member list of an 11 GB
    archive to fill in a form is not worth the wait. An empty list is an
    index that was looked into and has none, which Bracken cannot run on.
    """
    if not index.is_dir():
        return None
    found = (_BRACKEN_DISTRIB.fullmatch(entry.name) for entry in index.iterdir())
    return [str(n) for n in sorted({int(m.group(1)) for m in found if m})]


def gtdbtk_db() -> Path:
    """GTDB-Tk's reference data, which GTDB-Tk only reads as a directory."""
    return _named_or_installed(GTDBTK_DB_ENV, GTDBTK_DB_NAMES)


def genomes_db() -> Path:
    """Genome set CoverM is pointed at — the full one is ~1 GB, so not shipped.

    ``TIMON_GENOMES_DB`` names it outright, and is what makes a smaller one
    usable: the pipeline hands the path to ``coverm genome
    --genome-fasta-directory``, so any set of FASTA files is a valid answer,
    and a two-genome set is as legitimate as the 220-genome one. Without it
    the default set is looked for under db_root().

    Either may be a directory or a ``.tar.gz`` — the pipeline unpacks a
    tarball itself, so refusing one here would refuse a run it would accept.
    """
    return _named_or_installed(GENOMES_DB_ENV, GENOMES_DB_NAMES)


@dataclass(frozen=True)
class ReferenceData:
    """One piece of timon's own reference data: where it is and what it is."""

    locate: Callable[[], Path]
    # "dir" and "file" are what the pipeline will only accept as one or the
    # other; "any" is for the databases it unpacks itself, where a tarball and
    # a directory are the same answer.
    kind: str            # "dir" | "file" | "any"
    label: str
    env: str             # the variable that names it outright
    # Every name it may be installed under in db_root(), the one a download
    # would create first. More than one only where the same database is
    # published in more than one build (see KRAKEN_DB_NAMES).
    names: tuple[str, ...]

    @property
    def name(self) -> str:
        """What an install of it lands as when there is nothing there yet."""
        return self.names[0]

    def present(self) -> bool:
        path = self.locate()
        if self.kind == "dir":
            return path.is_dir()
        if self.kind == "file":
            return path.is_file()
        return path.exists()

    def installed_here(self) -> bool:
        """Whether timon looks for it where timon would install it.

        False while its variable points somewhere else: a download lands under
        db_root(), and one that landed where timon is not looking would be
        gigabytes spent on a database still reported missing.
        """
        root = db_root()
        return self.locate() in {root / name for name in self.names}


# Keyed by the name a pipeline entry uses under "reference_data"; the nextflow
# flag each is passed under is in model.nextflow, which is the only place that
# has to know the flags.
REFERENCE_DATA = {
    "kraken_db":  ReferenceData(kraken_db, "any", "Kraken2 database",
                                KRAKEN_DB_ENV, KRAKEN_DB_NAMES),
    "gtdbtk_db":  ReferenceData(gtdbtk_db, "dir", "GTDB-Tk database",
                                GTDBTK_DB_ENV, GTDBTK_DB_NAMES),
    "genomes_db": ReferenceData(genomes_db, "any", "genome database",
                                GENOMES_DB_ENV, GENOMES_DB_NAMES),
}


# Parameters whose accepted values are whatever an installed database was built
# with, rather than a list config.py could write down: which Bracken lengths
# exist depends on the index on this machine. Keyed by the name a parameter
# declares under "options_from"; each is the database it reads and how.
DATABASE_OPTIONS: dict[str, tuple[str, Callable[[Path], list[str] | None]]] = {
    "bracken_lengths": ("kraken_db", bracken_lengths),
}


def missing_reference_data(names: Iterable[str] | None = None) -> list[str]:
    """Reference data that a run expects but which is absent on disk."""
    return [f"{ref.label} not found: {ref.locate()}"
            for ref in (REFERENCE_DATA[n] for n in (names or REFERENCE_DATA))
            if not ref.present()]


def state_root() -> Path:
    """Directory for what is true only while timon is running.

    Separate from db_root(): nothing here is data the user would back up or
    reinstall, it is a note about a process that is alive right now. It has
    to live outside the workspace because a run started in one folder has to
    be findable by a timon started in another — that is the whole reason the
    directory exists (see ``model.live``).
    """
    base = os.getenv("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "timon"
