from flask import render_template, request, redirect, url_for, flash, current_app as app
import pandas as pd
import uuid, os
from .core import EXP_CONFIG, SAMPLES, WF_SUBPROCESS
from .config import Config, PIPELINES
from .utils import detect_samples_files, input_validation


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
    if EXP_CONFIG.set_pipeline(p_id):
        SAMPLES.clear()
        flash(f"Pipeline selected: {p_id}", "success")
    return redirect(url_for("index"))

@app.route("/get_run_info_base", methods=["POST"])
def get_run_info_base():
    exp_id = request.form.get("exp-id")
    if not input_validation(exp_id):
        flash("Invalid Experiment ID", "error")
        return redirect(url_for("index"))
    
    EXP_CONFIG.update(exp_id=exp_id)
    
    # Update dynamic params from form
    pipe = EXP_CONFIG.get_pipe()
    for p in pipe.get("params", []):
        val = request.form.get(p["id"])
        if p["type"] == "bool":
            EXP_CONFIG.set_param(p["id"], val == "on")
        else:
            EXP_CONFIG.set_param(p["id"], val)
    
    flash("Configuration saved", "success")
    return redirect(url_for("index"))

@app.route("/update_samples", methods=["POST"])
def update_samples():
    pipe = EXP_CONFIG.get_pipe()
    # Dynamic column retrieval based on active pipeline
    data = {col: request.form.getlist(col) for col in pipe["columns"]}
    df = pd.DataFrame(data)
    
    SAMPLES.clear()
    SAMPLES.extend(df.to_dict(orient="records"))
    
    if not df.empty:
        filename = f"samplesheet_{uuid.uuid4().hex}.csv"
        path = os.path.join(Config.IMPORT_FOLDER, filename)
        df.to_csv(path, index=False)
        
        EXP_CONFIG.update(samplesheet=path, n_samples=len(df))
        flash("Sample sheet updated successfully", "success")
    
    return redirect(url_for("index"))

@app.route("/refresh_sample_sheet")
def refresh_sample_sheet():
    files = detect_samples_files()
    pipe = EXP_CONFIG.get_pipe()
    
    SAMPLES.clear()
    count = 0
    for name, path in files.items():
        # Create a row with empty strings for all columns
        row = {c: "" for c in pipe["columns"]}
        
        # Populate the knowns: ID and File Path
        # We assume the first column in config is always the Identifier
        id_col = pipe["columns"][0] 
        file_col = pipe["file_column"]
        
        row[id_col] = name
        row[file_col] = path
        
        SAMPLES.append(row)
        count += 1
        
    flash(f"{count} samples detected.", "success")
    return redirect(url_for("index"))

@app.route("/reset_all")
def reset_all():
    EXP_CONFIG.reset()
    SAMPLES.clear()
    flash("All settings reset.", "success")
    return redirect(url_for("index"))
