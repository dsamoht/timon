"""Locations of on-disk reference data.

Resolution does not depend on how timon was installed: the small gene database
ships inside the package, while the large genome set lives in a user data
directory that TIMON_DB_DIR can override.
"""

import os
from pathlib import Path

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


def missing_reference_data() -> list[str]:
    """Reference data that a run expects but which is absent on disk."""
    missing = []
    if not genomes_db().is_dir():
        missing.append(f"genome database not found: {genomes_db()}")
    if not genes_db().is_file():
        missing.append(f"gene database not found: {genes_db()}")
    return missing
