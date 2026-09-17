import os
import secrets

class Config:
    SECRET_KEY    = os.getenv("TIMON_SECRET_KEY") or secrets.token_hex(32)
    IMPORT_FOLDER = os.getenv("INPUT_DIR",  "imports")
    # Where runs write, which is deliberately not where the reads are: a
    # folder called "imports" holding the results of an analysis is a folder
    # nobody can read the layout of. Everything of timon's own that a run
    # needs and nobody asked for — nextflow's work directory, the resource
    # ceiling, the sample sheet — goes in here under a leading dot, so what
    # the results view walks is the runs themselves.
    OUTPUT_FOLDER = os.getenv("OUTPUT_DIR", "timon_results")
    # Container engine Nextflow provisions tasks with. Every pipeline declares
    # which of these it supports; see "profiles" below.
    PROFILE       = os.getenv("TIMON_PROFILE", "docker")

# ── reference databases ──────────────────────────────────────────────────────
#
# Every database a pipeline reads is timon's to find: timon.paths.REFERENCE_DATA
# says where each one is (db_root(), unless its environment variable names a
# copy elsewhere), and a pipeline entry only lists which it reads under
# "reference_data". Nothing is asked for in the form — one database, one place,
# whichever pipeline reads it.
#
# A database timon cannot find is the commonest thing between a fresh install
# and a first run, and the fix is always the same act: fetch a large file and
# leave it where timon looks. So where each one can be got is declared here,
# and model/downloads.py is the one place that carries a download out.
#
# Keyed by the database, a key of timon.paths.REFERENCE_DATA. A database with
# no entry is still reported missing; it is simply not something the button can
# fetch.
#
#   label        what the page calls the download
#   size         how large it is. Someone deciding whether to start one at all
#                is deciding on this number, so it is written by hand from the
#                publisher's own page — a HEAD request would report it only
#                after the user had committed to asking
#   url          what is fetched, over https
#   archive      True for a `.tar.gz` unpacked once it has landed; False for a
#                file that is used exactly as it arrives
#   install_as   the name it takes under timon.paths.db_root(). It *must* be
#                one of the names paths.py looks for, or the download would
#                land somewhere timon never looks (tests/test_config.py)
#   description  one line: what is in it and what it is enough for
#
# Optional, and only where the publisher offers the same database in more than
# one build:
#
#   variants     the builds, each its own source. A variant carries "id" and
#                whatever it changes — url, size, install_as, label, note — and
#                inherits the rest from the entry around it, so what the builds
#                share is written once. The page offers them as a choice and
#                sends back an id; ``default`` names the one chosen for a user
#                who expresses no preference, and the bundle button fetches
#                that one
#   default      the id of that default variant
#
# A database published one way declares neither, and is its own single variant
# — model/downloads.py normalises both shapes to the same thing, so nothing
# past it has two to reason about.
DB_SOURCES = {
    # As published at https://benlangmead.github.io/aws-indexes/k2. Dated
    # builds: the date is part of the URL and of the name each is installed
    # under, so a newer index is a new variant beside these rather than a
    # silent change. Sizes in GiB, as the publisher's page gives them; both
    # variants are kept on the same date, since which of the two someone
    # picked should not also decide how current their index is.
    "kraken_db": {
        "label": "Kraken2 PlusPF",
        "archive": True,
        "description": "Archaea, bacteria, viruses, plasmids, human, vectors, "
                       "protozoa and fungi.",
        # Two builds of the same collection, from the same date. The cap is
        # how much memory Kraken2 needs to hold the index while it classifies,
        # so this is a choice about the machine and not about the analysis: a
        # laptop with 8 GB cannot run the larger one at all, and the smaller
        # one is more heavily hashed, so it classifies a little less. Which
        # was installed is not recorded anywhere and no run reads it — both
        # land under a name paths.py looks for, and a Kraken2 index is a
        # Kraken2 index to the pipeline.
        "default": "16GB",
        "variants": [
            {
                "id": "16GB",
                "label": "Kraken2 PlusPF-16",
                "size": "11.1 GB",
                "url": "https://genome-idx.s3.amazonaws.com/kraken/k2_pluspf_16_GB_20260626.tar.gz",
                "install_as": "k2_pluspf_16_GB_20260626",
                "note": "needs 16 GB of memory to classify with",
            },
            {
                "id": "8GB",
                "label": "Kraken2 PlusPF-8",
                "size": "5.5 GB",
                "url": "https://genome-idx.s3.amazonaws.com/kraken/k2_pluspf_08_GB_20260626.tar.gz",
                "install_as": "k2_pluspf_08_GB_20260626",
                "note": "same organisms, hashed down to 8 GB — for a machine "
                        "that cannot spare 16",
            },
        ],
    },
    # One package, and the project publishes it as "latest" rather than per
    # release: GTDB-Tk checks the data version it is given at startup, so the
    # pipeline's own image decides what it will accept.
    "gtdbtk_db": {
        "label": "GTDB-Tk reference data",
        "size": "~100 GB",
        "url": "https://data.ace.uq.edu.au/public/gtdb/data/releases/latest/"
               "auxillary_files/gtdbtk_package/full_package/gtdbtk_data.tar.gz",
        "archive": True,
        "install_as": "gtdbtk_data",
        "description": "The full package, which is the only one GTDB-Tk classify "
                       "takes. Allow for a long download and twice the space "
                       "while it unpacks.",
    },
    # timon's own: 220 dereplicated cyanobacterial genomes, published on
    # Zenodo under a record that names this exact set, so the URL is as fixed
    # as a dated Kraken2 build. The tarball wraps them in one directory, which
    # is unwrapped on install — CoverM is handed the directory and names each
    # genome after its file, so what it reads is the .fna files themselves.
    "genomes_db": {
        "label": "cyanobacterial genome set",
        "size": "278 MB",
        "url": "https://zenodo.org/records/19522349/files/"
               "cyanobacteriota_ncbi_dRep_n220.tar.gz",
        "archive": True,
        "install_as": "cyanobacteriota_ncbi_dRep_n220",
        "description": "220 dereplicated cyanobacterial genomes, which CoverM "
                       "maps the reads against. Any set of FASTA files is a "
                       "valid answer, so TIMON_GENOMES_DB can name a smaller one.",
    },
}

# What the **install databases** button fetches: installed once on a machine
# and read by every run after. A run that reads one of them cannot start until
# it is there, so the button is the first thing a fresh install offers and is
# frozen once there is nothing left for it to do.
#
# GTDB-Tk is deliberately not in it. At ~100 GB it would make every install
# pay for a step only mag-ont's bin QA takes, and a run that skips that step
# never reads it; it is offered on its own, and only to a run that needs it.
DATABASE_BUNDLE = ["kraken_db", "genomes_db"]

# ── linked pipelines ─────────────────────────────────────────────────────────
#
# Each entry links a Nextflow pipeline to timon. Required keys:
#
#   name, description, icon   what the workflow card shows
#   pipeline                  GitHub "owner/repo", passed to `nextflow run`
#   revision                  the release tag the run is pinned to — a tag, never
#                             a branch or a bare commit, so what a run used has a
#                             name upstream (tests/test_config.py holds that).
#                             None refuses to run (see model.nextflow.build_command)
#   profiles                  container engines the pipeline supports
#   columns, file_column      sample-sheet columns, and which one holds reads
#   reference_data            the databases the pipeline reads, by the keys of
#                             timon.paths.REFERENCE_DATA, each passed under its
#                             flag in model.nextflow.REFERENCE_FLAGS. Never
#                             asked for: timon knows where they are, and a run
#                             that reads a missing one cannot start. So they
#                             are never declared in "params" either — that
#                             would be a second source
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
#                 revision, or the form will lie about what a run does.
#                 None, for a number, is a pipeline that sets no value of its
#                 own: the field may be left empty and nothing is passed
#   description   one line under the field
#   help_text     the part that actually decides a value; disclosed on demand
#   min/max/step  numbers only. step "any" means the value is a float, not an
#                 integer, and is cast as one (see model.params.coerce)
#   enum          selects only: the whole set of accepted values
#   options_from  selects only, instead of enum: the options are what an
#                 installed database holds, read by the reader of that name in
#                 timon.paths.DATABASE_OPTIONS. Until the database can be
#                 looked into, the default is the only option
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
#   required_columns  sample-sheet columns that must be filled on every row.
#                     Defaults to *all* of "columns". Declared only where the
#                     pipeline's own assets/schema_input.json asks for less:
#                     a column timon insists on that the pipeline treats as
#                     optional locks the user out of a sheet the pipeline
#                     would have accepted — a nanopore run with no short reads
#                     beside it, say
#   one_of_columns    groups of columns of which at least one must be filled on
#                     each row, for a schema's "anyOf" — a row needing either
#                     reads to assemble or an assembly already made
#   param_groups      {group: blurb} for the section headings used by "params"
#   db_optional_when  {db key: [flags]} — a database under "reference_data"
#                     that is only read while none of those flags is set: not
#                     passed, and not missing, for a run that skips its step
#   test_profile      the pipeline's own smoke-test profile, launched as
#                     `-profile <test_profile>,<engine>` by the quick test
#                     button. Declared only for a pipeline whose test profile
#                     fetches its own reads and its own databases: timon hands
#                     it no sample sheet, no parameters and no database, so a
#                     profile expecting any of them would fail at once. A
#                     pipeline without this key is offered no quick test
#   selectable        False leaves a declared pipeline out of the workflow
#                     picker, and refuses a switch to it. For one written down
#                     before it can be run — the entry stays, so nothing has to
#                     be reconstructed when it can
PIPELINES = {
    "roshab-cli": {
        "name": "roshab-cli",
        "description": "Taxonomic classification and evaluation of cyanotoxin biosynthesis potential from nanopore reads",
        "icon": "img/bloom_orig.png",
        "pipeline": "dsamoht/roshab-cli",
        # The first release. Bumping it is a timon release, and the defaults
        # below have to be rechecked against that tag's nextflow_schema.json.
        "revision": "v0.1.0",
        "profiles": ["docker", "singularity", "apptainer"],
        # conf/test.config at this revision names its own sample sheet and
        # every database it reads — the viral Kraken2 index by URL, the CoverM
        # genomes and the gene database from the pipeline itself — so
        # the quick test needs nothing from the form. It checks the install
        # rather than a configuration, and what it downloads is the same
        # 569 MB index the roshab-cli example run asks the user for.
        "test_profile": "test",
        "file_column": "reads",
        # Found by timon and installed by the install databases button — see
        # timon.paths.REFERENCE_DATA. Not the gene database:
        # from v0.1.0 the pipeline ships its own (assets/cyanotoxin_genes_
        # mibig-4.0_two-class_v2.faa), whose sixth header field tells toxin
        # genes from the rest, and the reports are written against that panel.
        "reference_data": ["kraken_db", "genomes_db"],
        # Matches assets/schema_input.json at this revision, which requires
        # every one of them — so no "required_columns" here.
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
            "reference databases": "Needed only by the steps named. Kraken2 and the genome database are "
                                   "timon's own — installed once, from the databases card — and the gene "
                                   "database ships with the pipeline, so none of them is asked for here.",
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
            #
            # Every number declares both bounds (tests/test_config.py insists).
            # Where the pipeline sets none, "max" is timon's own ceiling on what
            # a typo can send: generous past any real run, short of absurd.
            {"id": "chopper_headcrop",  "label": "headcrop",              "type": "number", "default": 80,  "min": 0, "max": 10000,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Bases trimmed from the start of each read."},
            {"id": "chopper_tailcrop",  "label": "tailcrop",              "type": "number", "default": 50,  "min": 0, "max": 10000,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Bases trimmed from the end of each read."},
            {"id": "chopper_minlength", "label": "min. length",           "type": "number", "default": 500, "min": 1, "max": 1000000,
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
            # Only a length the installed Kraken2 index has a distribution
            # for is a length Bracken can run with, so the options are read
            # off the index (timon.paths.DATABASE_OPTIONS) and not written here.
            {"id": "bracken_length", "label": "Bracken read length", "type": "select", "default": "300",
             "options_from": "bracken_lengths", "group": "taxonomic profiling",
             "description": "Read length Bracken was built for, also used as the SeqKit window and step size.",
             "help_text": "Long reads are cut into non-overlapping windows of this length before Kraken2 "
                          "classification, so that the read lengths match the Bracken k-mer distribution."},

            {"id": "diamond_blastx_id", "label": "blastx min. identity (%)", "type": "number", "default": 70,
             "min": 0, "max": 100, "group": "read screening",
             "active_when": {"mode": ["reads", "both"]},
             "description": "Minimum percentage identity of the read-level `diamond blastx` alignments."},
            # Both read by PLOT_GENE_DIAMOND_READS alone (conf/modules.config),
            # so they go with the read route.
            {"id": "diamond_min_aln_length", "label": "min. alignment length (aa)", "type": "number", "default": 25,
             "min": 1, "max": 10000, "group": "read screening", "active_when": {"mode": ["reads", "both"]},
             "description": "Minimum alignment length kept when summarising the DIAMOND hits.",
             "help_text": "A short alignment over a conserved NRPS/PKS domain is not diagnostic on its own: 25 aa "
                          "is roughly the span of a single adenylation-domain core motif, shared across "
                          "essentially every NRPS."},
            # A fraction the pipeline declares as a float, as kraken_confidence.
            {"id": "diamond_range_overlap_frac", "label": "range overlap fraction", "type": "number", "default": 0.5,
             "min": 0, "max": 1, "step": "any", "group": "read screening",
             "active_when": {"mode": ["reads", "both"]},
             "description": "Overlap at which two alignments on one read count as the same gene.",
             "help_text": "One long read yields several alignments along different segments. Alignments "
                          "overlapping by at least this fraction of the shorter one compete for the same range "
                          "and only the best-scoring is counted; the rest count as separate gene occurrences."},

            # The assembly and BGC groups belong to the contig route: the
            # `reads` mode never assembles, so nothing in them is asked for.
            {"id": "assembler", "label": "assembler", "type": "select", "default": "flye",
             "enum": ["flye", "metamdbg"], "group": "assembly",
             "active_when": {"mode": ["assembly", "both"]},
             "description": "Assembler used for the contig-level route."},
            # Each passed to its own assembler only (conf/modules.config), and
            # typically starts with a dash — build_command joins such a value
            # to its flag so nextflow does not read it as a flag of its own.
            {"id": "flye_args", "label": "extra Flye arguments", "type": "text", "default": "",
             "placeholder": "e.g. --iterations 2", "group": "assembly",
             "active_when": {"mode": ["assembly", "both"], "assembler": ["flye"]},
             "description": "Added to `flye`, after the `--meta` the pipeline always passes."},
            {"id": "metamdbg_args", "label": "extra metaMDBG arguments", "type": "text", "default": "",
             "placeholder": "e.g. --min-read-quality 12", "group": "assembly",
             "active_when": {"mode": ["assembly", "both"], "assembler": ["metamdbg"]},
             "description": "Added to `metaMDBG asm`."},
            # No default of its own: unset, the heavy steps keep the
            # process_high label's CPUs.
            {"id": "assembly_cpus", "label": "assembly CPUs", "type": "number", "default": None, "min": 1, "max": 1024,
             "group": "assembly", "active_when": {"mode": ["assembly", "both"]},
             "description": "CPUs given to the assembly and antiSMASH steps. Leave empty for the pipeline's own.",
             "help_text": "Overrides the `process_high` CPU default for Flye, metaMDBG and antiSMASH. Memory and "
                          "time still come from that label."},
            {"id": "min_contig_length", "label": "min. contig length", "type": "number", "default": 1000, "min": 1, "max": 10000000,
             "group": "assembly", "active_when": {"mode": ["assembly", "both"]},
             "description": "Minimum contig length kept for screening, also passed to antiSMASH as `--minlength`."},
            {"id": "coassemble_by_group", "label": "co-assemble by group", "type": "bool", "default": False,
             "group": "assembly", "active_when": {"mode": ["assembly", "both"]},
             "description": "Co-assemble all the samples of a group instead of one assembly per sample."},

            {"id": "antismash_genefinding", "label": "antiSMASH gene finding", "type": "select", "default": "prodigal-m",
             "enum": ["glimmerhmm", "prodigal", "prodigal-m", "none", "error"], "group": "BGC screening",
             "active_when": {"mode": ["assembly", "both"]},
             "description": "antiSMASH `--genefinding-tool`."},
            # v0.1.0 took the BGC route down to antiSMASH alone: DIAMOND
            # blastp, GECCO, DeepBGC, BiG-SCAPE and the merge between them are
            # gone, and so are their parameters and databases.

            # A database only the contig route reads. Asked for here rather
            # than through reference_data because whether a run needs it follows
            # from the mode, not from the pipeline choice, and an empty value
            # is simply not passed on the command line. active_when and
            # required_when say the same thing: it is asked for exactly when
            # it is read.
            {"id": "antismash_db", "label": "antiSMASH databases", "type": "text", "default": "",
             "placeholder": "/path/to/antismash_db", "path": "any", "group": "reference databases",
             "active_when": {"mode": ["assembly", "both"]},
             "required_when": {"mode": ["assembly", "both"]},
             "description": "Required with screening mode `assembly` or `both`.",
             "help_text": "A directory or a `.tar.gz` tarball, created with `download-antismash-databases` "
                          "from the antiSMASH distribution."},
        ]
    },
    "mag-ont": {
        "name": "mag-ont",
        "description": "Automation of metagenome assembly and binning with support for nanopore reads",
        "icon": "img/mag-icon.png",
        "pipeline": "dsamoht/mag-ont",
        # The nf-core template release. Bumping it is a timon release, and the
        # defaults below have to be rechecked against that tag's
        # nextflow_schema.json. The pipeline refuses a run that names
        # --medaka_model or --skip_medaka with any assembler but flye, which
        # is what the active_when on those two keeps off the command line.
        "revision": "v1.4.0",
        # As declared by the tag's nextflow.config. "debug", "gpu", "drac" and the
        # test profiles are omitted: they are not container engines.
        "profiles": ["docker", "singularity", "apptainer", "podman",
                     "shifter", "charliecloud", "wave", "conda", "mamba"],
        "file_column": "long_reads",
        "reference_data": ["gtdbtk_db"],
        # The pipeline's own rule for gtdbtk_db: required unless --skip_gtdbtk
        # is set. Demanding it from a run that skips the step it feeds would
        # lock the user out of a configuration the pipeline accepts.
        # --only_qc stops before binning, so nothing reads it then either.
        "db_optional_when": {"gtdbtk_db": ["skip_gtdbtk", "skip_bin_qa", "only_qc"]},
        # Matches assets/schema_input.json at this revision, which requires
        # only the two identifiers and then either something to assemble or
        # something already assembled. Short reads are an optional extra used
        # for binning coverage, so a long-read-only sheet — the ordinary
        # nanopore case — has to be accepted.
        "columns": ["sample_id", "group", "assembly_fasta", "long_reads", "short_reads_1", "short_reads_2"],
        "required_columns": ["sample_id", "group"],
        "one_of_columns": [["assembly_fasta", "long_reads"]],
        "param_groups": {
            "read QC":  "Quality control and filtering of the long reads.",
            "assembly": "How the long reads are assembled, and — with Flye — polished.",
            "binning":  "Which binners run, and how they are configured.",
            "bin QC & reporting": "Quality assessment and classification of the recovered bins, and the run report. "
                                  "GTDB-Tk reads timon's own copy of its database; skipping it, or bin QA, "
                                  "means the database is not needed at all.",
        },
        "params": [
            # "skip QC" is the switch for the whole group: with it set, the
            # thresholds and the per-tool skips below are all moot.
            {"id": "chopper_minlength", "label": "min. length",           "type": "number", "default": 1000, "min": 0, "max": 1000000,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Minimum read length kept by Chopper."},
            {"id": "chopper_minq",      "label": "min. Q-score (Phred)",  "type": "number", "default": 10,   "min": 0, "max": 60,
             "group": "read QC", "active_when": {"skip_qc": [False]},
             "description": "Minimum average read quality kept by Chopper."},
            {"id": "skip_qc",           "label": "skip QC",               "type": "bool",   "default": False, "group": "read QC",
             "description": "Skip long read quality control entirely."},
            # The switch for everything *after* QC. Not made to hang off
            # "skip QC", though the pipeline refuses the two together: a
            # condition that drops takes whatever hangs off it along, and
            # every assembly and binning field hangs off this one — so
            # ticking "skip QC" would silently take the rest of the run with
            # it. The pipeline says so at startup instead.
            {"id": "only_qc",           "label": "only QC",               "type": "bool",   "default": False, "group": "read QC",
             "description": "Stop after read QC: no assembly, binning or bin QA. Cannot be combined with skip QC.",
             "help_text": "Runs NanoPlot, Porechop_ABI and Chopper, and publishes the QC'd reads and the MultiQC "
                          "report. Samples that come with their own assembly skip read QC, so nothing runs for them."},
            {"id": "skip_nanoplot",     "label": "skip Nanoplot",         "type": "bool",   "default": False, "group": "read QC",
             "active_when": {"skip_qc": [False]},
             "description": "Skip NanoPlot read quality reports."},
            {"id": "skip_porechop",     "label": "skip Porechop",         "type": "bool",   "default": False, "group": "read QC",
             "active_when": {"skip_qc": [False]},
             "description": "Skip Porechop_ABI adapter removal."},

            {"id": "assembler",     "label": "assembler",   "type": "select", "default": "flye",
             "enum": ["flye", "metamdbg"], "active_when": {"only_qc": [False]}, "group": "assembly",
             "description": "Long read assembler to use."},
            # Medaka polishes Flye assemblies only — metaMDBG produces a
            # consensus of its own — and the pipeline refuses a run that names
            # either Medaka parameter with any other assembler rather than
            # ignoring it. So both leave the form with `flye`, which is also
            # what keeps them off the command line. The model is asked for on
            # top of that only by a run that actually polishes.
            {"id": "medaka_model",  "label": "Medaka model", "type": "text",  "default": "r1041_e82_400bps_hac_v5.2.0",
             "group": "assembly", "required": True,
             "active_when": {"only_qc": [False], "assembler": ["flye"], "skip_medaka": [False]},
             "description": "Medaka model used to polish the assembly.",
             "help_text": "Only used once 'skip Medaka' is unticked. Must match the flow cell, kit and basecaller used to produce the reads. "
                          "Run `medaka tools list_models` to see the models available in the container."},
            # Skipped by default from v1.4.0: Medaka is a haploid consensus
            # model, and on a co-assembly it can rewrite a low-coverage genome
            # with the sequence of a high-coverage relative.
            {"id": "skip_medaka",   "label": "skip Medaka",  "type": "bool",  "default": True, "group": "assembly",
             "active_when": {"only_qc": [False], "assembler": ["flye"]},
             "description": "Skip Medaka polishing of the assembly.",
             "help_text": "On by default: Medaka is a haploid consensus model, and on a co-assembly it can "
                          "rewrite a low-coverage genome with the sequence of a high-coverage relative. Untick "
                          "to polish anyway, with a Medaka model that matches the basecaller."},

            # Read by the MAXBIN process alone (conf/modules.config), so it
            # goes with the binner.
            {"id": "maxbin_minlen",  "label": "MaxBin2 min. contig length", "type": "number", "default": 2500, "min": 0, "max": 10000000,
             "group": "binning", "active_when": {"only_qc": [False], "skip_maxbin": [False]},
             "description": "Minimum contig length considered by MaxBin2."},
            # The single-contig MAG hold-out is decided by CheckM2, so the
            # whole of it sits under "skip bin QA" in the pipeline (main.nf).
            {"id": "sc_mag_minimum", "label": "single-contig MAG length",   "type": "number", "default": 500000, "min": 0, "max": 100000000,
             "group": "binning", "active_when": {"only_qc": [False], "skip_bin_qa": [False]},
             "description": "Contigs at least this long are assessed on their own as candidate single-contig MAGs."},
            # A percentage the pipeline declares as a float: step "any" keeps
            # 92.5 from being saved back as 92.
            {"id": "sc_mag_min_completeness", "label": "single-contig MAG min. completeness (%)", "type": "number",
             "default": 90, "min": 0, "max": 100, "step": "any", "group": "binning",
             "active_when": {"only_qc": [False], "skip_bin_qa": [False]},
             "description": "CheckM2 completeness a long contig must reach to be held out of binning "
                            "and kept as a single-contig MAG."},
            # Co-binning across groups. Its rules — one read type for the
            # whole run, sample ids unique across it — are the pipeline's to
            # enforce, and it does so before anything is submitted.
            {"id": "binning_map_mode", "label": "coverage mapping", "type": "select", "default": "group",
             "enum": ["group", "all"], "group": "binning", "active_when": {"only_qc": [False]},
             "description": "`group` maps a group's own samples against its assembly; `all` maps every sample "
                            "of the run against every assembly.",
             "help_text": "With `all`, each binning run sees one coverage column per sample of the run instead of "
                          "one per sample of the group, which gives the binners a differential coverage signal even "
                          "for a group holding a single sample. It costs one mapping job per assembly and per "
                          "sample, and every group of the run has to use the same read type."},
            {"id": "skip_maxbin",  "label": "skip MaxBin2",  "type": "bool", "default": False, "active_when": {"only_qc": [False]}, "group": "binning",
             "description": "Skip binning with MaxBin2."},
            {"id": "skip_concoct", "label": "skip CONCOCT",  "type": "bool", "default": False, "active_when": {"only_qc": [False]}, "group": "binning",
             "description": "Skip binning with CONCOCT."},
            {"id": "skip_semibin", "label": "skip SemiBin2", "type": "bool", "default": False, "active_when": {"only_qc": [False]}, "group": "binning",
             "description": "Skip binning with SemiBin2."},

            {"id": "skip_bin_qa", "label": "skip bin QA",  "type": "bool", "default": False, "active_when": {"only_qc": [False]}, "group": "bin QC & reporting",
             "description": "Skip CheckM2, GTDB-Tk and the MAG summary."},
            # Under "skip bin QA", which already takes GTDB-Tk with it — and
            # with it goes gtdbtk_db, through "db_optional_when" above.
            {"id": "skip_gtdbtk", "label": "skip GTDB-Tk", "type": "bool", "default": False, "group": "bin QC & reporting",
             "active_when": {"only_qc": [False], "skip_bin_qa": [False]},
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
        # and a revision is pinned here. Until then it is not offered either:
        # a card whose only answer is a refusal is worse than no card, and the
        # entry is kept so that publishing the pipeline is a revision and a
        # flag rather than a rewrite.
        "revision": None,
        "selectable": False,
        "profiles": ["docker", "singularity", "apptainer"],
        "file_column": "long_reads",
        "reference_data": [],
        "columns": ["sample_id", "long_reads", "short_reads_1", "short_reads_2"],
        # Short reads are what makes the assembly a consensus one, but the
        # pipeline also runs without them.
        "required_columns": ["sample_id", "long_reads"],
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
