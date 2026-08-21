"""Locations of on-disk reference data.

Resolution does not depend on how timon was installed: the small gene database
ships inside the package, while the large genome set lives in a user data
directory that TIMON_DB_DIR can override.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

_PKG = Path(__file__).resolve().parent

GENOMES_DB_NAME = "cyanobacteriota_ncbi_dRep_n220"
GENES_DB_NAME = "core_cyanotoxin-related_gene_mibig-v4_antismash-v8.faa"


def db_root() -> Path:
    """Directory holding downloaded reference data."""
    env = os.getenv("TIMON_DB_DIR")
    if env:
        return Path(env).expanduser()
    base = os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "timon"


def genomes_db() -> Path:
    """Genome set used by roshab-cli — ~1 GB, not shipped with the package."""
    return db_root() / GENOMES_DB_NAME


def genes_db() -> Path:
    """Cyanotoxin gene database — small enough to ship inside the package."""
    return _PKG / "resources" / GENES_DB_NAME


@dataclass(frozen=True)
class ReferenceData:
    """One piece of timon's own reference data: where it is and what it is."""

    locate: Callable[[], Path]
    kind: str            # "dir" | "file"
    label: str

    def present(self) -> bool:
        path = self.locate()
        return path.is_dir() if self.kind == "dir" else path.is_file()


# Keyed by the name a pipeline entry uses under "reference_data"; the nextflow
# flag each is passed under is in model.nextflow, which is the only place that
# has to know the flags.
REFERENCE_DATA = {
    "genomes_db": ReferenceData(genomes_db, "dir", "genome database"),
    "genes_db":   ReferenceData(genes_db, "file", "gene database"),
}


def missing_reference_data(names: Iterable[str] | None = None) -> list[str]:
    """Reference data that a run expects but which is absent on disk."""
    return [f"{ref.label} not found: {ref.locate()}"
            for ref in (REFERENCE_DATA[n] for n in (names or REFERENCE_DATA))
            if not ref.present()]
