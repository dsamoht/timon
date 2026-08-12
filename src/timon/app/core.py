import subprocess
import os
import shutil
from functools import lru_cache
from typing import Optional
from .config import PIPELINES, Config
from ..paths import genes_db, genomes_db, missing_reference_data

SAMPLES = []

DB_REGISTRY = {
    "kraken_db": (lambda: Config.KRAKEN_DB, "--kraken_db"),
    "gtdbtk_db": (lambda: Config.GTDBTK_DB, "--gtdbtk_db"),
}


class WorkflowError(RuntimeError):
    """A run cannot be started with the current configuration."""


def nextflow_bin() -> str:
    """Sites that provide their own nextflow (`module load`) can point at it."""
    return os.getenv("TIMON_NEXTFLOW", "nextflow")


@lru_cache(maxsize=8)
def _nextflow_version(exe: str) -> str:
    """Cached per resolved path: launching nextflow costs about a second."""
    try:
        proc = subprocess.run([exe, "-v"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or proc.stderr).strip()


def nextflow_status() -> dict:
    """Whether nextflow can actually be launched, for the status indicator.

    `which` is re-checked on every call so installing nextflow and reloading
    the page reports the truth; only the version string is cached.
    """
    exe = shutil.which(nextflow_bin())
    if not exe:
        return {
            "ok": False,
            "label": "nextflow not found",
            "detail": f"{nextflow_bin()!r} is not on PATH — "
                      "install it, or set TIMON_NEXTFLOW to its location",
        }
    version = _nextflow_version(exe)
    return {
        "ok": True,
        "label": version.replace("nextflow version ", "nextflow ") or "nextflow ready",
        "detail": exe,
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
            "profile":          Config.PROFILE,
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

    def supported_profiles(self) -> list[str]:
        return self.get_pipe().get("profiles", [])

    def is_ready(self) -> bool:
        cfg = self._config
        if not cfg["exp_id"] or not cfg["samplesheet"] or not cfg["input_folder"]:
            return False
        if cfg.get("profile") not in self.supported_profiles():
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
        pipe = PIPELINES[config_dict["current_pipeline"]]

        # An unpinned pipeline would resolve to whatever the default branch
        # happens to be today, so two runs of the same timon version could not
        # be compared. Refuse rather than produce something uncitable.
        revision = pipe.get("revision")
        if not revision:
            raise WorkflowError(
                f"pipeline {pipe['name']!r} has no pinned revision — refusing to "
                "run, because the result would not be reproducible"
            )

        profile = config_dict.get("profile") or Config.PROFILE
        if profile not in pipe.get("profiles", []):
            supported = ", ".join(pipe.get("profiles", [])) or "none"
            raise WorkflowError(
                f"pipeline {pipe['name']!r} does not support profile "
                f"{profile!r} (supported: {supported})"
            )

        input_folder = config_dict["input_folder"]
        out_dir      = os.path.join(input_folder, config_dict["exp_id"])
        work_dir     = os.path.join(input_folder, "work")

        cmd = [
            nextflow_bin(), "run", pipe["pipeline"],
            "-r",        revision,
            "-profile",  profile,
            "--input",   config_dict["samplesheet"],
            "--outdir",  out_dir,
            "-w",        work_dir,
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
            missing = missing_reference_data()
            if missing:
                raise WorkflowError(
                    "reference data missing — run `timon fetch-db`, or set "
                    "TIMON_DB_DIR to an existing copy.\n  " + "\n  ".join(missing)
                )
            cmd.extend(["--genomes_db", str(genomes_db())])
            cmd.extend(["--genes_db", str(genes_db())])

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
