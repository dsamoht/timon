"""Run-configuration fields, declared by hand in ``config.PIPELINES``.

A pipeline's ``params`` list is a deliberate selection, not a transcription of
everything the workflow accepts: most Nextflow parameters are either supplied
by timon itself (``--input``, ``--outdir``), come from the environment (the
reference databases), or are tuning knobs that would only crowd the form. What
is listed here is what a user is expected to set for a run; anything left out
keeps the pipeline's own default.

This module only normalises those declarations and buckets them into the
sections the form renders — it never reaches the network, so a pipeline can be
linked, and its form rendered, on a machine with no connectivity.
"""

from __future__ import annotations

from typing import Any


def _normalise(p: dict) -> dict:
    """One declaration filled out to the shape the form and routes speak."""
    field = {
        "label": p["id"],           # the id *is* the --flag; a label is optional
        "type": "text",
        "description": "",
        "help_text": "",
        "required": False,
        "group": "",
        **p,
    }

    if field["type"] == "bool":
        field["default"] = bool(field.get("default"))
    else:
        field.setdefault("default", "")
    # An integer field and a float field are different runs: "any" is what
    # tells routes.py to cast with float() rather than int().
    if field["type"] == "number":
        field.setdefault("step", 1)
    if field["type"] == "select":
        field["enum"] = [str(v) for v in field.get("enum", [])]
    return field


def fields(pipe: dict) -> list[dict]:
    """Every parameter this pipeline puts in the form, in declaration order."""
    # A database listed under requires_db is passed from the environment (see
    # core.DB_FLAGS). Asking for it here as well would let the two disagree.
    supplied = set(pipe.get("requires_db") or [])
    return [_normalise(p) for p in pipe.get("params", []) if p["id"] not in supplied]


def param_sections(pipe: dict) -> list[dict]:
    """The parameters of a pipeline, bucketed into the sections the form renders.

    A section is a ``group`` shared by consecutive fields; its blurb, if it has
    one, comes from the pipeline's optional ``param_groups`` mapping. Booleans
    are kept apart from the rest: they render as a row of checkboxes under the
    group's fields rather than as grid cells.
    """
    blurbs = pipe.get("param_groups") or {}
    out: list[dict] = []
    index: dict[str, dict] = {}
    for p in fields(pipe):
        title = p.get("group") or ""
        section = index.get(title)
        if section is None:
            section = {"title": title, "description": blurbs.get(title, ""),
                       "fields": [], "flags": []}
            index[title] = section
            out.append(section)
        (section["flags"] if p["type"] == "bool" else section["fields"]).append(p)
    return out


def param_defaults(pipe: dict) -> dict[str, Any]:
    return {p["id"]: p.get("default") for p in fields(pipe)}
