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

from .params import parse_number, required_trigger

EXP_ID_RE    = re.compile(r'^[A-Za-z0-9_\-]+$')
# roshab-cli's own rule (assets/schema_input.json from v0.1.0): a leading dot,
# hyphen or underscore is refused there, and a sheet timon accepted would
# otherwise be turned away by the pipeline after the run had started.
SAMPLE_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
DATE_RE      = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def validate_configuration(pipe: dict, exp_id: str, values: dict,
                           fields: list[dict]) -> list[str]:
    """Check a submitted run configuration.

    ``fields`` are only what this configuration still uses: a threshold
    belonging to a skipped step is not worth an error message.

    The databases are not judged here. They are not part of what was
    submitted — timon finds them — and a missing one is not a mistake in the
    form: the configuration is saved, and the run waits for the install
    (``Experiment.is_ready``).
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
    value = values.get(p["id"], "")
    raw = "" if value is None else str(value).strip()

    if p["type"] == "number":
        if raw == "":
            # A number declared with no default of its own (None) is one the
            # pipeline leaves unset too, so an empty field is its answer.
            if p.get("default", "") is None and not p.get("required"):
                return []
            return [f"'{p['label']}' is required"]
        val = parse_number(raw)
        if val is None:
            shown = raw if len(raw) <= 24 else raw[:24] + "…"
            return [f"'{p['label']}' must be a plain number (got: {shown!r})"]
        if p.get("step") == 1 and val != int(val):
            errors.append(f"'{p['label']}' must be a whole number (got: {raw!r})")
        # The floor is 0 when a declaration names none (params._normalise);
        # repeated here for a field that reaches validation un-normalised.
        low, high = p.get("min", 0), p.get("max")
        if val < low or (high is not None and val > high):
            errors.append(f"'{p['label']}' must be between {_bound(low)} and {_bound(high)}"
                          if high is not None else f"'{p['label']}' must be ≥ {_bound(low)}")

    # a select's enum is the whole set of accepted values
    if p["type"] == "select" and p.get("options_from") and not p.get("enum"):
        # Looked for in the database and not there: nothing the form could
        # send would be a value the step can run with.
        errors.append(f"'{p['label']}': the installed database offers no value for it")
    elif p["type"] == "select" and raw and raw not in p.get("enum", []):
        allowed = ", ".join(p.get("enum", []))
        errors.append(f"'{p['label']}': {raw!r} is not one of {allowed}")

    return errors


def _bound(value: float) -> str:
    """A declared bound as it was written: 60, not 60.0; 100000, not 1e+05."""
    return f"{int(value):,}".replace(",", "\u202f") if float(value) == int(value) else str(value)


def required_columns(pipe: dict) -> list[str]:
    """Sample-sheet columns every row has to fill.

    All of them unless the pipeline says otherwise — which is what a schema
    requiring the lot wants, and what timon did before any pipeline needed
    less. A pipeline whose own schema marks a column optional declares
    ``required_columns``; insisting on it here would refuse a sheet the
    pipeline would have taken.
    """
    declared = pipe.get("required_columns")
    return list(declared) if declared is not None else list(pipe["columns"])


def validate_samples(rows: list[dict], pipe: dict) -> list[str]:
    """Check a sample sheet, row by row, against the pipeline's columns."""
    errors: list[str] = []
    columns = pipe["columns"]
    required = required_columns(pipe)
    # Groups of columns of which a row needs at least one — a schema's "anyOf".
    either = pipe.get("one_of_columns") or []
    file_column = pipe.get("file_column")

    if not rows:
        return ["sample sheet is empty — add at least one sample"]

    for i, row in enumerate(rows):
        row_label = f"row {i + 1}"

        for col in required:
            if not str(row.get(col, "")).strip():
                errors.append(f"{row_label} · '{col}' is required")

        for group in either:
            if not any(str(row.get(col, "")).strip() for col in group):
                named = " or ".join(f"'{col}'" for col in group)
                errors.append(f"{row_label} · one of {named} is required")

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
                    f"{row_label} · 'sample_id': must start with a letter or digit, "
                    "then only letters, digits, hyphens, dots and underscores"
                )

    counts = Counter(str(r.get("sample_id", "")).strip() for r in rows)
    for sid, n in counts.items():
        if sid and n > 1:
            errors.append(f"duplicate sample_id: {sid!r}")

    return errors
