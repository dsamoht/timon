"""The run being configured: which pipeline, with what, over which samples.

This is the whole of the application's state, and it is the only thing that
changes it. A route hands over what arrived — an identifier, a mapping of
submitted values, a list of sample rows — and gets back the reasons it was
refused, if it was; nothing outside reaches into the parameters, edits the
sample list, or writes the sample sheet itself. That is what keeps "which
parameters does this run actually use" a single answer rather than one per
caller.
"""

from __future__ import annotations

import os
import uuid

import pandas as pd

from pathlib import Path

from ...paths import DATABASE_OPTIONS, REFERENCE_DATA
from ..config import PIPELINES, Config
from . import history, live
from . import params as P
from . import validation
from .history import RunUnavailable
from .nextflow import WorkflowError, build_test_command, can_resume
from .samples import detect_samples_files

DEFAULT_PIPELINE = "roshab-cli"

# What every change to a pinned run is answered with. One sentence for all of
# them, because it is one rule: nothing about a reopened run moves until the
# user has said they no longer want it to be that run.
PINNED = "this run is reopened exactly as it ran — edit it to change anything"


def selectable_pipelines() -> dict:
    """The pipelines a user may pick, in the order they are declared.

    One is written down here before it can be run — isolate-wf has no
    published repository yet — and until then it is left out rather than
    shown as a card whose only answer is a refusal. Asked in the model so
    that the card that is not offered and the switch that is refused are the
    same rule.
    """
    return {pid: pipe for pid, pipe in PIPELINES.items()
            if pipe.get("selectable", True)}


class Experiment:

    def __init__(self):
        self.reset()

    # ── state ───────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Back to a fresh run, taking the sample sheet on disk with it."""
        self._discard_samplesheet()
        self.exp_id = ""
        self.samplesheet = ""
        self.pipeline_id = DEFAULT_PIPELINE
        self.profile = Config.PROFILE
        # Two folders, and they are not the same one. The input folder is
        # where a scan looks for reads and nothing of timon's is ever written;
        # the output folder is where runs land, and so is what "this
        # workspace" means to everything that asks what is running here.
        self.input_folder = os.path.abspath(Config.IMPORT_FOLDER)
        self.output_folder = os.path.abspath(Config.OUTPUT_FOLDER)
        # Only ever filled by ``restore``: the database paths a reopened run
        # was launched with. Any other configuration has no paths of its own —
        # timon finds each database (see database_paths).
        self.recorded_databases: dict = {}
        # Left empty rather than pre-filled with defaults: the form renders the
        # declared defaults itself, and saving it writes every value back here,
        # so pre-filling would only be a second copy to keep in step.
        self.params: dict = {}
        self.samples: list[dict] = []
        # Whether a run whose identifier names one that already happened
        # should continue it rather than start it over. True because that is
        # what fixing a configuration and pressing run again means; the form
        # offers to turn it off, and it only ever matters when there is a
        # recorded run to continue (see resume_session).
        self.resume = True
        # Whether this configuration is a past run put back exactly as it ran
        # (see restore). Only the fact is held; the run it names is the record
        # under exp_id, read from disk like every other question about it.
        self._pinned = False

    @property
    def pipeline(self) -> dict:
        return PIPELINES[self.pipeline_id]

    @property
    def n_samples(self) -> int:
        return len(self.samples)

    @property
    def revision(self) -> str:
        """The revision this configuration would be launched at.

        The pipeline's pinned tag — except for a pinned run, which is launched
        at the revision it ran at: a bumped revision is different code, and
        neither its failure nor its cache is the reopened run's. One answer,
        so the version the page shows and the one `-r` is given agree.
        """
        previous = self.previous() if self.pinned else None
        if previous is not None and previous.revision:
            return previous.revision
        return self.pipeline.get("revision") or ""

    @property
    def pinned(self) -> bool:
        """Whether this is a reopened run that nothing may change.

        Only while its record is still there: a folder deleted from under a
        pinned run has taken the run with it, and what is left is an ordinary
        configuration that happens to hold its values.
        """
        return self._pinned and self.previous() is not None

    def unpin(self) -> None:
        """Stop being the run that was reopened, keeping everything it held.

        The one way out, and a deliberate one. What follows is an ordinary
        configuration — edited, validated and saved like any other — so a
        failure after this is no longer evidence about the run that was
        reopened, which is exactly why it is not the default.
        """
        self._pinned = False
        self.recorded_databases = {}

    def set_pipeline(self, pipeline_id: str) -> bool:
        """Switch pipelines, which starts the configuration and sheet over.

        A sample sheet is written to a pipeline's columns and the parameters
        are its own, so neither survives the switch.
        """
        if self.pinned or pipeline_id not in selectable_pipelines():
            return False
        self.pipeline_id = pipeline_id
        self.params = {}
        self.samples = []
        self._discard_samplesheet()
        return True

    def is_ready(self) -> bool:
        """Whether this configuration is one nextflow could be launched on.

        The one answer to that question: the run button, the socket handler
        that would start the process and any future caller all ask it here, so
        an enabled button and a run that starts cannot disagree.
        """
        if not self.exp_id or not self.samplesheet or not self.output_folder:
            return False
        if self.profile not in self.pipeline.get("profiles", []):
            return False
        # A pinned run is launched with the databases it ran with and is not
        # re-judged (see restore): if one has moved, nextflow says so, from
        # the run. Anything else waits until every database it reads is there
        # — which is what makes installing them the first thing to do.
        return self.pinned or not self.missing_databases()

    def needed_databases(self) -> list[str]:
        """Every database this configuration reads, whether it is there or not.

        A database belonging to a step this run skips is not in the list at
        all — it is not read, so it cannot be missing.
        """
        inactive = P.inactive_ids(self.pipeline, self.params)
        return [key for key in self.pipeline.get("reference_data", [])
                if key in REFERENCE_DATA and key not in inactive]

    def database_paths(self) -> dict[str, str]:
        """Where each database this run reads is, as nextflow will be told.

        Found by timon, never typed: timon.paths knows where each one is
        installed and which variable names a copy elsewhere, so every pipeline
        that reads a database is pointed at the same one. A reopened run is
        the exception and keeps the paths it ran with — a run from before a
        database was reinstalled elsewhere is repeated as it was.
        """
        recorded = self.recorded_databases if self.pinned else {}
        return {key: str(recorded.get(key) or REFERENCE_DATA[key].locate())
                for key in self.needed_databases()}

    def missing_databases(self) -> list[str]:
        """Those of them timon cannot find on disk right now.

        The one answer to "does this machine have what this run reads": the
        notice in the page, the button that offers to fetch them and the run
        that refuses to start are reading the same list. Keys, not sentences —
        what to call a database and how to put the bad news is the view's
        half.

        Asked of the filesystem each time, so installing one — by the button,
        or by hand — is noticed on the next ask. As with nextflow itself,
        nothing is remembered that the disk can be asked.
        """
        if self.pinned:
            return [key for key, path in self.database_paths().items()
                    if not os.path.exists(path)]
        return [key for key in self.needed_databases()
                if not REFERENCE_DATA[key].present()]

    # ── what is going right now ─────────────────────────────────────────────

    def in_flight(self) -> list:
        """Every run going in this workspace, whoever started it.

        Asked of the machine rather than of this process: a run survives the
        timon that launched it, so the workspace may well have one going that
        this timon knows nothing about — that is the case this answers for.
        """
        return live.running(self.output_folder)

    # ── the run this one would continue ─────────────────────────────────────

    def previous(self) -> history.Run | None:
        """The recorded run this configuration would write into, if there is one.

        Read from disk on each ask rather than held on the experiment: the
        output folder *is* the record, so a user who deletes one between two
        page loads has said something, and a copy here would go on claiming
        otherwise.
        """
        return history.load(self.output_folder, self.exp_id)

    def resumable(self) -> bool:
        """Whether there is a previous run of this identifier to continue.

        A record is not enough: nextflow's cache for that session has to
        still be where it left it, which a workspace opened from a different
        directory is not. Asked in the model so that the offer the form makes
        and the flag the command line gets cannot disagree.
        """
        previous = self.previous()
        return bool(previous) and can_resume(previous.launch_dir, previous.session)

    def resume_session(self) -> str:
        """The session `-resume` is given, or "" for a run that starts over."""
        previous = self.previous()
        if not self.resume or previous is None:
            return ""
        return previous.session if can_resume(previous.launch_dir,
                                              previous.session) else ""

    def restore(self, record: history.Run) -> None:
        """Become a recorded run again, exactly as it ran, and stay that run.

        Nothing is re-judged. The workflow, its revision, the engine, every
        parameter, every database path and every sample row are the record's,
        and the configuration is pinned to them: no switch, no save and no
        sheet edit is accepted until ``unpin``. That is what makes running it
        again a repeat of the run rather than of whatever the form says now —
        if it fails the same way, the failure is nextflow's to report, from
        the run, and not a validation message standing in front of it.

        So a database that has since moved or reads that were tidied away are
        not reasons given here: the run is launched as it was, and it is the
        run that says what it could not find. Only what makes it impossible
        to launch that run at all is refused.
        """
        if record.status == history.RUNNING:
            raise RunUnavailable(f"{record.exp_id!r} is still running — watch it instead")
        if record.pipeline_id not in selectable_pipelines():
            raise RunUnavailable(
                f"this run was made with {record.pipeline_id!r}, which timon "
                "no longer offers")
        declared = PIPELINES[record.pipeline_id].get("profiles", [])
        if record.profile and record.profile not in declared:
            raise RunUnavailable(
                f"this run used the container engine {record.profile!r}, which "
                f"{record.pipeline_id!r} no longer declares")

        self._pinned = False
        self.set_pipeline(record.pipeline_id)
        if record.profile:
            self.profile = record.profile
        self.exp_id = record.exp_id
        self.params = dict(record.params)
        # A record from before timon found the databases itself may name only
        # some of them; the rest are looked for where they are now.
        self.recorded_databases = dict(record.databases or {})
        self._write_samplesheet(record.samples)
        self.resume = True
        self._pinned = True

    def is_testable(self) -> bool:
        """Whether this pipeline can be given the quick test of its own.

        Asked by building the command it would run and seeing whether that is
        refused, so the button and the launch cannot disagree about a missing
        test profile, an unpinned revision or an engine the pipeline does not
        support. Nothing about the configuration comes into it: a test profile
        brings its own sample sheet and its own databases, which is what makes
        it worth having before anything has been filled in.
        """
        try:
            build_test_command(self.test_spec())
        except WorkflowError:
            return False
        return True

    def test_spec(self) -> dict:
        """The little a quick test is built from: a pipeline and a workspace."""
        return {
            "pipeline":      self.pipeline,
            "output_folder": self.output_folder,
            "profile":       self.profile,
        }

    def run_spec(self) -> dict:
        """This configuration as the flat set of facts a run is built from.

        More than the command line needs: the sample rows and the pipeline's
        id are here because the record left in the output folder is written
        from this same spec, and a run that could not be reopened afterwards
        would be a run half kept.
        """
        return {
            "pipeline":     {**self.pipeline, "revision": self.revision},
            "pipeline_id":  self.pipeline_id,
            "exp_id":       self.exp_id,
            "samplesheet":  self.samplesheet,
            "output_folder": self.output_folder,
            "profile":      self.profile,
            "params":       dict(self.params),
            "databases":    self.database_paths(),
            "samples":      [dict(row) for row in self.samples],
            # Empty unless this identifier names a run there is something
            # left to continue; build_command only ever reads it.
            "resume":       self.resume_session(),
        }

    # ── the run configuration ───────────────────────────────────────────────

    def fields(self) -> list[dict]:
        """Every parameter of this pipeline, with the options this machine offers.

        A select filled from a database is filled from the one this run reads —
        a pinned run's recorded copy, so a reopened run shows the lengths it
        could have chosen from, not what a reinstall has since put elsewhere.
        """
        reads = set(self.pipeline.get("reference_data") or [])
        recorded = self.recorded_databases if self.pinned else {}
        options = {name: read(Path(recorded.get(key) or REFERENCE_DATA[key].locate()))
                   for name, (key, read) in DATABASE_OPTIONS.items() if key in reads}
        return P.fields(self.pipeline, options)

    def active_fields(self, values: dict | None = None) -> list[dict]:
        """The parameters this configuration still uses.

        Answered against ``values`` when a form is being judged — it is the
        boxes ticked in it, not what was saved last time, that decide which
        parameters are part of the run being asked for.
        """
        pipe = self.pipeline
        resolved = values if values is not None else self.params
        inactive = P.inactive_ids(pipe, resolved)
        return [p for p in self.fields() if p["id"] not in inactive]

    def apply_configuration(self, exp_id: str, values: dict,
                            resume: bool = True) -> list[str]:
        """Validate a submitted configuration and, if it holds, become it.

        Nothing is stored unless everything checks out, so a refused save
        leaves the run exactly as it was rather than half-updated.
        """
        if self.pinned:
            return [PINNED]
        pipe = self.pipeline
        fields = self.active_fields(values)
        errors = validation.validate_configuration(pipe, exp_id, values, fields)
        if errors:
            return errors

        self.resume = bool(resume)
        self._store(exp_id, values, fields)
        return []

    def _store(self, exp_id: str, values: dict, fields: list[dict]) -> None:
        """Become this configuration, having decided it is one worth becoming."""
        pipe = self.pipeline
        self.exp_id = exp_id

        # What this configuration takes out of the run goes with it. Cleared
        # rather than left alone: a value saved before a step was skipped would
        # still be handed to nextflow, describing a run that is not this one.
        active = {p["id"] for p in fields}
        for p in self.fields():
            if p["id"] in active:
                self.params[p["id"]] = P.coerce(p, values.get(p["id"]))
            else:
                self.params.pop(p["id"], None)

    # ── the sample sheet ────────────────────────────────────────────────────

    def scan_folder(self, folder: str | None = None) -> list[dict]:
        """Rows for the reads already in a folder, for the user to edit.

        The folder is the user's to choose — reads land on external drives and
        in shared folders more often than in the input folder — and the input
        folder is only where the scan looks when nobody said. Whether the
        chosen one may be read at all is the file browser's rule, settled
        before it gets here.

        Held as the current samples so a reload shows what the scan found, but
        deliberately not written: a scan is a suggestion until it is saved.
        A pinned run's rows are the ones it ran over, and are handed back as
        they are.
        """
        if self.pinned:
            return [dict(row) for row in self.samples]
        pipe = self.pipeline
        rows = []
        for name, path in detect_samples_files(folder or self.input_folder).items():
            row = {c: "" for c in pipe["columns"]}
            row[pipe["columns"][0]] = name
            row[pipe["file_column"]] = path
            rows.append(row)
        self.samples = rows
        return rows

    def set_samples(self, rows: list[dict]) -> list[str]:
        """Validate a sample sheet and, if it holds, write it for nextflow.

        The file is what `--input` points at, so it is written here, next to
        the state that names it: the previous one is removed rather than left
        behind, and a new name is drawn each time so a run reading the old one
        cannot be confused by the new.
        """
        if self.pinned:
            return [PINNED]
        rows = [{col: str(row.get(col, "")).strip() for col in self.pipeline["columns"]}
                for row in rows]
        errors = validation.validate_samples(rows, self.pipeline)
        if errors:
            return errors
        self._write_samplesheet(rows)
        return []

    def _write_samplesheet(self, rows: list[dict]) -> None:
        """Write rows out as the sheet `--input` reads, judged or not.

        Apart from the checking above because a reopened run's rows are
        written as they ran (see ``restore``).
        """
        rows = [{col: str(row.get(col, "")) for col in self.pipeline["columns"]}
                for row in rows]
        self._discard_samplesheet()
        self.samples = rows

        # In the output folder, under a leading dot: the sheet is timon's
        # scratch — rewritten by the next save and named anew each time — and
        # the input folder holds the user's reads, which timon never writes to.
        folder = self.output_folder or Config.OUTPUT_FOLDER
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f".samplesheet_{uuid.uuid4().hex}.csv")
        pd.DataFrame(rows, columns=self.pipeline["columns"]).to_csv(path, index=False)
        self.samplesheet = path

    def _discard_samplesheet(self) -> None:
        path = getattr(self, "samplesheet", "")
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                # Someone else's to clean up now — not a reason to refuse the
                # sheet that replaces it.
                pass
        self.samplesheet = ""


EXPERIMENT = Experiment()
