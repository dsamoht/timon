"""What nextflow remembers of its own runs.

Nextflow keeps a history and a task cache under the directory it was launched
from — for timon that is the folder the user ran it in, never the input
folder. Both are read here and nowhere else: they are nextflow's files, in
nextflow's shapes, and the rest of timon only wants the three answers they
give — which session a run was, how it ended, and whether it can still be
continued.

A run is found in that history by the output directory it wrote, because
that is the one thing on the command line that is this run and no other. The
match is against a whole argument rather than against the text of the line:
``imports/exp1`` is a substring of ``imports/exp10``, and a resume that read
the wrong line would continue a run the user never asked about.
"""

from __future__ import annotations

import shlex
from pathlib import Path

NEXTFLOW_DIR = ".nextflow"

# The columns of a line of .nextflow/history: when it started, how long it
# took, the run name, how it ended, the revision, the session id, and the
# command it was launched with. Nextflow appends the line as the run starts
# and rewrites it when the run ends, so a line found here for a run still
# going carries a status of "-".
HISTORY_TIME     = 0
HISTORY_DURATION = 1
HISTORY_NAME     = 2
HISTORY_STATUS   = 3
HISTORY_REVISION = 4
HISTORY_SESSION  = 5
HISTORY_COMMAND  = 6

# What nextflow writes in that status column once a run is over. Anything
# else — "-", or a word a later nextflow invents — means it is not over as
# far as this file is concerned.
OK  = "OK"
ERR = "ERR"


def _rows(launch_dir) -> list[list[str]]:
    """Every line of nextflow's history, oldest first, as its columns."""
    if not launch_dir:
        return []
    try:
        text = (Path(launch_dir) / NEXTFLOW_DIR / "history").read_text(errors="replace")
    except OSError:
        return []
    rows = [line.split("\t") for line in text.splitlines() if line.strip()]
    return [row for row in rows if len(row) > HISTORY_COMMAND]


def _arguments(command: str) -> list[str]:
    """The command column split the way the shell would have split it."""
    try:
        return shlex.split(command)
    except ValueError:
        # An unbalanced quote in a path timon did not write. Falling back to
        # whitespace keeps the whole-argument rule, which is the point.
        return command.split()


def _row_for(launch_dir, out_dir: str) -> list[str] | None:
    """The last line of the history that is this run.

    The last one, because a run continued into the same folder appears in
    the history once per attempt and the latest attempt is the one anybody
    is asking about — the one that holds the cache a resume would read, and
    the one whose outcome is this run's outcome.
    """
    for row in reversed(_rows(launch_dir)):
        if out_dir and out_dir in _arguments(row[HISTORY_COMMAND]):
            return row
    return None


def session_id(launch_dir, out_dir: str) -> str:
    """The session of the run that wrote ``out_dir``, as nextflow recorded it.

    Nextflow appends its history line as a run starts, so this answers for a
    run that is still going, and for one that was killed or interrupted,
    just as well as for one that finished — which are the ones worth
    continuing.
    """
    row = _row_for(launch_dir, out_dir)
    return row[HISTORY_SESSION].strip() if row else ""


def status_of(launch_dir, out_dir: str) -> str:
    """How nextflow says a run ended: OK, ERR, or "" for neither.

    Read for a run whose timon is gone: the process that would have written
    the outcome down did not live to do it, but nextflow closed its own line
    off, and that is a better answer than assuming the worst.
    """
    row = _row_for(launch_dir, out_dir)
    if row is None:
        return ""
    status = row[HISTORY_STATUS].strip()
    return status if status in (OK, ERR) else ""


def can_resume(launch_dir, session: str) -> bool:
    """Whether `-resume <session>` still has anything to read.

    The cache is a directory per session under the launch directory, so a
    workspace opened from somewhere else, or one whose ``.nextflow`` has been
    cleaned out, cannot continue anything — and saying so beforehand is the
    difference between an offer timon does not make and a run that dies on
    the command line with "unknown session".
    """
    if not launch_dir or not session:
        return False
    return (Path(launch_dir) / NEXTFLOW_DIR / "cache" / session / "db").is_dir()
