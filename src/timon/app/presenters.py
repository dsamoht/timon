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

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..paths import REFERENCE_DATA, db_root
from . import model
from .config import DATABASE_BUNDLE, Config
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


def _container_label(profile: str, version: str) -> str:
    """"Docker version 27.3.1, build ce12230" → "docker 27.3.1".

    Every engine words its own version line differently and none of them is
    worth a tile's width, so only the number is kept — under the profile's
    name, which is what the run is actually launched with.
    """
    head = version.split(",")[0].split()
    number = head[-1] if head else ""
    if not any(char.isdigit() for char in number):
        return f"{profile} ready"
    return f"{profile} {number}"


def container_view(container: model.Container) -> dict:
    """The container-engine indicator, beside nextflow's and read the same way.

    Three states rather than two: an engine can be absent, or present and not
    running, and on a laptop the second is the commoner one — so it is said in
    those words instead of as a missing installation the user would go and
    repeat.
    """
    if not container.binary:
        # A profile with nothing local to find. Reported as the fact it is,
        # not as an approval: timon has not checked anything.
        return {
            "ok": True,
            "label": f"{container.profile} profile",
            "detail": f"nextflow provisions {container.profile} itself — "
                      "nothing for timon to look for on this machine",
        }
    if not container.found:
        return {
            "ok": False,
            "label": f"{container.profile} not found",
            "detail": f"{container.binary!r} is not on PATH — install it, or "
                      "set TIMON_PROFILE to an engine this machine has",
        }
    if container.daemon is False:
        return {
            "ok": False,
            "label": f"{container.profile} not running",
            "detail": f"{container.path} is installed but the {container.profile} "
                      "service is not answering — start it",
        }
    return {
        "ok": True,
        "label": _container_label(container.profile, container.version),
        "detail": container.path,
    }


# ── the run-configuration form ───────────────────────────────────────────────

def number_text(value) -> str:
    """A number as the form writes it: plain decimal, "." as the only separator.

    str() would write a small fraction as "1e-05", which the form itself
    refuses to accept back — a saved run would reopen with a field it calls
    wrong. Never localised either: "0,5" is not a value timon reads.
    """
    number = P.parse_number(value)
    if number is None:
        return ""
    if float(number) == int(number):
        return str(int(number))
    return format(Decimal(repr(float(number))), "f")


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
    live    = {p["id"] for p in experiment.active_fields()}
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

    for p in experiment.fields():
        p["active"] = p["id"] in live
        if p["type"] == "number":
            p["text"] = number_text(values.get(p["id"], p["default"]))
            p["default_text"] = number_text(p["default"])
        if p.get("options_from") and not p["options_known"]:
            # Offering the default alone looks like a choice already made;
            # it is only the one the pipeline would make before there is an
            # index to read the real ones from.
            p["options_note"] = "the rest are offered once the database is installed"
        elif p.get("options_from") and not p["enum"]:
            p["options_note"] = "the installed database has none to offer"
        section = section_for(p.get("group") or "")
        (section["flags"] if p["type"] == "bool" else section["fields"]).append(p)
        if p["active"] and (p.get("required") or P.required_trigger(p, values)
                            or P.is_customised(p, values)):
            section["open"] = True

    # A section with nothing left in it is a heading for a route this run does
    # not take, and the first one still standing is where the form starts.
    first = True
    for section in out:
        section["active"] = any(p["active"] for p in section["fields"] + section["flags"])
        if section["active"] and first:
            section["open"], first = True, False
    return out


# ── the databases ────────────────────────────────────────────────────────────
#
# Two questions meet in one card. Whether the bundle is installed is asked of
# the machine, once for every run — it is what the install button is frozen
# by. Whether *this* run has what it reads is asked of the experiment, and
# only adds a line when the answer is a database outside the bundle (GTDB-Tk,
# for a mag-ont run that reaches bin QA) or when the run is being held back.

def size_of(done: int, total: int) -> str:
    """How far along a download is, in the units a file manager would use."""
    if total:
        return f"{size_label(done)} of {size_label(total)}"
    # No Content-Length: there is no fraction to show, only a count going up.
    return size_label(done)


def download_view(state: dict | None) -> dict | None:
    """A download in progress, as the card's bar and line read it."""
    if state is None:
        return None
    percent = int(100 * state["done"] / state["total"]) if state["total"] else 0
    return {
        **state,
        "percent": percent,
        # A bar that cannot say how far along it is should not draw a
        # fraction; the page stripes it instead.
        "known": bool(state["total"]),
        "progress": size_of(state["done"], state["total"]),
    }


def database_view(key: str, present: bool, where, variant: str = "") -> dict:
    """One database: whether it is there, where timon looked, how to get it.

    Whether it is there is passed in, because the two lists ask it of
    different things — the machine for the bundle, the run for the rest — and
    one walk of the filesystem answers for a whole list.

    ``where`` is the path itself, because that is what the user has to act on
    when a copy they have is not being found.

    ``variant`` is the build the page currently has picked, which decides the
    size and the name shown: a row offering a choice should say what it would
    fetch if pressed, not what it would have fetched by default.
    """
    reference = REFERENCE_DATA[key]
    builds = model.downloads.variants(key)
    # A choice arrives on a request and can name anything at all, so one that
    # is not a declared build falls back to the default rather than drawing a
    # row about nothing. The refusal is then asked about the build the row is
    # actually showing, so what it says and what its button would do agree —
    # a request that really does ask to fetch an undeclared build is still
    # refused, by the model, where that rule lives.
    source = model.downloads.source(key, variant) or (builds[0] if builds else None)
    download = model.downloads.current(key)
    refusal = "" if present else model.downloads.refusal(
        key, source.variant if source else variant)
    # Where the chosen build would land, for a row that has one to choose: a
    # row offering the 8 GB index must not point at the path the 16 GB one
    # would take, or the user is told a download is going somewhere it is
    # not. Only while timon is looking where it installs — a variable pointing
    # elsewhere is the thing such a row exists to report, so it stays put.
    if not present and source is not None and reference.installed_here() \
            and str(where) == str(reference.locate()):
        where = source.destination()

    return {
        "key":         key,
        "label":       reference.label,
        "present":     present,
        "where":       display_path(where),
        "env":         reference.env,
        "size":        source.size if source else "",
        "description": source.description if source else "",
        # The builds to choose between, and which is chosen. Only ever more
        # than one where the publisher offers more than one, so a row with a
        # choice to make is the one that draws one — every other row is
        # unchanged by any of this.
        "variants":    [{"id": build.variant, "label": build.label,
                         "size": build.size, "note": build.note}
                        for build in builds if build.variant],
        "variant":     source.variant if source else "",
        # Whether the button can do anything about it now. A reason is only
        # worth showing for a database that is missing and not arriving.
        "can_install": not present and not refusal,
        "reason":      refusal if not (download and download.running) else "",
        "download":    download_view(download.snapshot() if download else None),
    }


def databases_view(experiment: model.Experiment,
                   chosen: dict[str, str] | None = None) -> dict:
    """The databases card: the bundle, and whatever else this run is missing.

    ``missing`` is the model's list, not a filter applied here: the line that
    says a run is waiting, the button that offers to fetch and the run that
    refuses to start are all the same answer.

    ``chosen`` is which build the page has picked for a database published in
    more than one. It is the page's, not timon's: nothing is remembered
    between requests, because a choice only matters at the moment install is
    pressed and the page is the thing holding it until then.
    """
    chosen = chosen or {}
    bundle_missing = model.downloads.bundle_missing()
    bundle = [database_view(key, key not in bundle_missing,
                            REFERENCE_DATA[key].locate(), chosen.get(key, ""))
              for key in DATABASE_BUNDLE]

    missing = experiment.missing_databases()
    paths = experiment.database_paths()
    # The bundle's own are already rows above, whichever run reads them.
    extra = [database_view(key, False, paths[key], chosen.get(key, ""))
             for key in missing if key not in DATABASE_BUNDLE]

    return {
        # What freezes the button: nothing in the bundle is left to fetch.
        "installed":   not bundle_missing,
        "bundle":      bundle,
        "extra":       extra,
        "missing":     missing,
        # The databases standing between this configuration and a run. Empty
        # for a pinned run, which is launched as it ran and not held back.
        "holding":     [] if experiment.pinned
                       else [REFERENCE_DATA[key].label for key in missing],
        "can_install": any(row["can_install"] for row in bundle),
        "root":        display_path(db_root()),
        # What tells the page to keep asking: a download only exists in this
        # process, so the page learns it has finished by looking again.
        "busy":        model.downloads.busy(),
    }


def params_view(experiment: model.Experiment) -> dict:
    """Context for _params.html, rendered into the page and on a switch."""
    return {
        "param_sections": param_sections(experiment),
        "param_values": experiment.params,
    }


# ── the page ─────────────────────────────────────────────────────────────────

def revision_label(revision: str) -> str:
    """A revision as a person reads it: a tag as it is, a commit shortened.

    Only today's pins are tags. A run reopened from before them was recorded
    at a full commit, and forty hex characters would push the name out of the
    status strip.
    """
    if len(revision) == 40 and all(c in "0123456789abcdef" for c in revision):
        return revision[:7]
    return revision


def run_view(experiment: model.Experiment, engine: model.Engine,
             container: model.Container) -> dict:
    """What the status strip, the run button and the restored form state read."""
    in_flight = experiment.in_flight()
    return {
        "id": experiment.exp_id,
        # What pressing run would do to a run this identifier already names.
        # Part of every reply that can change the identifier, because that is
        # what decides whether the offer is there to make.
        "restart": restart_view(experiment),
        "pipeline_id": experiment.pipeline_id,
        # Beside the name in the status strip: which release a run would use.
        "revision": revision_label(experiment.revision),
        "n_samples": experiment.n_samples,
        # Whether the form has been saved at all, which is what locks it —
        # not whether the run could start.
        "configured": bool(experiment.exp_id),
        # The same for the sheet: a written sheet is a saved one. Not the
        # same as having rows — a scan, and a reopened run whose reads have
        # moved, both leave rows on the page that nothing has accepted yet.
        "sheet_saved": bool(experiment.samplesheet),
        # A reopened run, held exactly as it ran: the page locks the workflow,
        # the form and the sheet, and offers only the deliberate way out.
        "pinned": experiment.pinned,
        "ready": experiment.is_ready(),
        # What is going in this workspace right now, whoever started it. Part
        # of the first paint and not only of the socket, so that a page opened
        # onto a run already in progress is locked before it has connected —
        # the moment in which it would otherwise offer to start it again.
        "live": run_state_view(experiment, engine, container,
                               in_flight[0] if in_flight else None, model.RUN.entry),
        # Four things have to hold before a run can start, and they are
        # asked here so that the button and the model agree on one answer:
        # the configuration, nextflow, something to containerise its tasks
        # with, and nothing already running. timon runs one workflow at a
        # time in a workspace, and model.WorkflowRun refuses a second one
        # whether or not it was this timon that started the first.
        "can_start": (experiment.is_ready() and engine.found
                      and container.ready and not in_flight),
        # The quick test asks nothing of the configuration — only of the
        # pipeline and of the two engines being there — so it is offered while
        # a form that is not finished, or not started, still refuses to run.
        "can_test": (experiment.is_testable() and engine.found
                     and container.ready and not in_flight),
    }


def release_url(version: str) -> str:
    """Where the version in the brand points.

    The version is the git tag (see pyproject's hatch-vcs block), so a released
    build names a page that exists and is linked straight to it. A build made
    between tags carries a ``.dev`` segment or a ``+`` local part and has no
    release of its own, so the list is the honest answer — a link to
    ``/releases/tag/v0.1.1.dev2+g3fc222c`` would only be a 404.
    """
    released = version and ".dev" not in version and "+" not in version
    if not released:
        return f"{Config.REPO_URL}/releases"
    return f"{Config.REPO_URL}/releases/tag/v{version}"


def index_view(experiment: model.Experiment, engine: model.Engine,
               container: model.Container, version: str,
               release_year: str) -> dict:
    """Everything index.html renders, and nothing it has to work out itself."""
    pipe = experiment.pipeline
    return {
        "run": run_view(experiment, engine, container),
        "engine": engine_view(engine),
        # Beside it, because the two are one question — whether this machine
        # can run a pipeline at all — and a run stopped by either of them
        # should be explained by the strip rather than by the log.
        "container": container_view(container),
        # In the first paint as well as on demand: a missing database is the
        # reason a fresh install cannot run anything, and it should be on the
        # page before the user has pressed anything.
        "databases": databases_view(experiment),
        # Only the ones that can be picked: which those are is the model's
        # answer, the same one set_pipeline refuses a switch with.
        "pipelines": model.selectable_pipelines(),
        "columns": pipe["columns"],
        "path_columns": model.path_columns(pipe),
        # The rows themselves; run["n_samples"] is how many of them there are.
        "samples": experiment.samples,
        "workspace": display_path(model.workspace_root()),
        # Where the folder picker behind "scan folder" opens: the place reads
        # are expected to be, before the user has shown otherwise.
        "input_folder": experiment.input_folder,
        "version": version,
        # The version says what is running; the link says what that is.
        "release_url": release_url(version),
        "release_year": release_year,
        **params_view(experiment),
    }


# ── past runs ────────────────────────────────────────────────────────────────
#
# The model remembers a run as the folder it wrote plus a note in it; how
# long ago that was, what to call the way it ended and which mark to put
# beside it are decided here.

# One entry per status in model.history, plus the two the page reads off it:
# a word for the row, and a tone the stylesheet colours.
RUN_STATUS = {
    model.history.FINISHED:    {"label": "finished",    "glyph": "✓", "tone": "ok"},
    model.history.FAILED:      {"label": "failed",      "glyph": "✗", "tone": "bad"},
    model.history.CANCELLED:   {"label": "stopped",     "glyph": "■", "tone": "warn"},
    model.history.RUNNING:     {"label": "running",     "glyph": "⟳", "tone": "busy"},
    model.history.INTERRUPTED: {"label": "interrupted", "glyph": "!", "tone": "warn"},
}

MINUTE, HOUR, DAY = 60, 3600, 86400


def since(moment) -> str:
    """How long ago something happened, as a person would say it.

    Vague on purpose, and only for as long as vague is useful: past a week
    the date itself is what tells one run from another.
    """
    if not moment:
        return ""
    seconds = datetime.now().timestamp() - moment
    if seconds < 0 or seconds >= 7 * DAY:
        return when(moment)
    if seconds < MINUTE:
        return "just now"
    if seconds < HOUR:
        return f"{int(seconds // MINUTE)} min ago"
    if seconds < DAY:
        return f"{int(seconds // HOUR)} h ago"
    days = int(seconds // DAY)
    return "yesterday" if days == 1 else f"{days} days ago"


def duration_label(seconds: float) -> str:
    """How long a run took, in nextflow's own units. Blank while it runs."""
    if not seconds:
        return ""
    if seconds < MINUTE:
        return f"{int(seconds)}s"
    if seconds < HOUR:
        return f"{int(seconds // MINUTE)}m {int(seconds % MINUTE)}s"
    return f"{int(seconds // HOUR)}h {int((seconds % HOUR) // MINUTE)}m"


def run_row(record, current_id: str = "") -> dict:
    """One past run as a row of the list: what it was, and how it went."""
    return {
        "id":          record.exp_id,
        "pipeline":    record.pipeline_id,
        "status":      RUN_STATUS.get(record.status, RUN_STATUS[model.history.RUNNING]),
        "when":        when(record.started_at),
        "since":       since(record.started_at),
        "duration":    duration_label(record.duration),
        "n_samples":   len(record.samples),
        # Where the results browser opens it: a run's folder is named after
        # it, and that name is the path relative to the output root.
        "rel":         record.exp_id,
        "resumable":   model.can_resume(record.launch_dir, record.session),
        # Still going, which is a row the user can watch and stop rather than
        # reopen. A record says so only for as long as the process behind it
        # is actually there — see model.history._settled.
        "running":     record.status == model.history.RUNNING,
        "current":     bool(current_id) and record.exp_id == current_id,
    }


def runs_view(records: list, current_id: str = "", elsewhere=()) -> dict:
    """The list of past runs, newest first, as the runs view renders it.

    ``elsewhere`` is the other half of the list and belongs to no workspace
    in particular: the runs going right now that were started somewhere
    else on this machine. They have no record here to be listed from — a
    run is remembered in the folder it writes, and that folder is in the
    workspace it was launched in — so they are listed from the pointers
    they left instead, which is the only place they exist from here.
    """
    return {"runs": [run_row(record, current_id) for record in records],
            "elsewhere": [live_view(entry, False) for entry in elsewhere]}


# ── a run that is going ──────────────────────────────────────────────────────
#
# A run outlives the timon that started it, so "what is running" is a
# question about the machine rather than about this process, and the page
# has to be able to say which of the two it is looking at: its own run, or
# one it has found and is watching.

def live_view(entry, mine: bool) -> dict:
    """A run in flight, as the console header and the runs list read it."""
    return {
        "id":         entry.exp_id,
        "pid":        entry.pid,
        "test":       entry.is_test,
        # Whether this timon started it. The one that did is the only one
        # that can say how it ended with an exit code, and it is worth the
        # page saying plainly which situation the user is in.
        "mine":       mine,
        "since":      since(entry.started_at),
        "when":       when(entry.started_at),
        "launch_dir": display_path(entry.launch_dir),
        "workspace":  display_path(entry.output_folder),
        "command":    " ".join(entry.command),
    }


def run_state_view(experiment: model.Experiment, engine: model.Engine,
                   container: model.Container, entry=None, mine_entry=None,
                   record=None) -> dict:
    """What is running, and — when one has just stopped — how it ended.

    The whole of what the page is told about a run: in the first paint, and
    in every message the socket sends it afterwards. One shape for both, so
    that a page which has just loaded, a page which has just reconnected and
    a page which has been open all along cannot end up in different states.

    Whether a run may be started is part of it because the end of a run is
    the moment that changes: the button that was locked while nextflow was
    going has to be told what it is now, and it is told the model's answer
    rather than left to assume the one it had before.
    """
    mine = bool(entry is not None and mine_entry is not None
                and mine_entry.out_dir == entry.out_dir)
    ended = None
    if record is not None and record.ended:
        ended = {
            "id":     record.exp_id,
            "status": RUN_STATUS.get(record.status, RUN_STATUS[model.history.RUNNING]),
            "code":   record.exit_code,
        }
    return {
        "running":   entry is not None,
        "run":       live_view(entry, mine) if entry is not None else None,
        "ended":     ended,
        "can_start": (experiment.is_ready() and engine.found
                      and container.ready and entry is None),
        "can_test":  (experiment.is_testable() and engine.found
                      and container.ready and entry is None),
    }


def replay_view(record, text: str) -> dict:
    """A run that is over, and the end of what it said, for the console.

    What a reopened run shows before it is run again: its own last words,
    so the error on screen is the one the run gave rather than one the page
    made up.
    """
    return {
        "id":     record.exp_id,
        "status": RUN_STATUS.get(record.status, RUN_STATUS[model.history.RUNNING]),
        "since":  since(record.ended_at or record.started_at),
        "code":   record.exit_code,
        "data":   text,
    }


def restart_view(experiment: model.Experiment) -> dict:
    """What pressing run would do to a run this identifier already names.

    Three states, and the page says a different thing for each: no such run,
    one that can be continued, and one whose cache is gone — where running
    again is an honest start from the beginning over the same folder.
    """
    previous = experiment.previous()
    if previous is None:
        return {"previous": False, "can_resume": False, "on": experiment.resume}
    return {
        "previous":   True,
        "id":         previous.exp_id,
        "status":     RUN_STATUS.get(previous.status, RUN_STATUS[model.history.RUNNING]),
        "since":      since(previous.started_at),
        "when":       when(previous.started_at),
        "can_resume": experiment.resumable(),
        "on":         experiment.resume,
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


# ── the results browser ──────────────────────────────────────────────────────
#
# The model says what is in the output folder and what kind of thing each
# file is; the wording, the glyph, the shortened path and the human-readable
# size and date are decided here, so the page's JS only has to print what it
# is given.

# One mark per kind, in the same vocabulary the file browser already speaks.
KIND_GLYPHS = {
    "image": "▣",
    "html":  "◈",
    "pdf":   "▤",
    "table": "▦",
    "text":  "≡",
    "other": "·",
}


def size_label(size) -> str:
    """A file size as a person reads it. Blank when there is nothing to say."""
    if size is None:
        return ""
    value, units = float(size), ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.0f} {unit}" if unit == "B" or value >= 10 else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def when(mtime) -> str:
    """When a file was written, to the minute — the resolution a run has."""
    if not mtime:
        return ""
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def results_view(listing: dict, current_id: str = "") -> dict:
    """One folder of outputs as the results pane renders it.

    ``current`` marks the folder this session's run is writing to, which is
    the one a user coming here straight from the console is looking for. It
    is only ever a mark on a row: the folder is opened, listed and read like
    any other, so results from a previous session are not second-class.
    """
    entries = [{
        **entry,
        "glyph":      "▸" if entry["dir"] else KIND_GLYPHS.get(entry["kind"], "·"),
        "size_label": size_label(entry["size"]),
        "when":       when(entry["mtime"]),
        "current":    bool(current_id) and listing["at_root"]
                      and entry["dir"] and entry["name"] == current_id,
    } for entry in listing["entries"]]

    return {
        **listing,
        "entries": entries,
        "display": display_path(listing["path"]),
        "root_display": display_path(listing["root"]),
    }


def preview_view(preview: dict) -> dict:
    """One file as the viewer shows it, with the facts under its title."""
    return {
        **preview,
        "size_label": size_label(preview["size"]),
        "when": when(preview["mtime"]),
    }
