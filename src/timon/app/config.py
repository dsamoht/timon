import os
import secrets

class Config:
    SECRET_KEY    = os.getenv("TIMON_SECRET_KEY") or secrets.token_hex(32)
    IMPORT_FOLDER = os.getenv("INPUT_DIR",  "imports")
    KRAKEN_DB     = os.getenv("KRAKEN_DB",  "")
    GTDBTK_DB     = os.getenv("GTDBTK_DB", "")
    # Container engine Nextflow provisions tasks with. Every pipeline declares
    # which of these it supports; see "profiles" below.
    PROFILE       = os.getenv("TIMON_PROFILE", "docker")

PIPELINES = {
    "roshab-cli": {
        "name": "roshab-cli",
        "description": "Taxonomic classification and evaluation of cyanotoxin biosynthesis potential from nanopore reads",
        "icon": "img/bloom_orig.png",
        "pipeline": "dsamoht/roshab-cli",
        # Upstream has no tags yet, so this is pinned to a commit. Replace with
        # a tag once roshab-cli cuts a release; bumping it is a timon release.
        "revision": "20fabf2f4cd371ecaed54943df37b3d0e425589d",
        "profiles": ["docker", "singularity", "apptainer"],
        "file_column": "reads",
        "requires_db": ["kraken_db"],
        "columns": ["sample_name", "date", "info", "group", "reads"],
        "params": [
            {"id": "skip_qc",            "label": "skip QC",                 "type": "bool",   "default": False},
            {"id": "skip_nanoplot",      "label": "skip Nanoplot",           "type": "bool",   "default": False},
            {"id": "chopper_headcrop",   "label": "headcrop",                "type": "number", "default": 80,   "min": 0, "max": 100},
            {"id": "chopper_tailcrop",   "label": "tailcrop",                "type": "number", "default": 50,   "min": 0, "max": 100},
            {"id": "chopper_minlength",  "label": "min. length",             "type": "number", "default": 500,  "min": 0, "max": 10000},
            {"id": "chopper_minq",       "label": "min. Q-score (Phred)",    "type": "number", "default": 9,    "min": 1, "max": 60}
        ]
    },
    "mag-ont": {
        "name": "mag-ont",
        "description": "Automation of metagenome assembly and binning with support for nanopore reads",
        "icon": "img/mag-icon.png",
        "pipeline": "dsamoht/mag-ont",
        # Latest upstream release. main is ahead (unreleased 1.4.0, nf-core
        # template) and adds a conda profile — bump here once it is tagged.
        "revision": "v1.3.1",
        "profiles": ["docker", "singularity", "apptainer"],
        "file_column": "long_reads",
        "requires_db": ["gtdbtk_db"],
        "columns": ["sample_id", "group", "assembly_fasta", "long_reads", "short_reads_1", "short_reads_2"],
        "params": [
            {"id": "skip_qc",         "label": "skip QC",                  "type": "bool",   "default": False},
            {"id": "skip_porechop",   "label": "skip Porechop",            "type": "bool",   "default": False},
            {"id": "skip_medaka",     "label": "skip Medaka",              "type": "bool",   "default": False},
            {"id": "skip_maxbin",     "label": "skip MaxBin",              "type": "bool",   "default": False},
            {"id": "skip_semibin",    "label": "skip SemiBin",             "type": "bool",   "default": False},
            {"id": "chopper_minq",    "label": "min. Q-score (Phred)",     "type": "number", "default": 9,    "min": 1, "max": 60},
            {"id": "chopper_minlength","label": "min. length",             "type": "number", "default": 1000, "min": 0, "max": 10000},
        ]
    },
    "isolate-wf": {
        "name": "isolate-wf",
        "description": "Workflow for consensus isolate genome assembly",
        "icon": "img/isolate-icon.png",
        "pipeline": "dsamoht/isolate-wf",
        # The repository is not published yet; runs are refused until it exists
        # and a revision is pinned here.
        "revision": None,
        "profiles": ["docker", "singularity", "apptainer"],
        "file_column": "long_reads",
        "requires_db": [],
        "columns": ["sample_id", "long_reads", "short_reads_1", "short_reads_2"],
        "params": [
            {"id": "skip_qc",          "label": "skip QC",                 "type": "bool",   "default": False},
            {"id": "skip_porechop",    "label": "skip Porechop",           "type": "bool",   "default": False},
            {"id": "chopper_minq",     "label": "min. Q-score (Phred)",    "type": "number", "default": 10,   "min": 1, "max": 60},
            {"id": "chopper_minlength","label": "min. length",             "type": "number", "default": 1000, "min": 0, "max": 10000},
        ]
    }
}
