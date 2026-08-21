"""Run-configuration fields, declared by hand in ``config.PIPELINES``.

A pipeline's ``params`` list is a deliberate selection, not a transcription of
everything the workflow accepts: most Nextflow parameters are either supplied
by timon itself (``--input``, ``--outdir``) or are tuning knobs that would only
crowd the form. What is listed here is what a user is expected to set for a
run; anything left out keeps the pipeline's own default.

The databases under ``requires_db`` are the exception: they are not declared
per pipeline but described once in ``config.ENV_DATABASES``, because an
environment variable names the same database for every pipeline that reads it.

This module normalises those declarations, works out which of them the run as
configured still uses, and casts submitted values to the declared type. It
answers *what a parameter is* — never how a field is drawn or which section it
falls in; that is the view's question, and it lives in ``presenters.py``. It
also never reaches the network, so a pipeline can be linked, and its form
rendered, on a machine with no connectivity.
"""

from __future__ import annotations

from typing import Any

from ..config import DB_GROUP, ENV_DATABASES


def _normalise(p: dict) -> dict:
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
    if field["type"] == "select":
        field["enum"] = [str(v) for v in field.get("enum", [])]
    return field


def fields(pipe: dict) -> list[dict]:
    """Every parameter this pipeline puts in the form, in declaration order."""
    # A database listed under requires_db is passed from the environment (see
    # nextflow.DB_FLAGS). Asking for it here as well would let the two disagree.
    supplied = set(pipe.get("requires_db") or [])
    return [_normalise(p) for p in pipe.get("params", []) if p["id"] not in supplied]


def db_fields(pipe: dict, db_values: dict | None = None) -> list[dict]:
    """The pipeline's ``requires_db`` databases, as fields of the form.

    Their value is held on the experiment rather than among the parameters
    (nextflow.DB_FLAGS turns it into the flag), so it is passed in here as the
    field's default: whatever the environment set at launch, or the path a
    previous save put there.
    """
    values = db_values or {}
    optional_when = pipe.get("db_optional_when", {})
    out = []
    for key in pipe.get("requires_db", []):
        meta = dict(ENV_DATABASES.get(key, {"label": key, "env": key.upper()}))
        env = meta.pop("env")
        out.append(_normalise({
            "id": key,
            "type": "text",
            "group": pipe.get("db_group", DB_GROUP),
            "default": values.get(key, ""),
            # Required whenever it is asked for at all: a database only some
            # steps read leaves the form entirely once those steps are skipped,
            # so a field still standing is one the run is going to read.
            "required": True,
            # ``db_optional_when`` says which flags excuse it; spelled as an
            # active_when so one evaluator settles it, and so the page can drop
            # the field the moment the box is ticked.
            "active_when": {flag: [False] for flag in optional_when.get(key, [])},
            "placeholder": f"path, or launch with {env}=…",
            **meta,
        }))
    return out


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
    ``requires_db`` database is in the same position, and db_fields() gives it
    the equivalent condition.
    """
    conditions = {p["id"]: p["active_when"]
                  for p in fields(pipe) + db_fields(pipe) if p.get("active_when")}
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
        try:
            return float(current) != float(default)
        except (TypeError, ValueError):
            return True
    return str(current) != str(default)


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
        try:
            return cast(float(raw))
        except (TypeError, ValueError):
            return p.get("default", 0)
    return raw if raw is not None else ""


def param_defaults(pipe: dict) -> dict[str, Any]:
    return {p["id"]: p.get("default") for p in fields(pipe)}
