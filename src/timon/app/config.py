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

# ── linked pipelines ─────────────────────────────────────────────────────────
#
# Each entry links a Nextflow pipeline to timon. Required keys:
#
#   name, description, icon   what the workflow card shows
#   pipeline                  GitHub "owner/repo", passed to `nextflow run`
#   revision                  the release tag or commit the run is pinned to.
#                             None refuses to run (see core.WorkflowSubprocess)
#   profiles                  container engines the pipeline supports
#   columns, file_column      sample-sheet columns, and which one holds reads
#   requires_db               db keys passed from the environment through
#                             core.DB_FLAGS instead of being asked for in the
#                             form (they are dropped from "params")
#   params                    the run-configuration form
#
# "params" is written by hand, and is a *selection*: a pipeline accepts far
# more than a user should have to look at, and everything left out simply
# keeps the pipeline's own default. Add a parameter here when a run actually
# turns on it. Each entry is:
#
#   id            the Nextflow parameter, passed as --<id>. Required.
#   type          "bool" | "number" | "text" | "select"   (default: text)
#   label         what the form shows; defaults to the id
#   default       must match the pipeline's own default at the pinned
#                 revision, or the form will lie about what a run does
#   description   one line under the field
#   help_text     the part that actually decides a value; disclosed on demand
#   min/max/step  numbers only. step "any" means the value is a float, not an
#                 integer, and is cast as one (see routes.get_run_info_base)
#   enum          selects only: the whole set of accepted values
#   placeholder   text fields only: hint shown while the field is empty
#   required      refuse to save the configuration without a value
#   group         section heading; blurbs come from "param_groups" below
#
# Optional keys:
#
#   param_groups      {group: blurb} for the section headings used by "params"
#   db_optional_when  {db key: [flags]} — a database that is only needed when
#                     some step is not skipped
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
        # The tip of main (unreleased 1.4.0, nf-core template) rather than
        # v1.3.1. Pinned as the commit main pointed at, not as "main", so the
        # run stays reproducible. Replace with the tag once 1.4.0 is cut, and
        # check the defaults below against it.
        "revision": "922f754bdfc10782f52d54ad376cee1195555687",
        # As declared by main's nextflow.config. "debug", "gpu", "drac" and the
        # test profiles are omitted: they are not container engines.
        "profiles": ["docker", "singularity", "apptainer", "podman",
                     "shifter", "charliecloud", "wave", "conda", "mamba"],
        "file_column": "long_reads",
        "requires_db": ["gtdbtk_db"],
        # The pipeline's own rule for gtdbtk_db: required unless --skip_gtdbtk
        # is set. Demanding it from a run that skips the step it feeds would
        # lock the user out of a configuration the pipeline accepts.
        "db_optional_when": {"gtdbtk_db": ["skip_gtdbtk", "skip_bin_qa"]},
        # Matches assets/schema_input.json at this revision.
        "columns": ["sample_id", "group", "assembly_fasta", "long_reads", "short_reads_1", "short_reads_2"],
        "param_groups": {
            "read QC":  "Quality control and filtering of the long reads.",
            "assembly": "How the long reads are assembled and polished.",
            "binning":  "Which binners run, and how they are configured.",
            "bin QC & reporting": "Quality assessment and classification of the recovered bins, and the run report.",
        },
        "params": [
            {"id": "chopper_minlength", "label": "min. length",           "type": "number", "default": 1000, "min": 0,
             "group": "read QC", "description": "Minimum read length kept by Chopper."},
            {"id": "chopper_minq",      "label": "min. Q-score (Phred)",  "type": "number", "default": 10,   "min": 0, "max": 60,
             "group": "read QC", "description": "Minimum average read quality kept by Chopper."},
            {"id": "skip_qc",           "label": "skip QC",               "type": "bool",   "default": False, "group": "read QC"},
            {"id": "skip_nanoplot",     "label": "skip Nanoplot",         "type": "bool",   "default": False, "group": "read QC"},
            {"id": "skip_porechop",     "label": "skip Porechop",         "type": "bool",   "default": False, "group": "read QC"},

            {"id": "assembler",     "label": "assembler",   "type": "select", "default": "flye",
             "enum": ["flye", "metamdbg"], "group": "assembly",
             "description": "Long read assembler to use."},
            {"id": "medaka_model",  "label": "Medaka model", "type": "text",  "default": "r1041_e82_400bps_hac_v5.2.0",
             "group": "assembly", "required": True,
             "description": "Medaka model used to polish the assembly.",
             "help_text": "Must match the flow cell, kit and basecaller used to produce the reads. "
                          "Run `medaka tools list_models` to see the models available in the container."},
            {"id": "skip_medaka",   "label": "skip Medaka",  "type": "bool",  "default": False, "group": "assembly"},

            {"id": "maxbin_minlen",  "label": "MaxBin2 min. contig length", "type": "number", "default": 2500, "min": 0,
             "group": "binning", "description": "Minimum contig length considered by MaxBin2."},
            {"id": "sc_mag_minimum", "label": "single-contig MAG length",   "type": "number", "default": 500000, "min": 0,
             "group": "binning",
             "description": "Contigs at least this long are assessed on their own as candidate single-contig MAGs."},
            # A percentage the pipeline declares as a float: step "any" keeps
            # 92.5 from being saved back as 92.
            {"id": "sc_mag_min_completeness", "label": "single-contig MAG min. completeness (%)", "type": "number",
             "default": 90, "min": 0, "max": 100, "step": "any", "group": "binning",
             "description": "CheckM2 completeness a long contig must reach to be kept out of binning as a single-contig MAG."},
            {"id": "skip_maxbin",  "label": "skip MaxBin2", "type": "bool", "default": False, "group": "binning"},
            {"id": "skip_concoct", "label": "skip CONCOCT", "type": "bool", "default": False, "group": "binning"},
            {"id": "skip_semibin", "label": "skip SemiBin2", "type": "bool", "default": False, "group": "binning"},

            {"id": "skip_bin_qa", "label": "skip bin QA",  "type": "bool", "default": False, "group": "bin QC & reporting",
             "description": "Skip CheckM2, GTDB-Tk and the MAG summary."},
            {"id": "skip_gtdbtk", "label": "skip GTDB-Tk", "type": "bool", "default": False, "group": "bin QC & reporting"},
            {"id": "skip_multiqc", "label": "skip MultiQC", "type": "bool", "default": False, "group": "bin QC & reporting"},
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
