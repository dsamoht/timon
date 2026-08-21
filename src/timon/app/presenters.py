"""Model facts, put into the shape a page renders.

Everything the templates and the JSON responses read is built here: labels,
the shortened paths, the section a field falls in and whether it starts
folded. None of it is a decision about the run — those are the model's, and
this module only ever reads them — but none of it belongs in the model
either, because a different front end would want the same facts worded
differently.

The templates are written against what these functions return, so a template
never reaches into the model: it cannot ask whether a run is ready, only be
told.
"""

from __future__ import annotations

from pathlib import Path

from . import model
from .config import PIPELINES
from .model import params as P


# ── paths ────────────────────────────────────────────────────────────────────

def display_path(path) -> str:
    """Absolute path with the home directory shortened to ~."""
    path = Path(path)
    home = Path.home()
    if path == home or home in path.parents:
        return str(Path("~") / path.relative_to(home))
    return str(path)


# ── the engine indicator ─────────────────────────────────────────────────────

def engine_view(engine: model.Engine) -> dict:
    """The nextflow status indicator: a light, a word and what it means.

    Missing nextflow is a normal state — it is not a python dependency — so
    this says what to do about it rather than reporting a failure.
    """
    if not engine.found:
        return {
            "ok": False,
            "label": "nextflow not found",
            "detail": f"{engine.binary!r} is not on PATH — "
                      "install it, or set TIMON_NEXTFLOW to its location",
        }
    return {
        "ok": True,
        "label": engine.version.replace("nextflow version ", "nextflow ") or "nextflow ready",
        "detail": engine.path,
    }


# ── the run-configuration form ───────────────────────────────────────────────

def param_sections(experiment: model.Experiment) -> list[dict]:
    """The parameters of the current pipeline, bucketed into form sections.

    A section is a ``group`` shared by consecutive fields; its blurb, if it has
    one, comes from the pipeline's optional ``param_groups`` mapping. Booleans
    are kept apart from the rest: they render as a row of checkboxes under the
    group's fields rather than as grid cells.

    ``open`` is a starting state, not a filter: a folded section still renders
    its fields, so every parameter is submitted whether or not it was unfolded.
    A section starts open when it is the first one, when something in it has to
    be filled in — always, or because of a choice made elsewhere in the form —
    or when this run already carries a value that is not the pipeline's
    default: the cases where folding it would hide a decision. Only a
    parameter the run still uses can open a section, and neither can it be
    what makes one the first: a run that skips a whole route should not be
    greeted by the route's parameters.

    ``active`` is the filter, and it is a starting state too: the page
    re-evaluates it as the form is filled in (see model.params.inactive_ids),
    so this is what the first paint shows rather than the last word.
    """
    pipe    = experiment.pipeline
    values  = experiment.params
    blurbs  = pipe.get("param_groups") or {}
    active_params, active_dbs = experiment.active_fields()
    live    = {p["id"] for p in active_params + active_dbs}
    out: list[dict] = []
    index: dict[str, dict] = {}

    def section_for(title: str) -> dict:
        section = index.get(title)
        if section is None:
            section = {"title": title, "description": blurbs.get(title, ""),
                       "fields": [], "flags": [], "open": False}
            index[title] = section
            out.append(section)
        return section

    for p in P.fields(pipe):
        p["active"] = p["id"] in live
        section = section_for(p.get("group") or "")
        (section["flags"] if p["type"] == "bool" else section["fields"]).append(p)
        if p["active"] and (p.get("required") or P.required_trigger(p, values)
                            or P.is_customised(p, values)):
            section["open"] = True

    dbs = P.db_fields(pipe, experiment.databases)
    for d in dbs:
        d["active"] = d["id"] in live
    if dbs:
        section = section_for(dbs[0]["group"])
        # First in their group: a run needs the database before it needs
        # anything tuned about the steps that read it.
        section["fields"] = dbs + section["fields"]
        # Folded once it has a path — the environment already answered. Open
        # while one the run still needs is empty, which is the whole reason to
        # show it: required outright, or excused only by a step this
        # configuration does not actually skip.
        if any(d["active"] and not d["default"] for d in dbs):
            section["open"] = True

    # A section with nothing left in it is a heading for a route this run does
    # not take, and the first one still standing is where the form starts.
    first = True
    for section in out:
        section["active"] = any(p["active"] for p in section["fields"] + section["flags"])
        if section["active"] and first:
            section["open"], first = True, False
    return out


def params_view(experiment: model.Experiment) -> dict:
    """Context for _params.html, rendered into the page and on a switch."""
    return {
        "param_sections": param_sections(experiment),
        "param_values": experiment.params,
    }


# ── the page ─────────────────────────────────────────────────────────────────

def run_view(experiment: model.Experiment, engine: model.Engine) -> dict:
    """What the status strip, the run button and the restored form state read."""
    return {
        "id": experiment.exp_id,
        "pipeline_id": experiment.pipeline_id,
        "n_samples": experiment.n_samples,
        # Whether the form has been saved at all, which is what locks it —
        # not whether the run could start.
        "configured": bool(experiment.exp_id),
        "ready": experiment.is_ready(),
        # An engine that is not there is the other half of "can this start":
        # asked here so the button and the model agree on one answer.
        "can_start": experiment.is_ready() and engine.found,
    }


def index_view(experiment: model.Experiment, engine: model.Engine,
               version: str, release_year: str) -> dict:
    """Everything index.html renders, and nothing it has to work out itself."""
    pipe = experiment.pipeline
    return {
        "run": run_view(experiment, engine),
        "engine": engine_view(engine),
        "pipelines": PIPELINES,
        "columns": pipe["columns"],
        "path_columns": model.path_columns(pipe),
        # The rows themselves; run["n_samples"] is how many of them there are.
        "samples": experiment.samples,
        "workspace": display_path(model.workspace_root()),
        "version": version,
        "release_year": release_year,
        **params_view(experiment),
    }


# ── the file browser ─────────────────────────────────────────────────────────

def listing_view(listing: dict) -> dict:
    """One directory as the browser panel shows it.

    The paths stay exactly what the server resolved — they are sent straight
    back when something is picked — and only what is read on screen is
    shortened.
    """
    home = str(Path.home())
    crumbs = [{**c, "name": "~" if c["path"] == home and not c["root"] else c["name"]}
              for c in listing["crumbs"]]
    return {
        **listing,
        "crumbs": crumbs,
        "display": display_path(listing["path"]),
        "root_display": display_path(listing["root"]),
    }


def permission_view(path) -> dict:
    """The refusal the panel puts to the user as a question."""
    root = model.workspace_root()
    return {
        "ok": False,
        "needs_permission": True,
        "path": str(path),
        "display": display_path(path),
        "root": str(root),
        "root_display": display_path(root),
        "error": "outside the workspace timon was launched in",
    }
