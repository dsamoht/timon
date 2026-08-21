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

# ── reference databases ──────────────────────────────────────────────────────
#
# The databases a pipeline declares under ``requires_db``. An environment
# variable fills them in at launch, which is what a shared install wants — but
# it is the only way to name them, so a user who installs a database *after*
# starting timon has to restart it to point at it. They are rendered as fields
# too: the environment gives the value it starts with, the form can change it
# for this run.
#
# Described once, here, rather than per pipeline: the same environment variable
# names the same database for every pipeline that reads it.
ENV_DATABASES = {
    "kraken_db": {
        "label": "Kraken2 database",
        "env": "KRAKEN_DB",
        # Either shape is accepted, so the browser has to be able to pick both.
        "path": "any",
        "description": "Directory, or a `.tar.gz` tarball, holding the Kraken2 index.",
        "help_text": "Pre-built indexes are available from "
                     "https://benlangmead.github.io/aws-indexes/k2. The database must contain "
                     "`ktaxonomy.tsv`, which is used to rebuild the per-sample reports.",
    },
    "gtdbtk_db": {
        "label": "GTDB-Tk database",
        "env": "GTDBTK_DB",
        "path": "dir",
        "description": "Directory holding a local copy of the GTDB-Tk reference data.",
        "help_text": "See https://ecogenomics.github.io/GTDBTk/installing/index.html for how to "
                     "obtain it. Not read by a run that skips the steps it feeds.",
    },
}

# The section env databases are shown in, for a pipeline that does not group
# them with any of its own parameters.
DB_GROUP = "reference databases"

# ── linked pipelines ─────────────────────────────────────────────────────────
#
# Each entry links a Nextflow pipeline to timon. Required keys:
#
#   name, description, icon   what the workflow card shows
#   pipeline                  GitHub "owner/repo", passed to `nextflow run`
#   revision                  the release tag or commit the run is pinned to.
#                             None refuses to run (see model.nextflow.build_command)
#   profiles                  container engines the pipeline supports
#   columns, file_column      sample-sheet columns, and which one holds reads
#   requires_db               db keys described in ENV_DATABASES above and
#                             passed through model.nextflow.DB_FLAGS. An environment
#                             variable fills them in at launch and the form
#                             shows them, so they are never declared in
#                             "params" — that would be a second source
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
#                 integer, and is cast as one (see model.params.coerce)
#   enum          selects only: the whole set of accepted values
#   placeholder   text fields only: hint shown while the field is empty
#   path          text fields only: the value is a filesystem path, so the
#                 field gets the same browse button the sample sheet's path
#                 columns have. "dir" picks a folder, "file" picks a file,
#                 "any" takes either — a database shipped as a directory or
#                 as a tarball
#   required      refuse to save the configuration without a value
#   required_when {other param id: [values]} — required only while that other
#                 parameter holds one of those values (a checkbox is True)
#   active_when   {other param id: [values]} — part of the run only while
#                 *every* one of those parameters holds one of the listed
#                 values. Anything else drops out of the form, out of
#                 validation and off the command line: a QC threshold under
#                 "skip QC", the assembly options of a route this mode does
#                 not take. Conditions chain — a parameter whose controller
#                 has itself dropped out goes with it
#   group         section heading; blurbs come from "param_groups" below
#
# Optional keys:
#
#   param_groups      {group: blurb} for the section headings used by "params"
#   db_group          section the "requires_db" databases are shown in
#                     (default: DB_GROUP, "reference databases")
#   db_optional_when  {db key: [flags]} — a database that is only needed when
#                     some step is not skipped
#   reference_data    timon's own reference data the pipeline is passed, by the
#                     names in model.nextflow.REFERENCE_FLAGS. Unlike
#                     requires_db these are never asked for: timon knows where
#                     they are (see timon.paths) and a run stops if they are
#                     not there
PIPELINES = {
    "roshab-cli": {
        "name": "roshab-cli",
        "description": "Taxonomic classification and evaluation of cyanotoxin biosynthesis potential from nanopore reads",
        "icon": "img/bloom_orig.png",
        "pipeline": "dsamoht/roshab-cli",
        # Upstream has no tags yet, so this is pinned to a commit — the tip of
        # main, which rewrote the pipeline around --mode and added the BGC
        # route. Replace with a tag once roshab-cli cuts a release; bumping it
        # is a timon release, and the defaults below have to be rechecked.
        "revision": "83c51339c17614783f3f425f4fcd32f1123c3134",
        "profiles": ["docker", "singularity", "apptainer"],
        "file_column": "reads",
        "requires_db": ["kraken_db"],
        # timon's own reference data, shipped or downloaded rather than named
        # by the user — see model.nextflow.REFERENCE_FLAGS.
        "reference_data": ["genomes_db", "genes_db"],
        # Matches assets/schema_input.json at this revision.
        "columns": ["sample_id", "group", "info", "date", "reads"],
        # The `--db_dir` install route is deliberately absent: setting it runs
        # the database download *instead of* an analysis, which is not what
        # this form builds.
        "param_groups": {
            "workflow": "Which screening route the run takes. Taxonomic profiling runs in every mode.",
            "read QC": "Chopper trimming and filtering thresholds.",
            "taxonomic profiling": "Kraken2, Bracken and CoverM options.",
            "read screening": "The `reads` route: cyanotoxin genes called straight off the QC'd reads with DIAMOND.",
            "assembly": "The `assembly` and `both` routes: how the reads are assembled before they are screened.",
            "BGC screening": "Detection of biosynthetic gene clusters in the assembled contigs.",
            "reference databases": "KRAKEN_DB fills the Kraken2 path in at launch; the ones below it are "
                                   "needed only by the steps named. The genome and gene databases are "
                                   "timon's own reference data (TIMON_DB_DIR) and are not asked for here.",
        },
        "params": [
            {"id": "mode", "label": "screening mode", "type": "select", "default": "reads",
             "enum": ["reads", "assembly", "both"], "group": "workflow",
             "description": "Cyanotoxin screening route.",
             "help_text": "`reads` runs `diamond blastx` on the QC reads (minutes). `assembly` assembles the reads "
                          "and screens the contigs for biosynthetic gene clusters (hours, high memory). `both` runs "
                          "the two routes on the same reads."},
            {"id": "skip_qc",       "label": "skip QC",       "type": "bool", "default": False, "group": "workflow",
             "description": "Skip the read QC steps (NanoPlot and Chopper)."},
            {"id": "skip_nanoplot", "label": "skip Nanoplot", "type": "bool", "default": False, "group": "workflow",
             "active_when": {"skip_qc": [False]},
             "description": "Skip the NanoPlot quality assessment but still run Chopper."},

            # Chopper is the whole of this group, so skipping QC empties it.
            {"id": "chopper_headcrop",  "label": "headcrop",              "type": "number", "default": 80,  "min": 0,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Bases trimmed from the start of each read."},
            {"id": "chopper_tailcrop",  "label": "tailcrop",              "type": "number", "default": 50,  "min": 0,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Bases trimmed from the end of each read."},
            {"id": "chopper_minlength", "label": "min. length",           "type": "number", "default": 500, "min": 0,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Minimum read length kept after trimming."},
            {"id": "chopper_minq",      "label": "min. Q-score (Phred)",  "type": "number", "default": 9,   "min": 0, "max": 60,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Minimum average read quality kept."},

            # A fraction the pipeline declares as a float: step "any" keeps
            # 0.05 from being saved back as 0.
            {"id": "kraken_confidence", "label": "Kraken2 confidence", "type": "number", "default": 0.0,
             "min": 0, "max": 1, "step": "any", "group": "taxonomic profiling",
             "description": "Kraken2 confidence score threshold, between 0 and 1.",
             "help_text": "Fraction of a read's k-mers that must map to a taxon's clade for the read to be assigned "
                          "to it. `0` (the default) keeps Kraken2's own behaviour; higher values make classification "
                          "more conservative at the cost of sensitivity."},
            {"id": "bracken_length", "label": "Bracken read length", "type": "number", "default": 300, "min": 1,
             "group": "taxonomic profiling",
             "description": "Read length Bracken was built for, also used as the SeqKit window and step size.",
             "help_text": "Long reads are cut into non-overlapping windows of this length before Kraken2 "
                          "classification, so that the read lengths match the Bracken k-mer distribution."},

            {"id": "diamond_blastx_id", "label": "blastx min. identity (%)", "type": "number", "default": 70,
             "min": 0, "max": 100, "group": "read screening",
             "active_when": {"mode": ["reads", "both"]},
             "description": "Minimum percentage identity of the read-level `diamond blastx` alignments."},

            # The assembly and BGC groups belong to the contig route: the
            # `reads` mode never assembles, so nothing in them is asked for.
            {"id": "assembler", "label": "assembler", "type": "select", "default": "flye",
             "enum": ["flye", "metamdbg"], "group": "assembly",
             "active_when": {"mode": ["assembly", "both"]},
             "description": "Assembler used for the contig-level route."},
            {"id": "min_contig_length", "label": "min. contig length", "type": "number", "default": 1000, "min": 0,
             "group": "assembly", "active_when": {"mode": ["assembly", "both"]},
             "description": "Minimum contig length kept for screening, also passed to antiSMASH as `--minlength`."},
            {"id": "coassemble_by_group", "label": "co-assemble by group", "type": "bool", "default": False,
             "group": "assembly", "active_when": {"mode": ["assembly", "both"]},
             "description": "Co-assemble all the samples of a group instead of one assembly per sample."},

            {"id": "antismash_genefinding", "label": "antiSMASH gene finding", "type": "select", "default": "prodigal-m",
             "enum": ["glimmerhmm", "prodigal", "prodigal-m", "none", "error"], "group": "BGC screening",
             "active_when": {"mode": ["assembly", "both"]},
             "description": "antiSMASH `--genefinding-tool`."},
            {"id": "diamond_blastp_id", "label": "blastp min. identity (%)", "type": "number", "default": 70,
             "min": 0, "max": 100, "group": "BGC screening",
             "active_when": {"mode": ["assembly", "both"]},
             "description": "Minimum percentage identity of the contig-level `diamond blastp` alignments."},
            {"id": "bgc_min_overlap", "label": "BGC min. overlap (bp)", "type": "number", "default": 500, "min": 0,
             "group": "BGC screening", "active_when": {"mode": ["assembly", "both"]},
             "description": "Overlap at which two tools are considered to call the same BGC region.",
             "help_text": "Regions supported by at least two tools after merging are labelled `high` confidence "
                          "in the per-sample `*.bgc.tsv` table."},
            {"id": "run_deepbgc", "label": "run DeepBGC", "type": "bool", "default": False, "group": "BGC screening",
             "active_when": {"mode": ["assembly", "both"]},
             "description": "Add DeepBGC to the antiSMASH + GECCO screening. Needs the DeepBGC models below."},
            {"id": "run_bigscape", "label": "run BiG-SCAPE", "type": "bool", "default": False, "group": "BGC screening",
             "active_when": {"mode": ["assembly", "both"]},
             "description": "Cluster the antiSMASH regions into gene cluster families per group. Needs Pfam-A below."},

            # Databases only some routes read. They are asked for here rather
            # than through requires_db because whether a run needs them
            # follows from the fields above, not from the pipeline choice, and
            # an empty value is simply not passed on the command line. Each is
            # asked for exactly when it is needed, so active_when and
            # required_when say the same thing — the tool that turns one on
            # (DeepBGC, BiG-SCAPE) is itself part of the contig route, which
            # is what keeps its database out of a `reads` run.
            {"id": "antismash_db", "label": "antiSMASH databases", "type": "text", "default": "",
             "placeholder": "/path/to/antismash_db", "path": "any", "group": "reference databases",
             "active_when": {"mode": ["assembly", "both"]},
             "required_when": {"mode": ["assembly", "both"]},
             "description": "Required with screening mode `assembly` or `both`.",
             "help_text": "A directory or a `.tar.gz` tarball, created with `download-antismash-databases` "
                          "from the antiSMASH distribution."},
            {"id": "deepbgc_db", "label": "DeepBGC models", "type": "text", "default": "",
             "placeholder": "/path/to/deepbgc_db", "path": "any", "group": "reference databases",
             "active_when": {"run_deepbgc": [True]},
             "required_when": {"run_deepbgc": [True]},
             "description": "Required with 'run DeepBGC'. A directory or a `.tar.gz` tarball."},
            {"id": "pfam_db", "label": "Pfam-A HMM", "type": "text", "default": "",
             "placeholder": "/path/to/Pfam-A.hmm", "path": "file", "group": "reference databases",
             "active_when": {"run_bigscape": [True]},
             "required_when": {"run_bigscape": [True]},
             "description": "Required with 'run BiG-SCAPE'."},
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
        # check the defaults below against it. Moved up from the PR #8 merge
        # for the Medaka guard: from here on the pipeline refuses a run that
        # names --medaka_model or --skip_medaka with any assembler but flye,
        # which is what the active_when on those two keeps off the command
        # line. No parameter default moved with it.
        "revision": "d1f03a1d271744788a5660603fdd65c034169e48",
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
            "assembly": "How the long reads are assembled, and — with Flye — polished.",
            "binning":  "Which binners run, and how they are configured.",
            "bin QC & reporting": "Quality assessment and classification of the recovered bins, and the run report.",
            "reference databases": "GTDBTK_DB fills this in at launch. A run that skips GTDB-Tk, or bin QA "
                                   "altogether, never reads it, and this section empties out.",
        },
        "params": [
            # "skip QC" is the switch for the whole group: with it set, the
            # thresholds and the per-tool skips below are all moot.
            {"id": "chopper_minlength", "label": "min. length",           "type": "number", "default": 1000, "min": 0,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Minimum read length kept by Chopper."},
            {"id": "chopper_minq",      "label": "min. Q-score (Phred)",  "type": "number", "default": 10,   "min": 0, "max": 60,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Minimum average read quality kept by Chopper."},
            {"id": "skip_qc",           "label": "skip QC",               "type": "bool",   "default": False, "group": "read QC",
             "description": "Skip long read quality control entirely."},
            {"id": "skip_nanoplot",     "label": "skip Nanoplot",         "type": "bool",   "default": False, "group": "read QC",
             "active_when": {"skip_qc": [False]},
             "description": "Skip NanoPlot read quality reports."},
            {"id": "skip_porechop",     "label": "skip Porechop",         "type": "bool",   "default": False, "group": "read QC",
             "active_when": {"skip_qc": [False]},
             "description": "Skip Porechop_ABI adapter removal."},

            {"id": "assembler",     "label": "assembler",   "type": "select", "default": "flye",
             "enum": ["flye", "metamdbg"], "group": "assembly",
             "description": "Long read assembler to use."},
            # Medaka polishes Flye assemblies only — metaMDBG produces a
            # consensus of its own — and the pipeline refuses a run that names
            # either Medaka parameter with any other assembler rather than
            # ignoring it. So both leave the form with `flye`, which is also
            # what keeps them off the command line. The model is asked for on
            # top of that only by a run that actually polishes.
            {"id": "medaka_model",  "label": "Medaka model", "type": "text",  "default": "r1041_e82_400bps_hac_v5.2.0",
             "group": "assembly", "required": True,
             "active_when": {"assembler": ["flye"], "skip_medaka": [False]},
             "description": "Medaka model used to polish the assembly.",
             "help_text": "Must match the flow cell, kit and basecaller used to produce the reads. "
                          "Run `medaka tools list_models` to see the models available in the container."},
            {"id": "skip_medaka",   "label": "skip Medaka",  "type": "bool",  "default": False, "group": "assembly",
             "active_when": {"assembler": ["flye"]},
             "description": "Skip Medaka polishing of the assembly."},

            # Read by the MAXBIN process alone (conf/modules.config), so it
            # goes with the binner.
            {"id": "maxbin_minlen",  "label": "MaxBin2 min. contig length", "type": "number", "default": 2500, "min": 0,
             "group": "binning", "active_when": {"skip_maxbin": [False]},
             "description": "Minimum contig length considered by MaxBin2."},
            # The single-contig MAG hold-out is decided by CheckM2, so the
            # whole of it sits under "skip bin QA" in the pipeline (main.nf).
            {"id": "sc_mag_minimum", "label": "single-contig MAG length",   "type": "number", "default": 500000, "min": 0,
             "group": "binning", "active_when": {"skip_bin_qa": [False]},
             "description": "Contigs at least this long are assessed on their own as candidate single-contig MAGs."},
            # A percentage the pipeline declares as a float: step "any" keeps
            # 92.5 from being saved back as 92.
            {"id": "sc_mag_min_completeness", "label": "single-contig MAG min. completeness (%)", "type": "number",
             "default": 90, "min": 0, "max": 100, "step": "any", "group": "binning",
             "active_when": {"skip_bin_qa": [False]},
             "description": "CheckM2 completeness a long contig must reach to be held out of binning "
                            "and kept as a single-contig MAG."},
            {"id": "skip_maxbin",  "label": "skip MaxBin2",  "type": "bool", "default": False, "group": "binning",
             "description": "Skip binning with MaxBin2."},
            {"id": "skip_concoct", "label": "skip CONCOCT",  "type": "bool", "default": False, "group": "binning",
             "description": "Skip binning with CONCOCT."},
            {"id": "skip_semibin", "label": "skip SemiBin2", "type": "bool", "default": False, "group": "binning",
             "description": "Skip binning with SemiBin2."},

            {"id": "skip_bin_qa", "label": "skip bin QA",  "type": "bool", "default": False, "group": "bin QC & reporting",
             "description": "Skip CheckM2, GTDB-Tk and the MAG summary."},
            # Under "skip bin QA", which already takes GTDB-Tk with it — and
            # with it goes gtdbtk_db, through "db_optional_when" above.
            {"id": "skip_gtdbtk", "label": "skip GTDB-Tk", "type": "bool", "default": False, "group": "bin QC & reporting",
             "active_when": {"skip_bin_qa": [False]},
             "description": "Skip taxonomic classification with GTDB-Tk."},
            {"id": "skip_multiqc", "label": "skip MultiQC", "type": "bool", "default": False, "group": "bin QC & reporting",
             "description": "Skip the MultiQC report."},
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
            {"id": "skip_porechop",    "label": "skip Porechop",           "type": "bool",   "default": False,
             "active_when": {"skip_qc": [False]}},
            {"id": "chopper_minq",     "label": "min. Q-score (Phred)",    "type": "number", "default": 10,   "min": 1, "max": 60,
             "active_when": {"skip_qc": [False]}},
            {"id": "chopper_minlength","label": "min. length",             "type": "number", "default": 1000, "min": 0, "max": 10000,
             "active_when": {"skip_qc": [False]}},
        ]
    }
}
