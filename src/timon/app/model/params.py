"""Run-configuration fields, declared by hand in ``config.PIPELINES``.

A pipeline's ``params`` list is a deliberate selection, not a transcription of
everything the workflow accepts: most Nextflow parameters are either supplied
by timon itself (``--input``, ``--outdir``) or are tuning knobs that would only
crowd the form. What is listed here is what a user is expected to set for a
run; anything left out keeps the pipeline's own default.

The databases a pipeline reads are not here at all: timon finds them
(``timon.paths.REFERENCE_DATA``), so there is nothing to put in a form. They
still come into one question this module answers, which is whether a run
reaches the step that reads them.

A select may declare ``options_from`` instead of an ``enum``: its options
are what an installed database was built with (``timon.paths.DATABASE_OPTIONS``).
They are read off the disk by the caller and handed in, so this module still
only normalises.

This module normalises those declarations, works out which of them the run as
configured still uses, and casts submitted values to the declared type. It
answers *what a parameter is* — never how a field is drawn or which section it
falls in; that is the view's question, and it lives in ``presenters.py``. It
also never reaches the network, so a pipeline can be linked, and its form
rendered, on a machine with no connectivity.
"""

from __future__ import annotations

import math
import re
from typing import Any


def _normalise(p: dict, options: dict[str, list[str] | None] | None = None) -> dict:
    """One declaration filled out to the shape the rest of the app speaks."""
    field = {
        "label": p["id"],           # the id *is* the --flag; a label is optional
        "type": "text",
        "description": "",
        "help_text": "",
        "required": False,
        "group": "",
        # "dir" | "file" | "any" for a value that names something on disk;
        # empty for a field the browse button makes no sense on.
        "path": "",
        **p,
    }

    if field["type"] == "bool":
        field["default"] = bool(field.get("default"))
    else:
        field.setdefault("default", "")
    # An integer field and a float field are different runs: "any" is what
    # tells coerce() to cast with float() rather than int().
    if field["type"] == "number":
        field.setdefault("step", 1)
        # Every parameter in the form is a count, a length, a threshold or a
        # fraction, and a negative one is never a run anybody meant. A
        # declaration that forgot its floor gets this one rather than none.
        field.setdefault("min", 0)
    if field["type"] == "select":
        if field.get("options_from"):
            _read_options(field, (options or {}).get(field["options_from"]))
        field["enum"] = [str(v) for v in field.get("enum", [])]
    return field


def _read_options(field: dict, found: list[str] | None) -> None:
    """Fill a select from what its database turned out to hold.

    ``found`` is None while the database cannot be looked into — not yet
    installed, say — and then the declared default is the one option: the
    configuration can still be saved, and the run waits for the install
    anyway. An index that was looked into offers only what is in it, so the
    default moves to the nearest length there when the pipeline's own is
    not; and one holding none offers nothing, which validation refuses.
    """
    field["options_known"] = found is not None
    if found is None:
        field["enum"] = [field["default"]]
        return
    field["enum"] = found
    if found and str(field["default"]) not in found:
        target = parse_number(field["default"]) or 0
        field["default"] = min(found, key=lambda v: (abs(float(v) - target), -float(v)))


def fields(pipe: dict, options: dict[str, list[str] | None] | None = None) -> list[dict]:
    """Every parameter this pipeline puts in the form, in declaration order.

    ``options`` is what the databases on this machine hold, keyed as
    ``options_from`` names it (``Experiment.fields`` reads them). Left out,
    a select filled from a database offers its declared default alone —
    enough for the questions that do not depend on what is installed.
    """
    # A database is found by timon (see "reference_data"), never typed in.
    # Asking for it here as well would let the two disagree.
    supplied = set(pipe.get("reference_data") or [])
    return [_normalise(p, options)
            for p in pipe.get("params", []) if p["id"] not in supplied]


def database_conditions(pipe: dict) -> dict[str, dict]:
    """When each database the pipeline reads is read, as ``active_when``.

    ``db_optional_when`` names the flags that excuse one; spelled as an
    active_when so the one evaluator below settles databases and parameters
    alike, chaining included.
    """
    return {key: {flag: [False] for flag in flags}
            for key, flags in (pipe.get("db_optional_when") or {}).items()}


def required_trigger(p: dict, values: dict) -> tuple[str, Any] | None:
    """The value that makes ``p`` required right now, if one does.

    A parameter can be needed only for some other choice — the antiSMASH
    databases only once the screening mode assembles. ``required_when`` maps
    such a parameter to ``{other id: [values that need it]}``; any one of them
    matching is enough. Returns the (id, value) pair that triggered, so the
    error can say which choice is asking for it.
    """
    for key, wanted in (p.get("required_when") or {}).items():
        if key in values and values[key] in wanted:
            return key, values[key]
    return None


def _matches(value: Any, wanted: list) -> bool:
    """Whether a parameter's current value is one this condition accepts.

    Compared as strings as well as by identity: a select comes back from the
    form as "both" while a number comes back as "80", and a condition should
    be able to name either the way config.py writes it.
    """
    return any(value == w or str(value) == str(w) for w in wanted)


def _current_values(pipe: dict, values: dict | None = None) -> dict:
    """What every parameter holds right now — a saved value, or the default.

    The conditions have to be answerable before anything is saved, which is
    what the freshly rendered form is: the pipeline's own defaults.
    """
    resolved = param_defaults(pipe)
    resolved.update(values or {})
    return resolved


def inactive_ids(pipe: dict, values: dict | None = None) -> set[str]:
    """The parameters this configuration has taken out of the run.

    Half of a form is usually about steps a given run never reaches: nothing
    under `skip QC` is read once QC is skipped, and the assembly and BGC
    parameters belong to routes the screening mode may not take. Such a
    parameter declares ``active_when`` — ``{other id: [values that keep it]}``,
    every condition of which has to hold — and drops out of the form, out of
    validation, and off the command line while it does not.

    A parameter can hang off one that has itself dropped out (`skip Nanoplot`
    under `skip QC`), so this is settled rather than evaluated once. A
    database the pipeline reads is in the same position, and
    database_conditions() gives it the equivalent condition.
    """
    conditions = {p["id"]: p["active_when"]
                  for p in fields(pipe) if p.get("active_when")}
    conditions.update(database_conditions(pipe))
    resolved = _current_values(pipe, values)
    out: set[str] = set()
    while True:
        dropped = {pid for pid, cond in conditions.items() if pid not in out
                   and any(key in out or not _matches(resolved.get(key), wanted)
                           for key, wanted in cond.items())}
        if not dropped:
            return out
        out |= dropped


def is_customised(p: dict, values: dict) -> bool:
    """Whether a saved value differs from what the pipeline would do anyway."""
    if p["id"] not in values:
        return False
    current, default = values[p["id"]], p.get("default")
    if p["type"] == "number":
        # A number the pipeline leaves unset is customised by being given a
        # value, and by nothing else.
        blank = [v is None or str(v).strip() == "" for v in (current, default)]
        if any(blank):
            return blank[0] != blank[1]
        try:
            return float(current) != float(default)
        except (TypeError, ValueError):
            return True
    return str(current) != str(default)


# Plain decimal notation and nothing else: ASCII digits on both sides of a "."
# that is the only separator — never ",", which reads as a thousands mark or a
# decimal depending on who typed it. float() is far more generous than a
# form should be: it reads "nan", "inf", "1e400" (inf again), "1_000" and
# digits from any script, and a NaN compares false against both bounds, so it
# would pass a range check it is nowhere near.
_DECIMAL = re.compile(r"-?\d+(?:\.\d+)?", re.ASCII)
# Longer than any bound a parameter declares could need; past it the string is
# not a value someone typed.
_MAX_DIGITS = 20


def parse_number(raw: Any) -> float | None:
    """A submitted number as a finite float, or None if it is not one.

    The one reading of a number both validation and coerce() use, so what is
    refused and what reaches the command line cannot disagree.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if math.isfinite(raw) else None
    text = "" if raw is None else str(raw).strip()
    if len(text) > _MAX_DIGITS or not _DECIMAL.fullmatch(text):
        return None
    value = float(text)
    return value if math.isfinite(value) else None


def coerce(p: dict, raw: Any) -> Any:
    """One submitted value as the declared type, whatever spelling arrived.

    The caller hands over what the transport gave it — a string from a form
    field, a bool from a checkbox — and what comes back is what belongs on the
    command line. A number that cannot be read falls back to the declared
    default rather than to zero: validation has already refused the save, and
    an unreadable value should not quietly become a different run.
    """
    if p["type"] == "bool":
        return bool(raw)
    if p["type"] == "number":
        # A parameter declared with step "any" is a float: rounding it to an
        # int would silently change the run.
        cast = int if p.get("step") == 1 else float
        value = parse_number(raw)
        return p.get("default", 0) if value is None else cast(value)
    return raw if raw is not None else ""


def param_defaults(pipe: dict) -> dict[str, Any]:
    return {p["id"]: p.get("default") for p in fields(pipe)}
