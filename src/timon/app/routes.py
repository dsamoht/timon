"""HTTP surface: read the request, ask the model, render the answer.

Every route here is the same three steps. Nothing in this file decides
anything about a run — it translates form encoding into plain values, hands
them to the model, and passes what comes back to a presenter. The rules it
would otherwise be tempting to inline (which parameters count, what makes a
sample sheet valid, when a run may start) all live in ``model/``, so the page
and any other caller get the same answers.
"""

from flask import current_app as app, jsonify, render_template, request

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


def _saved(errors: list[str]):
    """One shape for every save: the reasons it was refused, or the new state."""
    if errors:
        return jsonify({"ok": False, "errors": errors, "error": errors[0]}), 400
    return jsonify({"ok": True, **presenters.run_view(model.EXPERIMENT, model.engine())})


# ── page ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template("index.html",
                           **presenters.index_view(model.EXPERIMENT, model.engine(),
                                                   __version__, __release_year__))


@app.route("/set_pipeline", methods=["POST"])
def set_pipeline():
    experiment = model.EXPERIMENT
    if not experiment.set_pipeline(request.form.get("pipeline_select")):
        return jsonify({"ok": False, "error": "Unknown pipeline"}), 400
    pipe = experiment.pipeline
    # The fields are rendered here rather than rebuilt in JS: the page and this
    # response would otherwise be two implementations of the same form.
    return jsonify({
        "ok": True,
        "pipeline_id": experiment.pipeline_id,
        "columns": pipe["columns"],
        "path_columns": model.path_columns(pipe),
        "params_html": render_template("_params.html",
                                       **presenters.params_view(experiment)),
    })


@app.route("/get_run_info_base", methods=["POST"])
def get_run_info_base():
    experiment = model.EXPERIMENT
    # Everything declared is read, active or not: which of them the run keeps
    # is the model's to settle, and it needs the hidden ones to settle it.
    declared = P.fields(experiment.pipeline) + P.db_fields(experiment.pipeline)
    errors = experiment.apply_configuration(request.form.get("exp-id", "").strip(),
                                            _submitted(declared))
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
    return jsonify({"ok": True,
                    "rows": experiment.scan_input_folder(),
                    "columns": experiment.pipeline["columns"]})


@app.route("/reset_all")
def reset_all():
    model.EXPERIMENT.reset()
    return jsonify({"ok": True})


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
