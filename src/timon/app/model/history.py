"""What a run was, kept beside what it wrote.

Every run leaves a folder behind, and this is the note timon leaves in it:
which pipeline wrote it, pinned to which revision, with what configuration,
over which samples, and how it ended. That note is the whole of timon's
memory — listing past runs is reading the notes in the input folder, and
reopening one is handing its note back to the Experiment the form is written
against.

The note lives *inside* the run's own output folder rather than in an index
of its own, so there is nothing to keep in step: a folder the user deletes
takes its record with it, and no record can describe results that are not
there. Its name starts with a dot, which is already what keeps it out of the
results browser (see ``results.listing``).

Nothing here judges a run. Whether one is still going is asked of the
operating system in ``live``; whether it can be continued is a question
about nextflow's own cache and is answered in ``nfstate``; whether the
pipeline it names can still be configured is the Experiment's answer. This
module writes facts down, reads them back, and corrects a record that was
left open by a timon that did not live to close it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from . import live, nfstate

RECORD_NAME = ".timon-run.json"

# How a run ended. The first four are what nextflow's own outcome is written
# down as; INTERRUPTED is for the run that ended with nobody watching and
# left no trace of how — the machine went to sleep, or the process was
# killed outright. A run whose timon merely went away is not one of these:
# nextflow is still going, and it is still RUNNING (see ``_settled``).
RUNNING     = "running"
FINISHED    = "finished"
FAILED      = "failed"
CANCELLED   = "cancelled"
INTERRUPTED = "interrupted"

# Written into every record. It is not read back yet — the loader defaults
# every field it does not find — but a record that outlives a change of shape
# has to be able to say which shape it is.
FORMAT = 1


@dataclass(frozen=True)
class Run:
    """One past run, as its record describes it.

    Everything needed to put the configuration back into the form is here,
    including the sample rows: the sheet itself is a scratch file that the
    next save replaces, so a record that pointed at one would decay.
    """

    exp_id: str
    pipeline_id: str = ""
    revision: str = ""
    profile: str = ""
    params: dict = field(default_factory=dict)
    databases: dict = field(default_factory=dict)
    samples: list = field(default_factory=list)
    command: list = field(default_factory=list)
    # Where nextflow was launched from, which is where it keeps the history
    # and the cache a resumed run reads. Recorded because a workspace can be
    # opened from somewhere else next time, and then neither is there.
    launch_dir: str = ""
    out_dir: str = ""
    # The nextflow session this run was, once nextflow has written it down.
    # Empty until then, and the only thing `-resume` can be given.
    session: str = ""
    # The nextflow doing the work, and the file it is writing its output to.
    # Both outlive the timon that started the run, which is what lets a
    # later one find the run still going and show what it is saying.
    pid: int = 0
    log: str = ""
    status: str = RUNNING
    exit_code: int | None = None
    started_at: float = 0.0
    ended_at: float | None = None

    @property
    def ended(self) -> bool:
        return self.status != RUNNING

    @property
    def duration(self) -> float:
        """Seconds the run took, or 0 while it is still going."""
        if not self.started_at or not self.ended_at:
            return 0.0
        return max(0.0, self.ended_at - self.started_at)


# ── where a record lives ─────────────────────────────────────────────────────

def record_path(output_folder, exp_id: str) -> Path:
    """The note for one run: inside the folder that run writes."""
    return Path(output_folder) / exp_id / RECORD_NAME


# ── writing one ──────────────────────────────────────────────────────────────

def started(spec: dict, command: list[str], pid: int = 0,
            log: str = "") -> Run:
    """Write down a run that has just been launched, and return the record.

    Called once nextflow is actually running: a configuration that could not
    be built into a command, or a launch that raised, is not a run and has no
    business in the list of them.

    A run continuing an earlier one takes over that one's record — a folder
    holds one run, not a pile of attempts — but keeps the session it was
    continuing from until nextflow has given this attempt one of its own
    (see ``finished``). Without that, a restart the user interrupts would be
    left with nothing to continue, having had something to continue a moment
    before.
    """
    previous = load(spec["output_folder"], spec["exp_id"])
    run = Run(
        exp_id=spec["exp_id"],
        pipeline_id=spec.get("pipeline_id", ""),
        revision=spec["pipeline"].get("revision") or "",
        profile=spec.get("profile", ""),
        params=dict(spec.get("params") or {}),
        databases=dict(spec.get("databases") or {}),
        samples=[dict(row) for row in (spec.get("samples") or [])],
        command=list(command),
        pid=pid,
        log=log,
        launch_dir=os.getcwd(),
        out_dir=os.path.join(spec["output_folder"], spec["exp_id"]),
        session=previous.session if previous else "",
        status=RUNNING,
        started_at=time.time(),
    )
    return save(run)


def finished(run: Run, status: str, exit_code: int, session: str = "") -> Run:
    """Write down how a run ended. The session is what a restart resumes."""
    return save(replace(run, status=status, exit_code=exit_code,
                        session=session or run.session, ended_at=time.time()))


def cancelled(output_folder, exp_id: str, session: str = "") -> Run | None:
    """Write down that a run was stopped on purpose.

    For the run that was stopped by a timon other than the one that started
    it, where there is no live record object to close off — only the note on
    disk. It has to be written at the moment of stopping, because nothing
    afterwards can tell a run someone stopped from one that failed: that is
    the same thing as far as nextflow's own history is concerned.
    """
    run = _read(record_path(output_folder, exp_id))
    if run is None or run.status != RUNNING:
        return run
    return save(replace(run, status=CANCELLED, session=session or run.session,
                        ended_at=time.time()))


def save(run: Run) -> Run:
    """Put a record on disk, creating the run's folder if nextflow has not.

    Written to the folder the record describes, which is the only place it
    can be looked for. A failure to write is swallowed: timon's memory of a
    run is worth less than the run itself, and a workspace that cannot be
    written to must not take a pipeline down with it.
    """
    if not run.out_dir:
        return run
    path = Path(run.out_dir) / RECORD_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump({"format": FORMAT, **asdict(run)}, handle, indent=2)
    except OSError:
        pass
    return run


# ── reading them back ────────────────────────────────────────────────────────

_FIELDS = set(Run.__dataclass_fields__)


def _read(path: Path) -> Run | None:
    """One record, or None for anything that is not one.

    Tolerant on purpose: a record is read by a timon that may be older or
    newer than the one that wrote it, so unknown keys are dropped and missing
    ones take the dataclass default. A file that is not JSON at all is not a
    record and is passed over rather than reported — the folder it sits in is
    still a folder the results browser will show.
    """
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("exp_id"):
        return None
    return Run(**{k: v for k, v in data.items() if k in _FIELDS})


# How nextflow's own word for an outcome is written down here. A run whose
# timon did not live to record the ending has one of these and nothing else.
FROM_NEXTFLOW = {nfstate.OK: FINISHED, nfstate.ERR: FAILED}


def _settled(run: Run, active: str) -> Run:
    """A record still claiming to run, judged against what is actually running.

    ``active`` is the run this timon has going, if any. Anything else marked
    running is asked about properly, because a run outlives the timon that
    started it: the process may well still be there, started by a timon that
    has since been closed, and calling that run interrupted would be worse
    than saying nothing.

    Once it is established that nothing is running, the record is closed off
    here — written, not just reported. Nextflow keeps its own history and
    closes its line off whether or not timon was watching, so how the run
    ended is usually known even though the process that should have written
    it down is gone. A record only has to be corrected once.
    """
    if run.status != RUNNING or run.exp_id == active:
        return run
    if live.find(run.out_dir):
        return run
    session = nfstate.session_id(run.launch_dir, run.out_dir) or run.session
    status = FROM_NEXTFLOW.get(nfstate.status_of(run.launch_dir, run.out_dir),
                               INTERRUPTED)
    return save(replace(run, status=status, session=session))


def load(output_folder, exp_id: str, active: str = "") -> Run | None:
    """The record for one run identifier, or None if there is not one."""
    if not exp_id:
        return None
    run = _read(record_path(output_folder, exp_id))
    return _settled(run, active) if run else None


def runs(output_folder, active: str = "") -> list[Run]:
    """Every run recorded in this workspace, most recent first.

    A folder with no record is not a run — nextflow's ``work``, a quick
    test's outputs, a folder of the user's own — and is simply not listed.
    """
    root = Path(output_folder)
    found: list[Run] = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return []
    for entry in entries:
        if not entry.is_dir():
            continue
        run = _read(Path(entry.path) / RECORD_NAME)
        if run:
            found.append(_settled(run, active))
    found.sort(key=lambda r: r.started_at, reverse=True)
    return found


class RunUnavailable(Exception):
    """A recorded run cannot be put back as it ran.

    Only for what makes launching that run impossible: it is still going, or
    the pipeline or the container engine it names is no longer one timon
    offers for it. Everything else about an old record (a database that
    moved, reads that are gone, a revision that has since been bumped) is
    the run's to run into, and nextflow's to report when it does.
    """
