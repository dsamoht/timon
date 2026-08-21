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
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Iterator, Optional

from ...paths import REFERENCE_DATA, missing_reference_data
from ..config import Config
from .params import inactive_ids, param_defaults

# Nextflow flag each database declared in a pipeline's "requires_db" is passed
# under, and the same for the reference data it declares under
# "reference_data". Kept apart from the generic --<param id> loop because
# neither is a parameter of the form: one comes from the environment, the
# other from timon's own install.
DB_FLAGS = {
    "kraken_db": "--kraken_db",
    "gtdbtk_db": "--gtdbtk_db",
}

REFERENCE_FLAGS = {
    "genomes_db": "--genomes_db",
    "genes_db":   "--genes_db",
}


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


# ── the command line ─────────────────────────────────────────────────────────

def build_command(spec: dict) -> list[str]:
    """The nextflow invocation a run configuration describes.

    Pure: it reads the spec Experiment.run_spec() hands over and returns
    argv, so what a configuration would run can be checked without running it.
    Raises WorkflowError for a configuration that must not be launched at all.
    """
    pipe = spec["pipeline"]

    # An unpinned pipeline would resolve to whatever the default branch
    # happens to be today, so two runs of the same timon version could not
    # be compared. Refuse rather than produce something uncitable.
    revision = pipe.get("revision")
    if not revision:
        raise WorkflowError(
            f"pipeline {pipe['name']!r} has no pinned revision — refusing to "
            "run, because the result would not be reproducible"
        )

    profile = spec.get("profile") or Config.PROFILE
    if profile not in pipe.get("profiles", []):
        supported = ", ".join(pipe.get("profiles", [])) or "none"
        raise WorkflowError(
            f"pipeline {pipe['name']!r} does not support profile "
            f"{profile!r} (supported: {supported})"
        )

    input_folder = spec["input_folder"]
    out_dir      = os.path.join(input_folder, spec["exp_id"])
    work_dir     = os.path.join(input_folder, "work")

    cmd = [
        nextflow_bin(), "run", pipe["pipeline"],
        "-r",        revision,
        "-profile",  profile,
        "--input",   spec["samplesheet"],
        "--outdir",  out_dir,
        "-w",        work_dir,
        "-ansi-log", "false"
    ]

    # A database whose steps this configuration skips is still on the
    # experiment — the form only hid the field — but naming it here would
    # describe a run that never opens it.
    unused = inactive_ids(pipe, spec["params"])
    for db_key in pipe.get("requires_db", []):
        val = spec["databases"].get(db_key, "")
        if val and db_key not in unused:
            cmd.extend([DB_FLAGS[db_key], val])

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
            cmd.extend([f"--{k}", str(v)])

    # Reference data timon installs rather than asks for. Missing is a stop:
    # the run would fail deep inside nextflow with a path the user never typed.
    wanted = pipe.get("reference_data") or []
    if wanted:
        missing = missing_reference_data(wanted)
        if missing:
            raise WorkflowError(
                "reference data missing — set TIMON_DB_DIR to a directory "
                "holding it.\n  " + "\n  ".join(missing)
            )
        for name in wanted:
            cmd.extend([REFERENCE_FLAGS[name], str(REFERENCE_DATA[name].locate())])

    return cmd


# ── the run ──────────────────────────────────────────────────────────────────

class Outcome(Enum):
    """How a run ended. The words shown for each are the view's business."""

    FINISHED  = "finished"
    CANCELLED = "cancelled"
    FAILED    = "failed"


class WorkflowRun:
    """The nextflow subprocess, if one is running.

    The caller reads lines() to completion and then asks for outcome(); it
    never touches the Popen, so "cancelled" is decided by the cancel() that
    caused it rather than by guessing at a signal number after the fact.
    """

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False
        self.command: list[str] = []

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self, spec: dict) -> None:
        """Launch the run this spec describes. Raises WorkflowError, OSError."""
        # Built before Popen so the command a failed launch tried is still
        # there to be reported.
        self.command = build_command(spec)
        self._cancelled = False
        self._process = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

    def lines(self) -> Iterator[str]:
        """Output of the run, stderr merged, as it arrives."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return
        for line in iter(proc.stdout.readline, ''):
            if line:
                yield line

    def outcome(self) -> tuple[Outcome, int]:
        """Wait for the run to end and say how it went, with its exit code."""
        proc = self._process
        if proc is None:
            return Outcome.CANCELLED, 0
        rc = proc.wait()
        self._process = None
        if self._cancelled:
            return Outcome.CANCELLED, rc
        return (Outcome.FINISHED if rc == 0 else Outcome.FAILED), rc

    def cancel(self) -> None:
        if self._process:
            self._cancelled = True
            self._process.kill()


RUN = WorkflowRun()
