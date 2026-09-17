"""Finding Nextflow, building its command line, and running it.

Nothing here writes anything for the page: the status of the engine is
reported as facts (found / where / which version) and the end of a run as an
outcome, and it is ``presenters.py`` and ``events.py`` that put those into
words. That is also what makes this module usable without a browser attached
to it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Optional

from ..config import Config
from . import history, live, nfstate
from .nfstate import NEXTFLOW_DIR, can_resume, session_id  # noqa: F401
from .params import inactive_ids, param_defaults

# Nextflow flag each database a pipeline declares under "reference_data" is
# passed under. Kept apart from the generic --<param id> loop because none of
# them is a parameter of the form: timon finds them (timon.paths).
REFERENCE_FLAGS = {
    "kraken_db":  "--kraken_db",
    "gtdbtk_db":  "--gtdbtk_db",
    "genomes_db": "--genomes_db",
}


# Written into the input folder beside the sample sheet and passed with -c.
# A file rather than `-process.resourceLimits` on the command line: nextflow
# parses that one as a string and the run dies inside the first task.
RESOURCES_CONFIG_NAME = ".timon_resources.config"


class WorkflowError(RuntimeError):
    """A run cannot be started with the current configuration."""


# ── the engine ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Engine:
    """What is known about the nextflow on this machine, as facts only."""

    binary: str          # what was looked for: "nextflow", or TIMON_NEXTFLOW
    path: str = ""       # where it was found; "" when it was not
    version: str = ""    # what `nextflow -v` said; "" when it could not be asked

    @property
    def found(self) -> bool:
        return bool(self.path)


def nextflow_bin() -> str:
    """Sites that provide their own nextflow (`module load`) can point at it."""
    return os.getenv("TIMON_NEXTFLOW", "nextflow")


def run_environment(base: Optional[dict] = None) -> dict:
    """The environment nextflow is launched with.

    Its output is a file, not a terminal, and the console library nextflow
    draws with strips every escape sequence it is not writing to a tty —
    cursor moves included. The table it redraws in place then lands in the
    log once per redraw, a block under a block. Passthrough keeps the
    sequences, and the console is what obeys them. Added to NXF_OPTS rather
    than replacing it: a site sets its JVM heap there.
    """
    env = dict(os.environ if base is None else base)
    flag = "-Djansi.passthrough=true"
    opts = env.get("NXF_OPTS", "")
    if flag not in opts.split():
        env["NXF_OPTS"] = f"{opts} {flag}".strip()
    return env


@lru_cache(maxsize=8)
def _version(exe: str) -> str:
    """Cached per resolved path: launching nextflow costs about a second."""
    try:
        proc = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr).strip()


def engine() -> Engine:
    """Whether nextflow can actually be launched.

    `which` is re-checked on every call so installing nextflow and reloading
    the page reports the truth; only the version string is cached.
    """
    binary = nextflow_bin()
    exe = shutil.which(binary)
    if not exe:
        return Engine(binary=binary)
    return Engine(binary=binary, path=exe, version=_version(exe))


# ── the container engine ─────────────────────────────────────────────────────
#
# Nextflow does not provision a task itself: every one of them runs inside a
# container, and the engine that makes it is the profile's, not timon's. It is
# no more a python dependency than nextflow is, and a run launched without it
# does not fail to start — it starts, downloads a pipeline, and dies inside its
# first task with an error about a command not found. That is worth catching
# before the run rather than in the log, so it is asked the same way nextflow
# is: found, where, which version, and the run button waits on the answer.

# The command each profile needs on this machine. A profile absent from here
# is one timon has no way to look for — "wave" containerises tasks in Seqera's
# cloud, and there is nothing local to find — and such a profile is reported
# ready, because refusing a run over a check that cannot be made is worse than
# letting nextflow give its own error.
CONTAINER_BINARIES = {
    "docker":       "docker",
    "podman":       "podman",
    "singularity":  "singularity",
    "apptainer":    "apptainer",
    "shifter":      "shifter",
    "charliecloud": "ch-run",
    "conda":        "conda",
    "mamba":        "mamba",
}

# Of those, the ones that are a client talking to a daemon, where being on
# PATH says nothing about whether anything will run: Docker Desktop installed
# and Docker Desktop started are different states, and only the second one is
# a machine a run works on.
DAEMON_PROFILES = {"docker", "podman"}

# How long a daemon's answer is trusted for. A version cannot change under a
# running timon and is cached outright; whether the daemon is up changes all
# the time — starting Docker and reloading the page has to report the truth —
# so this is only long enough that a page and the saves behind it do not each
# pay for the same probe.
DAEMON_TTL = 5.0

_daemon_answers: dict[str, tuple[float, bool]] = {}


@dataclass(frozen=True)
class Container:
    """What is known about the container engine a run would be launched under."""

    profile: str             # the nextflow profile: docker, apptainer, …
    binary: str = ""         # what to look for; "" when there is nothing local
    path: str = ""           # where it was found; "" when it was not
    version: str = ""        # what `<binary> --version` said
    daemon: Optional[bool] = None   # did it answer; None when it has no daemon

    @property
    def found(self) -> bool:
        return bool(self.path)

    @property
    def ready(self) -> bool:
        """Whether a run launched under this profile would have an engine.

        True for a profile timon cannot look for: an unchecked engine is an
        unknown, and an unknown must not hold the run button down.
        """
        if not self.binary:
            return True
        return self.found and self.daemon is not False


@lru_cache(maxsize=8)
def _container_version(exe: str) -> str:
    """Cached per resolved path, like nextflow's: only the first line is kept.

    `--version` rather than nextflow's `-v`: to singularity that one means
    verbose.
    """
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True,
                              text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    lines = (proc.stdout or proc.stderr).strip().splitlines()
    return lines[0].strip() if lines else ""


def _daemon_answers_now(exe: str) -> bool:
    """Whether the engine behind this client will actually run a container.

    `info` is the cheapest question that reaches past the client: it fails
    while the daemon is down, which is exactly the state a laptop is in
    between booting and starting Docker.
    """
    now = time.monotonic()
    cached = _daemon_answers.get(exe)
    if cached is not None and now - cached[0] < DAEMON_TTL:
        return cached[1]
    try:
        proc = subprocess.run([exe, "info"], capture_output=True,
                              text=True, timeout=20)
        answered = proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # A timeout included: a daemon that cannot answer in twenty seconds
        # is not one a run should be started against.
        answered = False
    _daemon_answers[exe] = (now, answered)
    return answered


def container(profile: str = "") -> Container:
    """Whether the engine a run would be containerised by is there.

    Re-checked on every call for the same reason nextflow is: installing an
    engine, or starting one, has to be visible on a reload.
    """
    name = profile or Config.PROFILE
    binary = CONTAINER_BINARIES.get(name, "")
    if not binary:
        return Container(profile=name)
    exe = shutil.which(binary)
    if not exe:
        return Container(profile=name, binary=binary)
    return Container(
        profile=name,
        binary=binary,
        path=exe,
        version=_container_version(exe),
        daemon=_daemon_answers_now(exe) if name in DAEMON_PROFILES else None,
    )


# ── what this machine can be asked for ───────────────────────────────────────

def _physical_memory_gb() -> int:
    """Total RAM in whole gigabytes, or 0 where it cannot be asked for."""
    try:
        total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return 0
    return int(total / (1024 ** 3))


def resource_limits() -> dict:
    """The ceiling a task's request is capped at, as nextflow resourceLimits.

    nf-core pipelines size their requests for a cluster — mag-ont asks 36 GB
    for a process it labels *medium* — and nextflow refuses a run whose request
    exceeds the machine rather than scaling it down to fit. Since timon runs
    where it was launched, and that is usually a laptop, a run with no ceiling
    fails on its very first task.

    So timon states what is actually there. This is a cap, not a reservation:
    it only ever lowers what a process asks for.

    The three environment variables override it, which is what a shared node
    wants — the machine's own totals are not a share of it.
    """
    limits: dict[str, str] = {}

    cpus = os.getenv("TIMON_MAX_CPUS") or os.cpu_count()
    if cpus:
        limits["cpus"] = str(cpus)

    memory = os.getenv("TIMON_MAX_MEMORY")
    if not memory:
        detected = _physical_memory_gb()
        memory = f"{detected}.GB" if detected else ""
    elif not memory[0].isdigit():
        memory = ""
    if memory:
        # Groovy memory literals: "16.GB" is a value, "16 GB" a syntax error.
        limits["memory"] = memory.replace(" ", ".")

    # No machine answer for time — a laptop has no wall clock limit — so this
    # one only appears when it is asked for.
    walltime = os.getenv("TIMON_MAX_TIME")
    if walltime:
        limits["time"] = walltime.replace(" ", ".")

    return limits


def render_resources(limits: dict) -> str:
    """The limits as the nextflow config file that carries them."""
    body = ", ".join(f"{key}: {value}" for key, value in limits.items())
    return (
        "// Written by timon before each run, and overwritten by the next one.\n"
        "// It caps what a process may ask for at what this machine has, so a\n"
        "// pipeline sized for a cluster still runs here. Set TIMON_MAX_CPUS,\n"
        "// TIMON_MAX_MEMORY or TIMON_MAX_TIME to say otherwise.\n"
        f"process.resourceLimits = [ {body} ]\n"
    )


def resources_config_path(spec: dict) -> str:
    """Where that file goes: in the output folder, hidden, beside the runs."""
    return os.path.join(spec["output_folder"], RESOURCES_CONFIG_NAME)


def write_resources_config(spec: dict) -> str | None:
    """Write the ceiling for this run, and say where. None when there is none."""
    limits = resource_limits()
    if not limits:
        return None
    path = resources_config_path(spec)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as handle:
        handle.write(render_resources(limits))
    return path


# ── the command line ─────────────────────────────────────────────────────────

def _revision(pipe: dict) -> str:
    """The commit or tag a run is pinned to, or a refusal.

    An unpinned pipeline would resolve to whatever the default branch happens
    to be today, so two runs of the same timon version could not be compared.
    Refuse rather than produce something uncitable.
    """
    revision = pipe.get("revision")
    if not revision:
        raise WorkflowError(
            f"pipeline {pipe['name']!r} has no pinned revision — refusing to "
            "run, because the result would not be reproducible"
        )
    return revision


def _container_profile(spec: dict) -> str:
    """The engine profile this run is launched under, or a refusal."""
    pipe = spec["pipeline"]
    profile = spec.get("profile") or Config.PROFILE
    if profile not in pipe.get("profiles", []):
        supported = ", ".join(pipe.get("profiles", [])) or "none"
        raise WorkflowError(
            f"pipeline {pipe['name']!r} does not support profile "
            f"{profile!r} (supported: {supported})"
        )
    return profile


def output_dir(spec: dict) -> str:
    """Where a run writes: a folder of its own inside the output folder.

    Named here rather than only inside build_command because more than the
    command line needs it — it is where the run's record goes, where its log
    goes, and what says whether some other timon is already running this run.
    """
    return os.path.join(spec["output_folder"], spec["exp_id"])


def work_dir(spec: dict) -> str:
    """Nextflow's scratch directory, shared by every run of this workspace.

    Hidden, because it is nextflow's rather than the user's: it holds a copy
    of every intermediate a run produced, it is what `-resume` reads, and a
    results browser that listed it would put a directory nobody asked for at
    the top of the results. The leading dot is the same rule that keeps a
    run's own note out of that list.
    """
    return os.path.join(spec["output_folder"], ".work")


def test_output_dir(spec: dict) -> str:
    """Where a quick test writes, which is never where a real run writes.

    Named after the pipeline rather than after the run being configured: a
    test is of the install, it can be asked for before anything has been
    filled in, and it must not land on top of results someone is keeping.
    """
    return os.path.join(spec["output_folder"], f"{spec['pipeline']['name']}_test")


def build_test_command(spec: dict) -> list[str]:
    """The invocation of a pipeline's own test profile.

    Pure, like build_command, and a smoke test of the install rather than of
    a configuration: the profile brings its own sample sheet, parameters and
    databases, so nothing the form holds is passed on. Only where it writes
    is overridden — left alone, an nf-core test profile writes inside
    nextflow's own copy of the pipeline, which is nowhere the user can look.
    """
    pipe = spec["pipeline"]
    test_profile = pipe.get("test_profile")
    if not test_profile:
        raise WorkflowError(f"pipeline {pipe['name']!r} ships no test profile")

    cmd = [
        nextflow_bin(), "run", pipe["pipeline"],
        "-r",        _revision(pipe),
        "-profile",  f"{test_profile},{_container_profile(spec)}",
        "--outdir",  test_output_dir(spec),
        "-w",        work_dir(spec),
        "-ansi-log", "true",
    ]
    # A test profile is sized for a CI runner, which is not necessarily
    # smaller than the machine this is running on.
    if resource_limits():
        cmd.extend(["-c", resources_config_path(spec)])
    return cmd


def build_command(spec: dict) -> list[str]:
    """The nextflow invocation a run configuration describes.

    Pure: it reads the spec Experiment.run_spec() hands over and returns
    argv, so what a configuration would run can be checked without running it.
    Raises WorkflowError for a configuration that must not be launched at all.
    """
    pipe = spec["pipeline"]
    revision = _revision(pipe)
    profile = _container_profile(spec)

    out_dir = output_dir(spec)

    cmd = [
        nextflow_bin(), "run", pipe["pipeline"],
        "-r",        revision,
        "-profile",  profile,
        "--input",   spec["samplesheet"],
        "--outdir",  out_dir,
        "-w",        work_dir(spec),
        # The live table nextflow draws in a terminal, rather than a line per
        # task: the console redraws it in place (run_environment says why it
        # reaches the log at all).
        "-ansi-log", "true",
    ]

    # Continuing a run this identifier already had: every task whose inputs
    # this configuration did not change is taken from the cache, and only
    # what the fix actually touched runs again. Named by session rather than
    # left bare, which would continue whichever run happened to be the last
    # one in this directory. Whether there is a session to name is settled
    # before the spec is built (Experiment.resume_session).
    if spec.get("resume"):
        cmd.extend(["-resume", spec["resume"]])

    # The ceiling this machine imposes. Named here and written by
    # WorkflowRun.start(), so that what a configuration *would* run can still
    # be built without touching the disk.
    if resource_limits():
        cmd.extend(["-c", resources_config_path(spec)])

    # Only what the pipeline does not already default to is worth putting
    # on the command line: a flag whose default is false is set by naming it,
    # but one that defaults to *true* can only be turned off explicitly.
    # (Nextflow parses the string "false" back into a boolean.)
    defaults = param_defaults(pipe)
    for k, v in spec["params"].items():
        if isinstance(v, bool):
            if v:
                cmd.append(f"--{k}")
            elif defaults.get(k) is True:
                cmd.extend([f"--{k}", "false"])
        elif v is not None and str(v).strip() != "":
            # A value starting with a dash is read by nextflow as the next
            # option: `--flye_args --careful` arrives as flye_args=true.
            # Joined with `=` it arrives whole.
            if str(v).startswith("-"):
                cmd.append(f"--{k}={v}")
            else:
                cmd.extend([f"--{k}", str(v)])

    # The databases, at the paths the spec was given (Experiment.database_paths
    # found them; a reopened run brings the ones it ran with). Whether they
    # are on disk is not asked here — that is what keeps this pure, and it
    # has been settled before a run can start (Experiment.is_ready). One this
    # configuration skips the step of is not named: that would describe a run
    # that never opens it.
    unused = inactive_ids(pipe, spec["params"])
    for key in pipe.get("reference_data") or []:
        if key in unused:
            continue
        path = str((spec.get("databases") or {}).get(key, "")).strip()
        if not path:
            raise WorkflowError(f"no path for the {key} this run reads")
        cmd.extend([REFERENCE_FLAGS[key], path])

    return cmd


# ── the run ──────────────────────────────────────────────────────────────────
#
# A run is deliberately not owned by the timon that started it. Nextflow is
# launched in a session of its own and writes to a file rather than into a
# pipe, so quitting timon, losing the terminal or closing the browser leaves
# the workflow going and leaves its output being written. A run is hours of
# compute; the page watching it is not worth ending it for.
#
# What follows from that is that almost nothing here is privileged. Whether a
# run is going is ``live``'s answer, what it is saying is its log, and
# stopping it is a signal — all three the same for a run this timon started
# and one it found. WorkflowRun is only what an owner can do that a finder
# cannot: wait on the process and write down how it ended.


class Outcome(Enum):
    """How a run ended. The words shown for each are the view's business."""

    FINISHED  = "finished"
    CANCELLED = "cancelled"
    FAILED    = "failed"


# How each of those is written into the run's record. Spelled out rather than
# leaning on the values above happening to match: two vocabularies that agree
# by coincidence are one rename away from disagreeing silently.
RECORDED_AS = {
    Outcome.FINISHED:  history.FINISHED,
    Outcome.CANCELLED: history.CANCELLED,
    Outcome.FAILED:    history.FAILED,
}


def stop(entry: live.Live) -> bool:
    """Stop a run — any run on this machine, not only this timon's.

    The record is closed off here rather than left to be worked out
    afterwards, because afterwards it cannot be: nextflow's own history says
    only that the run did not finish, and a run somebody stopped on purpose
    would come back as a failure.
    """
    stopped = live.stop(entry)
    if not stopped:
        return False
    live.forget(entry)
    if entry.kind == live.RUN:
        history.cancelled(entry.output_folder, entry.exp_id,
                          nfstate.session_id(entry.launch_dir, entry.out_dir))
    return True


class WorkflowRun:
    """The nextflow this timon started, while it is still this timon's to wait on.

    Starting one is refused rather than queued: two nextflows in the same
    output folder would overwrite each other's results and fight over the
    same work directory, and that is true whether the other one belongs to
    this timon or to a timon running in another window.
    """

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False
        # The pointer that says this run is going, from the moment it is
        # launched until it is over. What other timons find it by.
        self._entry: Optional[live.Live] = None
        # The note left in the output folder for this run, from the moment it
        # is launched until it is closed off in outcome(). None for a quick
        # test, which is of the install rather than of a configuration and so
        # is not one of the runs a user goes looking for.
        self._record: Optional[history.Run] = None
        self.command: list[str] = []

    @property
    def running(self) -> bool:
        """Whether the process this timon started is still going."""
        return self._process is not None and self._process.poll() is None

    @property
    def entry(self) -> Optional[live.Live]:
        """The run in flight, as anything watching or stopping it needs it."""
        return self._entry

    def start(self, spec: dict) -> None:
        """Launch the run this spec describes. Raises WorkflowError, OSError.

        Recorded only once nextflow is actually running: a configuration that
        could not be built into a command, or a launch that raised, is not a
        run and has no business in the list of them.
        """
        entry = self._launch(build_command(spec), spec,
                             out_dir=output_dir(spec),
                             exp_id=spec["exp_id"], kind=live.RUN)
        self._record = history.started(spec, self.command,
                                       pid=entry.pid, log=entry.log)

    def start_test(self, spec: dict) -> None:
        """Launch the pipeline's own test profile over this spec's workspace.

        The same subprocess, the same console and the same stop button: a
        test that ran some other way would not be evidence about a run. It
        leaves no record — it is of the install, not of a configuration —
        but it is registered like any other run, because it is a nextflow
        that must not be started twice over one folder either.
        """
        out_dir = test_output_dir(spec)
        self._launch(build_test_command(spec), spec, out_dir=out_dir,
                     exp_id=os.path.basename(out_dir), kind=live.TEST)
        self._record = None

    def _launch(self, command: list[str], spec: dict, out_dir: str,
                exp_id: str, kind: str) -> live.Live:
        # A process this timon started and never waited on: it has ended, so
        # it is not in the way, but its record is still open and its pointer
        # is still there. Close it off before starting anything else.
        if self._process is not None and not self.running:
            self.outcome()
        if self.running:
            raise WorkflowError(
                "this timon is already running a workflow — wait for it to "
                "finish, or stop it first")
        # One workflow at a time in a workspace, and the one already going
        # need not be ours: a run survives the timon that started it, so the
        # timon in the next window may well be watching the run this one is
        # about to trample. Two in one output folder is the case that would
        # destroy results outright; two in one workspace is the case that
        # would divide a laptop between them and hand the user one console
        # for both.
        here = live.find(out_dir)
        other = here or next(iter(live.running(str(spec["output_folder"]))), None)
        if other is not None:
            where = ("that folder" if here is not None else "this workspace")
            raise WorkflowError(
                f"{other.exp_id!r} is already running in {where} "
                f"(process {other.pid}, started from {other.launch_dir}) — "
                "watch it or stop it first")

        # Built before Popen so the command a failed launch tried is still
        # there to be reported.
        self.command = command
        # The `-c` the command line names has to exist by the time nextflow
        # opens it, and it is rewritten per run: the machine may have changed,
        # and so may the environment overriding it.
        write_resources_config(spec)
        os.makedirs(out_dir, exist_ok=True)
        log = live.log_path(out_dir)
        self._cancelled = False

        # Output goes to a file, appended to so that the attempts on a folder
        # stay readable in order, and the file is what the console reads.
        # A pipe would have tied the run to this process twice over: nextflow
        # would be writing into something nobody would read once the page was
        # closed, and it would be killed by its own output the moment timon
        # quit.
        with open(log, "ab") as handle:
            handle.write(live.banner(command))
            handle.flush()
            self._process = subprocess.Popen(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=run_environment(),
                # A session of its own, which is what makes the run outlive
                # timon: a Ctrl-C in the terminal goes to timon's process
                # group and no longer reaches nextflow. It also gives the run
                # a process group of its own, so stopping it can reach the
                # tasks it spawned rather than only the process on top.
                start_new_session=True,
            )

        self._entry = live.register(live.Live(
            exp_id=exp_id,
            pid=self._process.pid,
            out_dir=out_dir,
            launch_dir=os.getcwd(),
            output_folder=str(spec["output_folder"]),
            log=log,
            command=list(command),
            kind=kind,
            started_at=time.time(),
            proc_start=live.process_start(self._process.pid),
        ))
        return self._entry

    def outcome(self) -> tuple[Outcome, int]:
        """Wait for the run to end and say how it went, with its exit code."""
        proc = self._process
        if proc is None:
            return Outcome.CANCELLED, 0
        rc = proc.wait()
        self._process = None
        entry, self._entry = self._entry, None
        if entry is not None:
            live.forget(entry)
        outcome = (Outcome.CANCELLED if self._cancelled
                   else Outcome.FINISHED if rc == 0 else Outcome.FAILED)
        # Closed off here rather than by the caller, so that a run is
        # remembered as it ended whoever was watching — and so that the
        # session nextflow gave it is read while its history line is the one
        # this directory just wrote.
        if self._record is not None:
            record, self._record = self._record, None
            history.finished(record, RECORDED_AS[outcome], rc,
                             nfstate.session_id(record.launch_dir, record.out_dir))
        return outcome, rc

    def cancel(self) -> None:
        """Stop this timon's run, and give nextflow the chance to tidy up.

        Blocking, and for as long as a minute: it is waiting for nextflow to
        take its tasks and their containers down with it, which is the part
        worth waiting for. Callers run it off the request.
        """
        entry = self._entry
        if entry is None:
            return
        self._cancelled = True
        stop(entry)


RUN = WorkflowRun()
