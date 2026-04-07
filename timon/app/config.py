import os

class Config:
    SECRET_KEY = "timon_secret_key!"
    IMPORT_FOLDER = os.getenv("INPUT_DIR", "imports")

PIPELINES = {
    "roshab-cli": {
        "name": "roshab-cli",
        "description": "Characterization of algal blooms from metagenomic data",
        "icon": "img/bloom_orig.png",
        "pipeline": "dsamoht/roshab-cli",
        "file_column": "reads",
        "columns": ["sample_id", "date", "info", "group", "reads"],
        "params": []
    },
    "mag-ont": {
        "name": "mag-ont",
        "description": "Automation of metagenome assembly and binning with support for long reads",
        "icon": "img/mag-icon.png",
        "pipeline": "dsamoht/mag-ont",
        "file_column": "long_reads",
        "columns": ["sample_id", "group", "assembly_fasta", "long_reads", "short_reads_1", "short_reads_2"],
        "params": [
            {"id": "skip_qc", "label": "skip QC", "type": "bool", "default": False},
            {"id": "skip_porechop", "label": "skip Porechop", "type": "bool", "default": False},
            {"id": "skip_medaka", "label": "skip Medaka", "type": "bool", "default": False},
            {"id": "skip_maxbin", "label": "skip MaxBin", "type": "bool", "default": False},
            {"id": "skip_semibin", "label": "skip SemiBin", "type": "bool", "default": False},
            {"id": "chopper_minq", "label": "min. Q-score (Phred)", "type": "number", "default": 10},
            {"id": "chopper_minlength", "label": "min. length", "type": "number", "default": 1000},
            {"id": "gtdbtk_db", "label": "GTDB-Tk database path", "type": "text", "default": ""}
        ]
    },
    "isolate-wf": {
        "name": "isolate-wf",
        "description": "Workflow for isolate genome assembly",
        "icon": "img/isolate-icon.png",
        "pipeline": "dsamoht/isolate-wf",
        "file_column": "long_reads",
        "columns": ["sample_id", "long_reads", "short_reads_1", "short_reads_2"],
        "params": [
            {"id": "skip_qc", "label": "skip QC", "type": "bool", "default": False},
            {"id": "skip_porechop", "label": "skip Porechop", "type": "bool", "default": False},
            {"id": "chopper_minq", "label": "min. Q-score (Phred)", "type": "number", "default": 10},
            {"id": "chopper_minlength", "label": "min. length", "type": "number", "default": 1000},
            {"id": "gtdbtk_db", "label": "GTDB-Tk database path", "type": "text", "default": ""}
        ]
    }
}
