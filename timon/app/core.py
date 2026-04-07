import subprocess
import os
import shutil
from typing import Optional
from .config import PIPELINES, Config

SAMPLES = []

class ExpConfig:
    def __init__(self):
        self._config = {
            "exp_id": "",
            "samplesheet": "",
            "n_samples": 0,
            "current_pipeline": "roshab-cli", # Default
            "params": {}
        }
        self.set_pipeline("roshab-cli")

    def set_pipeline(self, pipeline_id):
        if pipeline_id in PIPELINES:
            self._config["current_pipeline"] = pipeline_id
            pipe = PIPELINES[pipeline_id]
            self._config["params"] = {p["id"]: p["default"] for p in pipe.get("params", [])}
            # Note: We do not clear the samplesheet path here immediately to allow 
            # re-using uploaded sheets if columns match, but strictly speaking 
            # different pipelines might need different sheets.
            return True
        return False

    def update(self, **kwargs):
        self._config.update(kwargs)

    def set_param(self, key, val):
        self._config["params"][key] = val

    def get_pipe(self):
        return PIPELINES[self._config["current_pipeline"]]

    def as_dict(self):
        return self._config
    
    def reset(self):
        """Resets config and deletes temporary samplesheet."""
        if self._config["samplesheet"] and os.path.exists(self._config["samplesheet"]):
            try:
                os.remove(self._config["samplesheet"])
            except OSError:
                pass
        self.__init__()

    def is_ready(self):
        return all([self._config["exp_id"], self._config["samplesheet"]])

class WorkflowSubprocess:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None

    def start(self, config_dict):
        pipe = PIPELINES[config_dict["current_pipeline"]]
        
        # Define Work and Output directories based on Import Folder or a dedicated dir
        base_dir = Config.IMPORT_FOLDER.rstrip(r'/')
        out_dir = os.path.join(base_dir, config_dict["exp_id"])
        work_dir = os.path.join(base_dir, "work")

        # Build command
        cmd = ["nextflow", "run", pipe["pipeline"], 
               "--input", config_dict["samplesheet"], 
               "--exp", config_dict["exp_id"],
               "--output", out_dir,
               "-w", work_dir]
        
        # Dynamic params
        for k, v in config_dict["params"].items():
            if isinstance(v, bool):
                if v: cmd.append(f"--{k}")
            elif v:
                cmd.extend([f"--{k}", str(v)])

        self.process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, 
            text=True,
            bufsize=1, # Line buffered
            universal_newlines=True
        )

    def cancel(self):
        if self.process:
            self.process.kill()
            self.process = None

EXP_CONFIG = ExpConfig()
WF_SUBPROCESS = WorkflowSubprocess()
