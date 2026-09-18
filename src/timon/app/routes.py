"""HTTP surface: read the request, ask the model, render the answer.

Every route here is the same three steps. Nothing in this file decides
anything about a run — it translates form encoding into plain values, hands
them to the model, and passes what comes back to a presenter. The rules it
would otherwise be tempting to inline (which parameters count, what makes a
sample sheet valid, when a run may start) all live in ``model/``, so the page
and any other caller get the same answers.
"""

import re

from flask import (current_app as app, jsonify, render_template, request,
                   send_file)

from . import model, presenters
from .. import __release_year__, __version__
from .model import params as P


def _submitted(fields: list[dict]) -> dict:
    """The declared fields as this form holds them, in plain values.

    An unticked checkbox sends nothing at all and a ticked one sends "on";
    that is HTML's business, and undoing it here is the whole of what the
    model has to be spared. Taken from the form rather than from the stored
    configuration: it is the form the user is asking to accept, and which
    parameters are part of the run follows from the boxes ticked in it.
    """
    return {p["id"]: (request.form.get(p["id"]) == "on") if p["type"] == "bool"
                     else request.form.get(p["id"], "").strip()
            for p in fields}


def _run_view(experiment) -> dict:
    """The run view, with what this machine says about both engines.

    Asked here rather than remembered: nextflow and the container engine are
    each re-checked per request, so installing one, or starting one, shows up
    on the next thing the page does.
    """
    return presenters.run_view(experiment, model.engine(),
                               model.container(experiment.profile))


def _saved(errors: list[str]):
    """One shape for every save: the reasons it was refused, or the new state.

    The databases go back with it because a save is when the answer can have
    changed: ticking a step off can take the last missing database out of the
    run, and the line saying the run is waiting has to go with it.
    """
    if errors:
        return jsonify({"ok": False, "errors": errors, "error": errors[0]}), 400
    return jsonify({"ok": True,
                    **_run_view(model.EXPERIMENT),
                    "databases": presenters.databases_view(model.EXPERIMENT)})


def _form_reply(experiment) -> dict:
    """What a page has to be given to rebuild the form for a pipeline.

    The fields are rendered here rather than assembled in JS: the page and this
    response would otherwise be two implementations of the same form.
    """
    pipe = experiment.pipeline
    return {
        "pipeline_id": experiment.pipeline_id,
        "columns": pipe["columns"],
        "path_columns": model.path_columns(pipe),
        "params_html": render_template("_params.html",
                                       **presenters.params_view(experiment)),
    }


# ── page ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template("index.html",
                           **presenters.index_view(model.EXPERIMENT, model.engine(),
                                                   model.container(model.EXPERIMENT.profile),
                                                   __version__, __release_year__))


@app.route("/set_pipeline", methods=["POST"])
def set_pipeline():
    experiment = model.EXPERIMENT
    if not experiment.set_pipeline(request.form.get("pipeline_select")):
        return jsonify({"ok": False, "error": model.PINNED if experiment.pinned
                                              else "Unknown pipeline"}), 400
    # The run view goes back with the form because the quick test button
    # belongs to the pipeline, not to the configuration: switching to one that
    # ships a test profile has to reveal it without a reload. The databases go
    # for the same reason — which ones are read is the pipeline's answer, so a
    # switch is one of the two moments the missing-database notice changes.
    return jsonify({"ok": True, **_form_reply(experiment),
                    **_run_view(experiment),
                    "databases": presenters.databases_view(experiment)})


@app.route("/get_run_info_base", methods=["POST"])
def get_run_info_base():
    experiment = model.EXPERIMENT
    # Everything declared is read, active or not: which of them the run keeps
    # is the model's to settle, and it needs the hidden ones to settle it.
    declared = experiment.fields()
    # The continue box is always in the form, whether or not the page is
    # showing it — an identifier that turns out to name a past run must not
    # be left with whatever the last form happened to say about a different
    # one. Whether there is anything to continue is the model's answer.
    errors = experiment.apply_configuration(
        request.form.get("exp-id", "").strip(), _submitted(declared),
        resume=request.form.get("resume") == "on")
    return _saved(errors)


@app.route("/update_samples", methods=["POST"])
def update_samples():
    columns = model.EXPERIMENT.pipeline["columns"]
    values = {col: request.form.getlist(col) for col in columns}
    # A short column is a row the form did not finish sending; the rows that
    # are whole are what was meant.
    n = min((len(v) for v in values.values()), default=0)
    rows = [{col: values[col][i] for col in columns} for i in range(n)]

    errors = model.EXPERIMENT.set_samples(rows)
    return _saved(errors)


@app.route("/refresh_sample_sheet")
def refresh_sample_sheet():
    experiment = model.EXPERIMENT
    # The folder comes from the file browser, so it meets the browser's wall:
    # a hand-written path above the workspace is refused here exactly as a
    # listing of it would be.
    raw = request.args.get("path")
    try:
        folder = model.resolve(raw) if raw else None
    except model.PermissionRequired as exc:
        return jsonify(presenters.permission_view(exc.path)), 403
    if folder is not None and not folder.is_dir():
        return jsonify({"ok": False, "error": f"not a folder: {folder}"}), 404
    return jsonify({"ok": True,
                    "rows": experiment.scan_folder(str(folder) if folder else None),
                    "columns": experiment.pipeline["columns"]})


# ── reference databases ──────────────────────────────────────────────────────
#
# What a run reads and this machine may not have. All three routes answer with
# the same view, so the page is never told half the story: asking, starting an
# install and stopping one all come back saying what every database is and
# what is happening to it — and whether the run can start, because a database
# arriving is one of the things that lets it.
#
# There is no route that reports progress on its own. A download lives in this
# process and dies with it, so the page learns how far along it is by asking
# again — the same way it learns everything else here. Nothing has to be done
# when one finishes: it lands where timon looks, and the next ask finds it.

def _chosen() -> dict[str, str]:
    """Which build the page has picked, by database: ``variant.<db>=<id>``.

    Carried on the request rather than kept here. A database published in
    more than one build (the two caps of the Kraken2 index) is a choice the
    user makes in the card, and it only means anything at the moment install
    is pressed — so the page holds it and sends it, and timon has no
    preference of its own to keep in step with theirs.
    """
    return {name.split(".", 1)[1]: value
            for name, value in request.values.items()
            if name.startswith("variant.") and value}


def _databases() -> dict:
    experiment = model.EXPERIMENT
    return {**presenters.databases_view(experiment, _chosen()),
            "can_start": _run_view(experiment)["can_start"]}


@app.route("/databases")
def databases():
    return jsonify({"ok": True, **_databases()})


@app.route("/databases/install", methods=["POST"])
def databases_install():
    # No database named is the install button: the bundle. One named is a
    # database outside it that this run reads.
    named = request.form.getlist("db")
    try:
        model.downloads.install(named or None, _chosen())
    except model.DownloadError as exc:
        # Nothing was started, for reasons that are answers rather than
        # faults, so the current state goes back with them.
        return jsonify({"ok": False, "error": str(exc), **_databases()}), 400
    return jsonify({"ok": True, **_databases()})


@app.route("/databases/cancel", methods=["POST"])
def databases_cancel():
    stopped = model.downloads.cancel(request.form.get("db") or None)
    return jsonify({"ok": True, "stopped": stopped, **_databases()})


# ── past runs ────────────────────────────────────────────────────────────────
#
# A run is remembered as the folder it wrote plus a note inside it, so these
# two routes are the whole feature: read the notes in the workspace, and hand
# one back to the experiment the form is written against.

@app.route("/runs")
def runs():
    experiment = model.EXPERIMENT
    # A record left saying "running" is the model's to reinterpret — the
    # process behind it may be going still, may have been this timon's, or
    # may be gone — and telling it which one is ours saves it asking the
    # operating system about a run this process is holding open anyway.
    active = experiment.exp_id if model.RUN.running else ""
    # Runs going in other workspaces have no record to be listed from here,
    # so they come from the pointers they left. Shown because a run outlives
    # the timon that started it: one launched in a folder the user has since
    # left is still theirs to watch and to stop.
    elsewhere = [entry for entry in model.live.running()
                 if entry.output_folder != experiment.output_folder]
    return jsonify({"ok": True,
                    **presenters.runs_view(
                        model.history.runs(experiment.output_folder, active),
                        experiment.exp_id, elsewhere)})


@app.route("/runs/open", methods=["POST"])
def runs_open():
    """Reopen a past run exactly as it ran, so running it again repeats it.

    What comes back is what a pipeline switch returns plus the sample rows:
    the page rebuilds the form from it exactly as it would after a switch,
    and locks it, because the run is pinned (``run_view``'s ``pinned``). The
    run's own output is not in it — the console is sent that over the
    socket, the same way it is sent every run's.
    """
    experiment = model.EXPERIMENT
    record = model.history.load(experiment.output_folder,
                                request.form.get("exp_id", "").strip())
    if record is None:
        return jsonify({"ok": False, "error": "no record of that run"}), 404
    try:
        experiment.restore(record)
    except model.RunUnavailable as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "samples": experiment.samples,
                    **_form_reply(experiment),
                    **_run_view(experiment),
                    "databases": presenters.databases_view(experiment)})


@app.route("/runs/unpin", methods=["POST"])
def runs_unpin():
    """Let a reopened run be edited, which makes it an ordinary configuration."""
    experiment = model.EXPERIMENT
    experiment.unpin()
    return jsonify({"ok": True, **_run_view(experiment)})


# ── file browser ─────────────────────────────────────────────────────────────
#
# Only listings are served here, never file contents. The workspace rule is
# enforced in model/files.py, so these routes just translate its refusal into
# the 403 the page reacts to by asking the user.

@app.route("/browse")
def browse():
    try:
        return jsonify({"ok": True,
                        **presenters.listing_view(model.listing(request.args.get("path")))})
    except model.PermissionRequired as exc:
        return jsonify(presenters.permission_view(exc.path)), 403
    except (FileNotFoundError, NotADirectoryError) as exc:
        return jsonify({"ok": False, "error": f"not a folder: {exc}"}), 404
    except OSError as exc:
        # Most often a directory the user cannot read. Reported rather than
        # raised: browsing into it is a normal mistake, not a server error.
        return jsonify({"ok": False, "error": f"cannot read folder: {exc.strerror or exc}"}), 403


@app.route("/browse_allow_outside", methods=["POST"])
def browse_allow_outside():
    """Grant browsing above the workspace — this process only, no state on disk."""
    model.ACCESS.allow_outside()
    return jsonify({"ok": True, "outside_ok": True})


@app.route("/browse_lock_workspace", methods=["POST"])
def browse_lock_workspace():
    model.ACCESS.lock()
    return jsonify({"ok": True, "outside_ok": False, "root": str(model.workspace_root())})


@app.route("/browse_pick", methods=["POST"])
def browse_pick():
    """Turn the files picked in the browser into one sample-sheet value.

    Collapsing several files into a wildcard is done server-side because
    model.convert_realpaths_to_wildcards is what the folder scan already
    uses: a second implementation in the page could disagree with it.
    """
    paths = request.form.getlist("paths")
    if not paths:
        return jsonify({"ok": False, "error": "nothing selected"}), 400
    try:
        resolved = [str(model.resolve(p)) for p in paths]
    except model.PermissionRequired as exc:
        return jsonify(presenters.permission_view(exc.path)), 403
    return jsonify({"ok": True,
                    "value": model.convert_realpaths_to_wildcards(sorted(resolved))})


# ── results ──────────────────────────────────────────────────────────────────
#
# The output folder, browsed and read. Unlike the file browser above these
# routes do serve file contents, so the rule they lean on is the narrower one
# in model/results.py: everything is resolved against the output folder and
# there is no grant that reaches past it.
#
# What is served is whatever a pipeline wrote, which includes HTML reports.
# Those are handed to the page inside a sandboxed iframe and, for anything
# that can carry a script of its own, sent with a sandbox header too — so a
# report cannot reach the page that framed it whether it is opened here or
# pasted into a tab of its own.

SANDBOXED = {"html", "image"}       # image only matters for svg, which is markup
SANDBOX_POLICY = "sandbox allow-scripts allow-popups allow-downloads allow-forms"

# The price of that sandbox is an opaque origin, and in one of those merely
# *reading* localStorage, sessionStorage or document.cookie throws. Reports
# read them unguarded to remember a theme or a saved view — MultiQC does it
# at load, and the exception stops its plots being drawn at all. Granting
# allow-same-origin would hand the report this page, so instead a report is
# given stand-ins that hold nothing past the tab, placed ahead of every
# script of its own. Only where the real one throws: a browser that does
# grant storage keeps it.
STORAGE_SHIM = (
    b"<script>(function(){"
    b"function mem(){var d=new Map();return{"
    b"get length(){return d.size},"
    b"key:function(i){var k=Array.from(d.keys())[i];return k===undefined?null:k},"
    b"getItem:function(k){k=String(k);return d.has(k)?d.get(k):null},"
    b"setItem:function(k,v){d.set(String(k),String(v))},"
    b"removeItem:function(k){d.delete(String(k))},"
    b"clear:function(){d.clear()}}}"
    b"['localStorage','sessionStorage'].forEach(function(n){"
    b"try{window[n]}catch(e){Object.defineProperty(window,n,{value:mem(),configurable:true})}});"
    b"try{document.cookie}catch(e){Object.defineProperty(document,'cookie',"
    b"{get:function(){return ''},set:function(){},configurable:true})}"
    b"})();</script>"
)


def _with_storage_shim(markup: bytes) -> bytes:
    """The report, with STORAGE_SHIM ahead of anything it runs.

    Straight after ``<head>`` when there is one, so the doctype stays first
    and the page is not thrown into quirks mode; at the very top otherwise,
    which a browser parses into the head all the same.
    """
    match = re.search(rb"<head(?:\s[^>]*)?>", markup[:65536], re.IGNORECASE)
    at = match.end() if match else 0
    return markup[:at] + STORAGE_SHIM + markup[at:]


def _results_root() -> str:
    return model.EXPERIMENT.output_folder


@app.route("/results/browse")
def results_browse():
    try:
        listing = model.results.listing(_results_root(), request.args.get("path"))
    except model.OutsideResults:
        return jsonify({"ok": False, "error": "outside the output folder"}), 403
    except (FileNotFoundError, NotADirectoryError):
        return jsonify({"ok": False, "error": "that folder is not there any more"}), 404
    except OSError as exc:
        return jsonify({"ok": False,
                        "error": f"cannot read that folder: {exc.strerror or exc}"}), 403
    return jsonify({"ok": True,
                    **presenters.results_view(listing, model.EXPERIMENT.exp_id)})


@app.route("/results/view")
def results_view():
    """One file's contents, for the kinds timon shows itself."""
    try:
        preview = model.results.preview(_results_root(), request.args.get("path", ""))
    except model.OutsideResults:
        return jsonify({"ok": False, "error": "outside the output folder"}), 403
    except (FileNotFoundError, IsADirectoryError):
        return jsonify({"ok": False, "error": "that file is not there any more"}), 404
    except OSError as exc:
        return jsonify({"ok": False,
                        "error": f"cannot read that file: {exc.strerror or exc}"}), 403
    return jsonify({"ok": True, **presenters.preview_view(preview)})


@app.route("/results/raw/<path:rel>")
def results_raw(rel):
    """The bytes themselves: what an <img>, an iframe and a download read.

    The path is in the URL rather than in a query string so that a report
    made of several files still works: an HTML page that pulls in a
    stylesheet beside it resolves that against its own address, and only
    this shape puts it back in the same folder.

    ``download`` is the difference between looking at a figure and saving
    it; everything else about the two is the same request.
    """
    try:
        path = model.results.resolve(_results_root(), rel)
        if path.is_dir():
            raise IsADirectoryError(str(path))
        if not path.is_file():
            raise FileNotFoundError(str(path))
    except model.OutsideResults:
        return jsonify({"ok": False, "error": "outside the output folder"}), 403
    except (FileNotFoundError, IsADirectoryError):
        return jsonify({"ok": False, "error": "that file is not there any more"}), 404

    download = request.args.get("download") == "1"
    kind = model.results.kind_of(path.name)
    if kind == "html" and not download:
        # Read whole rather than streamed: the shim has to go in ahead of
        # the report's own scripts, and a report is megabytes, not a BAM.
        response = app.response_class(_with_storage_shim(path.read_bytes()),
                                      mimetype="text/html")
    else:
        # A download is the file as the pipeline wrote it, byte for byte.
        response = send_file(path, as_attachment=download,
                             download_name=path.name, conditional=True)
    # Nothing here is ever a script of this page's: a pipeline chose these
    # bytes, and the browser must not go looking for a better content type
    # than the one the extension gave.
    response.headers["X-Content-Type-Options"] = "nosniff"
    if kind in SANDBOXED:
        response.headers["Content-Security-Policy"] = SANDBOX_POLICY
    return response
