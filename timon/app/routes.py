from flask import render_template, request, current_app as app, jsonify
import pandas as pd
import uuid, os, re
from .core import EXP_CONFIG, SAMPLES
from .config import Config, PIPELINES
from .utils import detect_samples_files, input_validation


# ── helpers ─────────────────────────────────────────────────────────────────

EXP_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _validate_config(exp_id: str, pipe: dict, form) -> list[str]:
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
    cfg = EXP_CONFIG.as_dict()
    for db_key in required_dbs:
        val = cfg.get(db_key, "")
        label = db_labels.get(db_key, db_key)
        if not val:
            errors.append(f"{label} path is required for this pipeline")
        elif not os.path.isdir(val):
            errors.append(f"{label} path not found: {val!r}")

    if not cfg.get("current_pipeline"):
        errors.append("no pipeline selected")

    # numeric params
    for p in pipe.get("params", []):
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
        if "min" in p and val < p["min"]:
            errors.append(f"'{p['label']}' must be ≥ {p['min']}")
        if "max" in p and val > p["max"]:
            errors.append(f"'{p['label']}' must be ≤ {p['max']}")

    # required text params (no empty default)
    for p in pipe.get("params", []):
        if p["type"] != "text":
            continue
        if p.get("default", None) is None:
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
    return render_template("index.html",
                           exp_config=EXP_CONFIG.as_dict(),
                           table_rows=SAMPLES,
                           pipelines=PIPELINES,
                           active_pipe=EXP_CONFIG.get_pipe())


@app.route("/set_pipeline", methods=["POST"])
def set_pipeline():
    p_id = request.form.get("pipeline_select")
    if not EXP_CONFIG.set_pipeline(p_id):
        return jsonify({"ok": False, "error": "Unknown pipeline"}), 400
    SAMPLES.clear()
    pipe = EXP_CONFIG.get_pipe()
    return jsonify({
        "ok": True,
        "pipeline_id": p_id,
        "columns": pipe["columns"],
        "params": pipe.get("params", []),
        "param_values": EXP_CONFIG.as_dict()["params"]
    })


@app.route("/get_run_info_base", methods=["POST"])
def get_run_info_base():
    exp_id = request.form.get("exp-id", "").strip()
    pipe   = EXP_CONFIG.get_pipe()

    errors = _validate_config(exp_id, pipe, request.form)
    if errors:
        return jsonify({"ok": False, "errors": errors, "error": errors[0]}), 400

    EXP_CONFIG.update(exp_id=exp_id)

    for p in pipe.get("params", []):
        val = request.form.get(p["id"])
        if p["type"] == "bool":
            EXP_CONFIG.set_param(p["id"], val == "on")
        elif p["type"] == "number":
            try:
                EXP_CONFIG.set_param(p["id"], int(float(val)))
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


@app.route("/reset_all")
def reset_all():
    EXP_CONFIG.reset()
    SAMPLES.clear()
    return jsonify({"ok": True})
