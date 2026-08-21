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

from ..config import PIPELINES, Config
from . import params as P
from . import validation
from .samples import detect_samples_files

DEFAULT_PIPELINE = "roshab-cli"


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
        self.input_folder = os.path.abspath(Config.IMPORT_FOLDER)
        self.databases = {"kraken_db": Config.KRAKEN_DB,
                          "gtdbtk_db": Config.GTDBTK_DB}
        # Left empty rather than pre-filled with defaults: the form renders the
        # declared defaults itself, and saving it writes every value back here,
        # so pre-filling would only be a second copy to keep in step.
        self.params: dict = {}
        self.samples: list[dict] = []

    @property
    def pipeline(self) -> dict:
        return PIPELINES[self.pipeline_id]

    @property
    def n_samples(self) -> int:
        return len(self.samples)

    def set_pipeline(self, pipeline_id: str) -> bool:
        """Switch pipelines, which starts the configuration and sheet over.

        A sample sheet is written to a pipeline's columns and the parameters
        are its own, so neither survives the switch.
        """
        if pipeline_id not in PIPELINES:
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
        if not self.exp_id or not self.samplesheet or not self.input_folder:
            return False
        if self.profile not in self.pipeline.get("profiles", []):
            return False
        # Only a database the run still reads: one whose steps this
        # configuration skips is not asked for, so it cannot hold a run back.
        inactive = P.inactive_ids(self.pipeline, self.params)
        return all(self.databases.get(key)
                   for key in self.pipeline.get("requires_db", [])
                   if key not in inactive)

    def run_spec(self) -> dict:
        """This configuration as the flat set of facts a run is built from."""
        return {
            "pipeline":     self.pipeline,
            "exp_id":       self.exp_id,
            "samplesheet":  self.samplesheet,
            "input_folder": self.input_folder,
            "profile":      self.profile,
            "params":       dict(self.params),
            "databases":    dict(self.databases),
        }

    # ── the run configuration ───────────────────────────────────────────────

    def active_fields(self, values: dict | None = None) -> tuple[list[dict], list[dict]]:
        """The parameters and databases this configuration still uses.

        Answered against ``values`` when a form is being judged — it is the
        boxes ticked in it, not what was saved last time, that decide which
        parameters are part of the run being asked for.
        """
        pipe = self.pipeline
        resolved = values if values is not None else self.params
        inactive = P.inactive_ids(pipe, resolved)
        return ([p for p in P.fields(pipe) if p["id"] not in inactive],
                [d for d in P.db_fields(pipe, self.databases) if d["id"] not in inactive])

    def apply_configuration(self, exp_id: str, values: dict) -> list[str]:
        """Validate a submitted configuration and, if it holds, become it.

        Nothing is stored unless everything checks out, so a refused save
        leaves the run exactly as it was rather than half-updated.
        """
        pipe = self.pipeline
        fields, dbs = self.active_fields(values)
        errors = validation.validate_configuration(
            pipe, exp_id, values, fields, dbs, self.databases)
        if errors:
            return errors

        self.exp_id = exp_id

        # Databases are held apart from the parameters: nextflow.DB_FLAGS, not
        # the generic --<id> loop, is what turns these into flags. An unused
        # one keeps whatever the environment gave it — the field is hidden,
        # not cleared, and ticking the box back on should not have lost the
        # path.
        for db in dbs:
            self.databases[db["id"]] = str(values.get(db["id"], "")).strip()

        # What this configuration takes out of the run goes with it. Cleared
        # rather than left alone: a value saved before a step was skipped would
        # still be handed to nextflow, describing a run that is not this one.
        active = {p["id"] for p in fields}
        for p in P.fields(pipe):
            if p["id"] in active:
                self.params[p["id"]] = P.coerce(p, values.get(p["id"]))
            else:
                self.params.pop(p["id"], None)
        return []

    # ── the sample sheet ────────────────────────────────────────────────────

    def scan_input_folder(self) -> list[dict]:
        """Rows for the reads already in the input folder, for the user to edit.

        Held as the current samples so a reload shows what the scan found, but
        deliberately not written: a scan is a suggestion until it is saved.
        """
        pipe = self.pipeline
        rows = []
        for name, path in detect_samples_files(self.input_folder).items():
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
        rows = [{col: str(row.get(col, "")).strip() for col in self.pipeline["columns"]}
                for row in rows]
        errors = validation.validate_samples(rows, self.pipeline)
        if errors:
            return errors

        self._discard_samplesheet()
        self.samples = rows

        folder = self.input_folder or Config.IMPORT_FOLDER
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"samplesheet_{uuid.uuid4().hex}.csv")
        pd.DataFrame(rows, columns=self.pipeline["columns"]).to_csv(path, index=False)
        self.samplesheet = path
        return []

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
