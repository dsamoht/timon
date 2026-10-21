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
from .samples import Unreadable, files_under, holds_data

EXP_ID_RE    = re.compile(r'^[A-Za-z0-9_\-]+$')


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


def column_rule(pipe: dict, column: str) -> dict:
    """What one sample-sheet column accepts; empty where nothing is declared."""
    return (pipe.get("column_rules") or {}).get(column, {})


def validate_samples(rows: list[dict], pipe: dict) -> list[str]:
    """Check a sample sheet, cell by cell, against what the pipeline accepts."""
    errors: list[str] = []
    columns = pipe["columns"]
    required = required_columns(pipe)
    # Groups of columns of which a row needs at least one — a schema's "anyOf".
    either = pipe.get("one_of_columns") or []
    paired = pipe.get("paired_columns") or []
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

        for group in paired:
            filled = [col for col in group if str(row.get(col, "")).strip()]
            if filled and len(filled) < len(group):
                named = " and ".join(f"'{col}'" for col in group)
                errors.append(f"{row_label} · {named} go together: fill all of them or none")

        for col in columns:
            value = str(row.get(col, "")).strip()
            if not value:
                continue
            rule = column_rule(pipe, col)
            if not rule and col == file_column:
                # Nothing declared for this pipeline: whether it exists is the
                # one thing that can be said without knowing what it takes.
                rule = {"path": "any"}
            errors.extend(f"{row_label} · '{col}': {e}" for e in _cell_errors(value, rule))

    counts = Counter(str(r.get("sample_id", "")).strip() for r in rows)
    for sid, n in counts.items():
        if sid and n > 1:
            errors.append(f"duplicate sample_id: {sid!r}")

    return errors


# Nextflow's glob, which file() expands into a list and nf-schema then refuses.
_GLOB_RE = re.compile(r"[*?\[{]")


def _cell_errors(value: str, rule: dict) -> list[str]:
    """One filled cell against its rule: the reasons it would be turned away.

    Stops at the first, since each check stands on the one before it — a path
    that does not exist has no contents to judge.
    """
    shown = value if len(value) <= 80 else "…" + value[-79:]
    expected = f" — expected {rule['accepts']}" if rule.get("accepts") else ""
    kind = rule.get("path")

    if kind and _GLOB_RE.search(value):
        return [f"{shown!r} is a pattern, which the pipeline does not expand{expected}"]
    if kind and "," in value and not os.path.exists(value):
        how = (" — or give the folder that holds them" if kind in ("dir", "any") else
               " — concatenate them into one file first")
        return [f"{shown!r} is a list of paths, and a row takes one{how}"]
    # The wrong kind of path is said before the pattern, which a folder fails
    # too — "is a folder" says what to do about it.
    if kind == "file" and os.path.isdir(value):
        return [f"{shown!r} is a folder{expected}"]
    if kind == "dir" and os.path.isfile(value):
        return [f"{shown!r} is not a folder{expected}"]
    if rule.get("pattern") and not re.search(rule["pattern"], value):
        return [f"{shown!r} is not accepted{expected}"]
    if not kind:
        return []
    if not os.path.exists(value):
        return [f"path not found — {shown!r}"]

    name = re.compile(rule["name"]) if rule.get("name") else None
    if os.path.isdir(value):
        return _folder_errors(value, shown, name, rule.get("nonempty"), expected)
    if name and not name.search(os.path.basename(value)):
        return [f"{shown!r} is not accepted{expected}"]
    if rule.get("nonempty"):
        try:
            if not holds_data(value):
                return [f"{shown!r} is empty"]
        except Unreadable as exc:
            return [f"{shown!r} {exc}"]
    return []


def _folder_errors(folder: str, shown: str, name, nonempty: bool,
                   expected: str) -> list[str]:
    """A folder is as good as the files a pipeline would gather from it."""
    found = False
    for path in files_under(folder, name):
        found = True
        if not nonempty:
            return []
        try:
            if holds_data(path):
                return []
        except Unreadable:
            # One bad chunk among good ones is the pipeline's to report; a
            # folder with nothing else in it is caught below.
            continue
    if not found:
        return [f"{shown!r} holds no file the pipeline would read{expected}"]
    return [f"{shown!r} holds only empty or unreadable files"]
