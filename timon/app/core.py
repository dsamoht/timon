import subprocess
import os
from typing import Optional
from .config import PIPELINES, Config

SAMPLES = []

DB_REGISTRY = {
    "kraken_db": (lambda: Config.KRAKEN_DB, "--kraken_db"),
    "gtdbtk_db": (lambda: Config.GTDBTK_DB, "--gtdbtk_db"),
}


class ExpConfig:
    def __init__(self):
        self._config = {
            "exp_id":           "",
            "samplesheet":      "",
            "n_samples":        0,
            "current_pipeline": "roshab-cli",
            "kraken_db":        Config.KRAKEN_DB,
            "gtdbtk_db":        Config.GTDBTK_DB,
            "input_folder":     os.path.abspath(Config.IMPORT_FOLDER),
            "params":           {},
        }
        self.set_pipeline("roshab-cli")

    def set_pipeline(self, pipeline_id):
        if pipeline_id not in PIPELINES:
            return False
        self._config["current_pipeline"] = pipeline_id
        pipe = PIPELINES[pipeline_id]
        self._config["params"] = {p["id"]: p["default"] for p in pipe.get("params", [])}
        return True

    def update(self, **kwargs):
        self._config.update(kwargs)

    def set_param(self, key, val):
        self._config["params"][key] = val

    def get_pipe(self):
        return PIPELINES[self._config["current_pipeline"]]

    def as_dict(self):
        return self._config

    def reset(self):
        if self._config["samplesheet"] and os.path.exists(self._config["samplesheet"]):
            try:
                os.remove(self._config["samplesheet"])
            except OSError:
                pass
        self.__init__()

    def required_dbs(self) -> list[str]:
        return self.get_pipe().get("requires_db", [])

    def is_ready(self) -> bool:
        cfg = self._config
        if not cfg["exp_id"] or not cfg["samplesheet"] or not cfg["input_folder"]:
            return False
        for db_key in self.required_dbs():
            if not cfg.get(db_key):
                return False
        return True


class WorkflowSubprocess:
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.last_cmd: list[str] = []

    def start(self, config_dict):
        pipe         = PIPELINES[config_dict["current_pipeline"]]
        input_folder = config_dict["input_folder"]
        out_dir      = os.path.join(input_folder, config_dict["exp_id"])
        work_dir     = os.path.join(input_folder, "work")

        cmd = [
            "nextflow", "run", pipe["pipeline"],
            "--input",  config_dict["samplesheet"],
            "--outdir", out_dir,
            "-w",       work_dir,
            "-ansi-log", "false"
        ]

        for db_key in pipe.get("requires_db", []):
            _, nf_flag = DB_REGISTRY[db_key]
            val = config_dict.get(db_key, "")
            if val:
                cmd.extend([nf_flag, val])

        for k, v in config_dict["params"].items():
            if isinstance(v, bool):
                if v:
                    cmd.append(f"--{k}")
            elif v is not None and str(v).strip() != "":
                cmd.extend([f"--{k}", str(v)])

        if pipe["name"] == "roshab-cli":
            cmd.extend(["--genomes_db", "/app/timon/data/cyanobacteriota_ncbi_dRep_n220"])
            cmd.extend(["--genes_db", "/app/timon/data/core_cyanotoxin-related_gene_mibig-v4_antismash-v8.faa"])

        self.last_cmd = cmd  # store before Popen so it's available even if Popen raises

        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

    def cancel(self):
        if self.process:
            self.process.kill()
            self.process = None


EXP_CONFIG = ExpConfig()
WF_SUBPROCESS = WorkflowSubprocess()
