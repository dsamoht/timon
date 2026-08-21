"""What makes a run configuration and a sample sheet acceptable.

The rules live here rather than in the route that happens to receive them:
they are statements about a run, not about an HTTP request, and they are
written against plain values so they can be checked without one. What comes
back is a list of reasons, in the order they were found; whether those become
a list under the form, a toast, or a line on a terminal is the view's choice.
"""

from __future__ import annotations

import os
import re
from collections import Counter

from ..config import ENV_DATABASES
from .params import required_trigger

EXP_ID_RE    = re.compile(r'^[A-Za-z0-9_\-]+$')
SAMPLE_ID_RE = re.compile(r'^[A-Za-z0-9_\-\.]+$')
DATE_RE      = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def validate_configuration(pipe: dict, exp_id: str, values: dict,
                           fields: list[dict], dbs: list[dict],
                           databases: dict) -> list[str]:
    """Check a submitted run configuration.

    ``fields`` and ``dbs`` are only what this configuration still uses: a
    threshold belonging to a skipped step is not worth an error message, and
    neither is a database whose steps this run does not reach — the field is
    not even shown, so an error about it would point at nothing.
    """
    errors: list[str] = []

    if not exp_id:
        errors.append("run identifier is required")
    elif not EXP_ID_RE.match(exp_id):
        errors.append("run identifier: only letters, digits, hyphens and underscores allowed")
    elif len(exp_id) > 64 or len(exp_id) < 3:
        errors.append("run identifier: min 3 char & max 64 char allowed")

    if not pipe:
        errors.append("no pipeline selected")

    for db in dbs:
        key = db["id"]
        val = str(values.get(key, databases.get(key, ""))).strip()
        label = ENV_DATABASES.get(key, {}).get("label", key)
        if not val:
            errors.append(f"{label} path is required for this pipeline")
        # A database can be shipped as a directory or as a tarball, so this
        # asks that the path exist, not that it be a folder.
        elif not os.path.exists(val):
            errors.append(f"{label} path not found: {val!r}")

    for p in fields:
        errors.extend(_field_errors(p, values))

    # Text and select params the pipeline entry marks as required — always, or
    # only for the options this very form selects (a database read by one
    # screening mode, say).
    labels = {p["id"]: p["label"] for p in fields}
    for p in fields:
        if p["type"] not in ("text", "select"):
            continue
        trigger = required_trigger(p, values)
        if not p.get("required") and not trigger:
            continue
        if str(values.get(p["id"], "")).strip():
            continue
        if not trigger:
            errors.append(f"'{p['label']}' is required")
        else:
            key, val = trigger
            asked = "on" if val is True else repr(val)
            errors.append(f"'{p['label']}' is required when '{labels.get(key, key)}' is {asked}")

    return errors


def _field_errors(p: dict, values: dict) -> list[str]:
    """The one field, against what it was declared to accept."""
    errors: list[str] = []
    raw = str(values.get(p["id"], "")).strip()

    if p["type"] == "number":
        if raw == "":
            return [f"'{p['label']}' is required"]
        try:
            val = float(raw)
        except ValueError:
            return [f"'{p['label']}' must be a number (got: {raw!r})"]
        if p.get("step") == 1 and val != int(val):
            errors.append(f"'{p['label']}' must be a whole number (got: {raw!r})")
        if "min" in p and val < p["min"]:
            errors.append(f"'{p['label']}' must be ≥ {p['min']}")
        if "max" in p and val > p["max"]:
            errors.append(f"'{p['label']}' must be ≤ {p['max']}")

    # a select's enum is the whole set of accepted values
    if p["type"] == "select" and raw and raw not in p.get("enum", []):
        allowed = ", ".join(p.get("enum", []))
        errors.append(f"'{p['label']}': {raw!r} is not one of {allowed}")

    return errors


def validate_samples(rows: list[dict], pipe: dict) -> list[str]:
    """Check a sample sheet, row by row, against the pipeline's columns."""
    errors: list[str] = []
    columns = pipe["columns"]
    file_column = pipe.get("file_column")

    if not rows:
        return ["sample sheet is empty — add at least one sample"]

    for i, row in enumerate(rows):
        row_label = f"row {i + 1}"

        for col in columns:
            if not str(row.get(col, "")).strip():
                errors.append(f"{row_label} · '{col}' is required")

        if file_column and file_column in row:
            path = str(row[file_column]).strip()
            # A wildcard stands for files that are only resolved by nextflow,
            # so there is nothing here to look for on disk.
            if path and "*" not in path and not os.path.exists(path):
                errors.append(f"{row_label} · '{file_column}': path not found — {path!r}")

        if "date" in columns and "date" in row:
            raw_date = str(row["date"]).strip()
            if raw_date and not DATE_RE.match(raw_date):
                errors.append(f"{row_label} · 'date': expected YYYY-MM-DD (got {raw_date!r})")

        if "sample_id" in columns and "sample_id" in row:
            sid = str(row["sample_id"]).strip()
            if sid and not SAMPLE_ID_RE.match(sid):
                errors.append(
                    f"{row_label} · 'sample_id': only letters, digits, hyphens, dots and underscores allowed"
                )

    counts = Counter(str(r.get("sample_id", "")).strip() for r in rows)
    for sid, n in counts.items():
        if sid and n > 1:
            errors.append(f"duplicate sample_id: {sid!r}")

    return errors
