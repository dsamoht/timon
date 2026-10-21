"""Finding the reads already sitting in the input folder.

A scan is a starting point for the sample sheet, not an answer: it guesses a
sample name from how the files are laid out, and the user corrects it.
"""

import gzip
import os
import re
from collections import defaultdict

from ..config import Config

FASTQ_RE = re.compile(r'\.f(ast)?q(\.gz)?$', re.IGNORECASE)
GZIP_MAGIC = b'\x1f\x8b'


class Unreadable(Exception):
    """A file that is there and cannot be read as what its name says."""


def holds_data(path: str) -> bool:
    """Whether a file has anything in it once decompressed.

    Size alone does not say: an empty FastQ gzipped is twenty bytes, and it is
    what a nanopore run leaves in a barcode nothing was read into.
    """
    try:
        with open(path, "rb") as handle:
            gzipped = handle.read(2) == GZIP_MAGIC
        if path.endswith(".gz") and not gzipped:
            raise Unreadable("is not gzip-compressed")
        opener = gzip.open if gzipped else open
        with opener(path, "rb") as handle:
            return handle.read(1) != b""
    except (OSError, EOFError) as exc:
        # gzip.BadGzipFile is an OSError; a truncated stream is an EOFError.
        raise Unreadable(f"cannot be read ({exc})") from exc


def files_under(folder: str, name: re.Pattern | None = None):
    """Every file below a folder, at any depth, as a pipeline gathering a
    folder's reads by rglob sees them."""
    for root, _dirs, files in os.walk(folder):
        for f in sorted(files):
            if name is None or name.search(f):
                yield os.path.join(root, f)


def _has_reads(path: str) -> bool:
    # Unreadable is kept: dropped here it would be a sample that silently
    # went missing, kept it is a row the save explains.
    try:
        return holds_data(path)
    except Unreadable:
        return True


def sample_value(paths: list[str], folders_ok: bool) -> str:
    """One sample-sheet value naming every file of a sample.

    Never a wildcard — nf-schema refuses a pattern in a path column. A folder
    stands for the files only when it holds those and no others with reads,
    since a pipeline taking one gathers all of them. What cannot be said as
    one path is handed back as a list, which the save then explains rather
    than a scan quietly dropping a file.
    """
    if len(paths) == 1:
        return paths[0]
    folder = os.path.commonpath(paths)
    if folders_ok and os.path.isdir(folder):
        under = {p for p in files_under(folder, FASTQ_RE) if _has_reads(p)}
        if under == set(paths):
            return folder
    return ",".join(paths)


def detect_samples_files(folder=None, folders_ok=True):
    """
    Detects fastq files up to 2 levels deep, ignoring those with no reads.
    Uses folder context for 'barcode*' directories and
    common prefix grouping for others.
    """
    target = folder or Config.IMPORT_FOLDER
    if not os.path.exists(target):
        return {}

    root_base = os.path.abspath(target)
    base_level = root_base.count(os.sep)

    chunk_suffix_pattern = re.compile(r'([._-](part\d+|\d+|[Rr][12]))$', re.IGNORECASE)

    samples_map = defaultdict(list)

    for root, dirs, files in os.walk(root_base):
        current_depth = root.count(os.sep) - base_level
        if current_depth >= 2:
            dirs[:] = []

        # A folder whose reads are all empty is a barcode nothing was read
        # into, not a sample: it is left out with them.
        current_fastq = [f for f in sorted(files)
                         if FASTQ_RE.search(f) and _has_reads(os.path.join(root, f))]
        if not current_fastq:
            continue

        folder_name = os.path.basename(root)

        if folder_name.lower().startswith("barcode"):
            names_only = [FASTQ_RE.sub('', f) for f in current_fastq]
            prefix = os.path.commonprefix(names_only)
            sample_name = re.sub(r'[._-]+$', '', prefix)

            if len(sample_name) < 2:
                sample_name = folder_name

            for f in current_fastq:
                samples_map[sample_name].append(os.path.join(root, f))

        else:
            for f in current_fastq:
                basename = FASTQ_RE.sub('', f)
                sample_identity = chunk_suffix_pattern.sub('', basename)
                sample_name = re.sub(r'[._-]+$', '', sample_identity)
                samples_map[sample_name].append(os.path.join(root, f))

    return {sample: sample_value(sorted(paths), folders_ok)
            for sample, paths in samples_map.items()}
