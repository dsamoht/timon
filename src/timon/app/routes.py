from flask import render_template, request, current_app as app, jsonify
import pandas as pd
import uuid, os, re
from .. import __version__
from .core import EXP_CONFIG, SAMPLES, nextflow_status
from .config import Config, PIPELINES
from .params import fields as param_fields, param_sections
from .files import (ACCESS, PermissionRequired, display, listing, path_columns,
                    resolve, workspace_root)
from .utils import detect_samples_files, convert_realpaths_to_wildcards


# ── helpers ─────────────────────────────────────────────────────────────────

EXP_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _validate_config(exp_id: str, pipe: dict, params: list[dict], form) -> list[str]:
    errors: list[str] = []

    # run identifier
    if not exp_id:
        errors.append("run identifier is required")
    elif not EXP_ID_RE.match(exp_id):
        errors.append("run identifier: only letters, digits, hyphens and underscores allowed")
    elif len(exp_id) > 64 or len(exp_id) < 3:
        errors.append("run identifier: min 3 char & max 64 char allowed")

    # Only validate the db paths this pipeline actually requires
    required_dbs = pipe.get("requires_db", [])
    db_labels = {"kraken_db": "Kraken2 database", "gtdbtk_db": "GTDB-Tk database"}
    # A database a pipeline needs only when some step is not skipped: the flag
    # is checked in the form being saved, not in the stored configuration,
    # because it is that form the user is asking to accept.
    optional_when = pipe.get("db_optional_when", {})
    cfg = EXP_CONFIG.as_dict()
    for db_key in required_dbs:
        val = cfg.get(db_key, "")
        label = db_labels.get(db_key, db_key)
        if any(form.get(flag) == "on" for flag in optional_when.get(db_key, [])):
            # Still checked below if a path was given: a wrong path is worth
            # reporting even when the step that would read it is skipped.
            if val and not os.path.isdir(val):
                errors.append(f"{label} path not found: {val!r}")
            continue
        if not val:
            errors.append(f"{label} path is required for this pipeline")
        elif not os.path.isdir(val):
            errors.append(f"{label} path not found: {val!r}")

    if not cfg.get("current_pipeline"):
        errors.append("no pipeline selected")

    # numeric params
    for p in params:
        if p["type"] != "number":
            continue
        raw = form.get(p["id"], "").strip()
        if raw == "":
            errors.append(f"'{p['label']}' is required")
            continue
        try:
            val = float(raw)
        except ValueError:
            errors.append(f"'{p['label']}' must be a number (got: {raw!r})")
            continue
        if p.get("step") == 1 and val != int(val):
            errors.append(f"'{p['label']}' must be a whole number (got: {raw!r})")
        if "min" in p and val < p["min"]:
            errors.append(f"'{p['label']}' must be ≥ {p['min']}")
        if "max" in p and val > p["max"]:
            errors.append(f"'{p['label']}' must be ≤ {p['max']}")

    # a select's enum is the whole set of accepted values
    for p in params:
        if p["type"] != "select":
            continue
        raw = form.get(p["id"], "").strip()
        if raw and raw not in p.get("enum", []):
            allowed = ", ".join(p.get("enum", []))
            errors.append(f"'{p['label']}': {raw!r} is not one of {allowed}")

    # text params the pipeline entry marks as required
    for p in params:
        if p["type"] not in ("text", "select") or not p.get("required"):
            continue
        if not form.get(p["id"], "").strip():
            errors.append(f"'{p['label']}' is required")

    return errors


def _validate_samples(df: pd.DataFrame, pipe: dict) -> list[str]:
    errors: list[str] = []
    columns = pipe["columns"]
    file_column = pipe.get("file_column")

    if df.empty:
        errors.append("sample sheet is empty — add at least one sample")
        return errors

    for i, row in df.iterrows():
        row_label = f"row {i + 1}"

        for col in columns:
            val = str(row.get(col, "")).strip()
            if not val:
                errors.append(f"{row_label} · '{col}' is required")

        if file_column and file_column in row:
            path = str(row[file_column]).strip()
            if path and "*" not in path and not os.path.exists(path):
                errors.append(f"{row_label} · '{file_column}': path not found — {path!r}")

        if "date" in columns and "date" in row:
            raw_date = str(row["date"]).strip()
            if raw_date and not re.match(r'^\d{4}-\d{2}-\d{2}$', raw_date):
                errors.append(f"{row_label} · 'date': expected YYYY-MM-DD (got {raw_date!r})")

        if "sample_id" in columns and "sample_id" in row:
            sid = str(row["sample_id"]).strip()
            if sid and not re.match(r'^[A-Za-z0-9_\-\.]+$', sid):
                errors.append(
                    f"{row_label} · 'sample_id': only letters, digits, hyphens, dots and underscores allowed"
                )

    if "sample_id" in df.columns:
        sid_series = df["sample_id"].astype(str).str.strip()
        dupes = sid_series[sid_series.duplicated(keep=False)].unique()
        for d in dupes:
            errors.append(f"duplicate sample_id: {d!r}")

    return errors


# ── routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    pipe = EXP_CONFIG.get_pipe()
    return render_template("index.html",
                           exp_config=EXP_CONFIG.as_dict(),
                           table_rows=SAMPLES,
                           pipelines=PIPELINES,
                           active_pipe=pipe,
                           path_columns=path_columns(pipe),
                           param_sections=param_sections(pipe),
                           version=__version__,
                           workspace=display(workspace_root()),
                           nextflow=nextflow_status())


@app.route("/set_pipeline", methods=["POST"])
def set_pipeline():
    p_id = request.form.get("pipeline_select")
    if not EXP_CONFIG.set_pipeline(p_id):
        return jsonify({"ok": False, "error": "Unknown pipeline"}), 400
    SAMPLES.clear()
    pipe = EXP_CONFIG.get_pipe()
    # The fields are rendered here rather than rebuilt in JS: the page and this
    # response would otherwise be two implementations of the same form.
    return jsonify({
        "ok": True,
        "pipeline_id": p_id,
        "columns": pipe["columns"],
        "path_columns": path_columns(pipe),
        "params_html": render_template("_params.html",
                                       exp_config=EXP_CONFIG.as_dict(),
                                       param_sections=param_sections(pipe)),
    })


@app.route("/get_run_info_base", methods=["POST"])
def get_run_info_base():
    exp_id = request.form.get("exp-id", "").strip()
    pipe   = EXP_CONFIG.get_pipe()
    params = param_fields(pipe)

    errors = _validate_config(exp_id, pipe, params, request.form)
    if errors:
        return jsonify({"ok": False, "errors": errors, "error": errors[0]}), 400

    EXP_CONFIG.update(exp_id=exp_id)

    for p in params:
        val = request.form.get(p["id"])
        if p["type"] == "bool":
            EXP_CONFIG.set_param(p["id"], val == "on")
        elif p["type"] == "number":
            # A parameter declared with step "any" is a float: rounding it to
            # an int would silently change the run.
            cast = int if p.get("step") == 1 else float
            try:
                EXP_CONFIG.set_param(p["id"], cast(float(val)))
            except (TypeError, ValueError):
                EXP_CONFIG.set_param(p["id"], p.get("default", 0))
        else:
            EXP_CONFIG.set_param(p["id"], val or "")

    cfg = EXP_CONFIG.as_dict()
    return jsonify({
        "ok": True,
        "run_ready": bool(cfg["exp_id"] and cfg["samplesheet"])
    })


@app.route("/update_samples", methods=["POST"])
def update_samples():
    pipe = EXP_CONFIG.get_pipe()
    data = {col: request.form.getlist(col) for col in pipe["columns"]}

    min_len = min((len(v) for v in data.values()), default=0)
    data = {k: v[:min_len] for k, v in data.items()}
    df = pd.DataFrame(data)
    df = df.apply(lambda col: col.str.strip() if col.dtype == object else col)

    errors = _validate_samples(df, pipe)
    if errors:
        return jsonify({"ok": False, "errors": errors, "error": f"{len(errors)} validation error(s)"}), 400

    cfg = EXP_CONFIG.as_dict()
    if cfg.get("samplesheet") and os.path.exists(cfg["samplesheet"]):
        try:
            os.remove(cfg["samplesheet"])
        except OSError:
            pass

    SAMPLES.clear()
    SAMPLES.extend(df.to_dict(orient="records"))

    folder = cfg.get("input_folder") or Config.IMPORT_FOLDER
    os.makedirs(folder, exist_ok=True)
    filename = f"samplesheet_{uuid.uuid4().hex}.csv"
    path = os.path.join(folder, filename)
    df.to_csv(path, index=False)
    EXP_CONFIG.update(samplesheet=path, n_samples=len(df))

    cfg = EXP_CONFIG.as_dict()
    return jsonify({
        "ok": True,
        "n_samples": len(df),
        "run_ready": bool(cfg["exp_id"] and cfg["samplesheet"])
    })


@app.route("/refresh_sample_sheet")
def refresh_sample_sheet():
    cfg = EXP_CONFIG.as_dict()
    folder = cfg.get("input_folder") or Config.IMPORT_FOLDER
    files = detect_samples_files(folder)
    pipe = EXP_CONFIG.get_pipe()

    SAMPLES.clear()
    rows = []
    for name, path in files.items():
        row = {c: "" for c in pipe["columns"]}
        row[pipe["columns"][0]] = name
        row[pipe["file_column"]] = path
        SAMPLES.append(row)
        rows.append(row)

    return jsonify({"ok": True, "rows": rows, "columns": pipe["columns"]})


# ── file browser ─────────────────────────────────────────────────────────────
#
# Only listings are served here, never file contents. The workspace rule is
# enforced in files.py, so these routes just translate its refusal into the
# 403 the page reacts to by asking the user.

def _permission_payload(path) -> dict:
    return {
        "ok": False,
        "needs_permission": True,
        "path": str(path),
        "display": display(path),
        "root": str(workspace_root()),
        "root_display": display(workspace_root()),
        "error": "outside the workspace timon was launched in",
    }


@app.route("/browse")
def browse():
    try:
        return jsonify({"ok": True, **listing(request.args.get("path"))})
    except PermissionRequired as exc:
        return jsonify(_permission_payload(exc.path)), 403
    except (FileNotFoundError, NotADirectoryError) as exc:
        return jsonify({"ok": False, "error": f"not a folder: {exc}"}), 404
    except OSError as exc:
        # Most often a directory the user cannot read. Reported rather than
        # raised: browsing into it is a normal mistake, not a server error.
        return jsonify({"ok": False, "error": f"cannot read folder: {exc.strerror or exc}"}), 403


@app.route("/browse_allow_outside", methods=["POST"])
def browse_allow_outside():
    """Grant browsing above the workspace — this process only, no state on disk."""
    ACCESS.allow_outside()
    return jsonify({"ok": True, "outside_ok": True})


@app.route("/browse_lock_workspace", methods=["POST"])
def browse_lock_workspace():
    ACCESS.lock()
    return jsonify({"ok": True, "outside_ok": False, "root": str(workspace_root())})


@app.route("/browse_pick", methods=["POST"])
def browse_pick():
    """Turn the files picked in the browser into one sample-sheet value.

    Collapsing several files into a wildcard is done here because
    utils.convert_realpaths_to_wildcards is what the folder scan already
    uses: a second implementation in the page could disagree with it.
    """
    paths = request.form.getlist("paths")
    if not paths:
        return jsonify({"ok": False, "error": "nothing selected"}), 400
    try:
        resolved = [str(resolve(p)) for p in paths]
    except PermissionRequired as exc:
        return jsonify(_permission_payload(exc.path)), 403
    return jsonify({"ok": True, "value": convert_realpaths_to_wildcards(sorted(resolved))})


@app.route("/reset_all")
def reset_all():
    EXP_CONFIG.reset()
    SAMPLES.clear()
    return jsonify({"ok": True})
