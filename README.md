# timon

**t**oolkit of **i**ntegrated **m**icrobi**o**me analysis with support for lo**n**g reads.

timon is a local web app that prepares and launches Nextflow pipelines microbiome analysis. It works like a Jupyter notebook: you install it
once, `cd` into the folder you want to work in, and run `timon`.

```console
$ pip install git+https://github.com/dsamoht/timon
$ cd ~/projects/bloom_survey
$ timon
timon 0.1.0 → http://127.0.0.1:54123   (Ctrl-C to quit)
```

A browser opens on the app. The folder you launched from is the workspace:
inputs are found there, and each run writes its results back into it.

## Try it first

A new install can be checked before any real data goes near it. Select
**roshab-cli** and press **quick test**, beside the workflow picker — no
sample sheet, no parameters, no databases to install first.

It runs the pipeline's own test profile, which fetches the reads and every
database it reads, so what is exercised is the whole chain: Nextflow, your
container engine, the live console and the results view. It downloads a few
hundred megabytes the first time and takes a few minutes.

**The results mean nothing** — it is the pipeline's smoke test, not an
analysis. It answers whether the install works, which is worth knowing before
there is a configuration to blame. It writes to `timon_results/roshab-cli_test/`,
never on top of a run of yours, and is not listed among your past runs —
delete that folder when you are done.

Only roshab-cli offers this for now; a pipeline gets the button by declaring a
`test_profile` in `src/timon/app/config.py`.

## Requirements

- Python ≥ 3.10
- [Nextflow](https://www.nextflow.io/) on your `PATH` — **not** a Python
  dependency, so `pip install` does not provide it. The app starts without it
  and says so; runs stay disabled until it is installed.
- A container engine Nextflow can use (Docker by default; Singularity,
  Apptainer, Podman and others are supported per pipeline).

## Install

**pip** — the app and its Python dependencies:

```console
pip install git+https://github.com/dsamoht/timon      # or: pip install .
```

Install Nextflow separately, e.g. `conda install -c bioconda nextflow`.

**conda** — the app plus Nextflow and the bioinformatics toolchain:

```console
conda env create -f environment.yaml
conda activate timon_v0.1.0
```

**From a checkout**, without installing anything yourself: `./run.sh` builds a
virtualenv holding an editable install and starts the app, passing every
argument through to `timon`.

## Using it

```console
timon                 # open a browser on a free loopback port
timon --port 8000     # fixed port
timon --no-browser    # for use behind an SSH tunnel
timon --host 0.0.0.0  # bind beyond loopback (see below)
```

The page walks through four steps:

1. **Select workflow** — the pipelines timon knows about, each pinned to a
   release tag so a run can be reproduced.
2. **Run configuration** — a run identifier and the pipeline parameters worth
   changing. Anything not shown keeps the pipeline's own default.
3. **Sample sheet** — one row per sample. `scan folder` fills it from the input
   folder (`imports/` by default, relative to where you launched timon), and any
   column holding a path has a browse button beside it. timon never writes
   there — that folder is yours.
4. **Execution console** — the Nextflow output, streamed live, with a stop
   button.

Two more views sit beside it in the sidebar: **runs**, every run this folder
remembers, and **results**, what they wrote.

### Picking a run up again

A run is remembered as the folder it wrote plus a small note inside it, so the
**runs** view is simply what is on disk — delete a run's folder and it leaves
the list with it. Each row says how the run ended and how long it took, and
opens either its outputs or its configuration.

Reopening a run puts its whole configuration back in the form: the pipeline,
the parameters, the databases and the sample sheet. That is how a run that
failed is fixed and started again — correct what was wrong and press run. If
something about it no longer holds (a database on a drive that is not mounted,
reads that have been tidied away) it is loaded anyway, with the reasons listed
under the form.

Running an identifier that already names a run **continues it**: Nextflow is
given `-resume`, so every step your fix did not touch is taken from its cache
instead of being computed again. The form says so, and a checkbox there starts
the run over instead. Continuing only works in the directory the first run was
launched from, since that is where Nextflow keeps the cache — timon does not
offer it anywhere else.

### Finding input files

The browse button opens a file browser rooted at the folder timon was launched
in. Picking several files from one directory collapses them into a single
wildcard, which is what the pipelines expect for a barcode's worth of reads.

Reads often live somewhere else entirely — an external drive, a shared folder
above the analysis directory — so the browser can leave the workspace, but only
after you allow it: navigating above the launch directory asks first, and the
permission lasts until timon is closed. The rule is enforced by the server, not
the page, and only file names, sizes and dates are ever listed — timon never
reads a file's contents to show it to you.

### Reference databases

A pipeline reads reference data that is far too large to ship with timon, so
the first card on the page is **Reference databases**, with one **install
databases** button. It fetches a Kraken2 PlusPF index and the cyanobacterial
genome set into timon's data directory (`TIMON_DB_DIR`, default
`~/.local/share/timon`), once, and every pipeline reads them from there — you
never type a database path. Until they are installed a run that reads them
cannot start; once they are, the button is frozen as **installed**.

The Kraken2 index comes in two builds, and the card lets you pick before
anything is fetched:

| | Download | Needs |
| --- | --- | --- |
| **PlusPF-16** (default) | 11.1 GB | 16 GB of memory to classify with |
| **PlusPF-8** | 5.5 GB | 8 GB |

Both hold the same organisms — archaea, bacteria, viruses, plasmids, human,
vectors, protozoa and fungi — from the same build date; the smaller one is
hashed down harder, so it classifies a little less. The choice is about the
machine, not the analysis: nothing records which you installed and no pipeline
is told, so either one satisfies a run. Installing one means the other is not
offered.

The GTDB-Tk data (~100 GB) is not part of that install: it is only read by
mag-ont's bin QA, so it gets an install button of its own, shown only when a
run needs it. A site that already has a copy of any of them can point timon at
it with `KRAKEN_DB`, `GTDBTK_DB` or `TIMON_GENOMES_DB` instead.

Nothing appears in that directory until the whole file is there, so an
interrupted download leaves no half-installed database behind, and one that is
already installed is never downloaded over. A download does belong to the timon
process, though: quitting ends it.

Some of what timon reads has no published source — its own genome set, as
things stand. Those are listed the same way, with the variable that names them
(`TIMON_GENOMES_DB`).

### Where things are written

Everything stays under the folder you launched from:

```
<launch dir>/
  imports/                 input folder (INPUT_DIR) — your reads, never written to
  timon_results/           output folder (OUTPUT_DIR) — what the results view walks
    <run identifier>/      pipeline results
      .timon-run.json      what that run was, for the runs view
      .timon-run.log       what that run printed
    <pipeline>_test/       what a quick test wrote, if you ran one
    .samplesheet_*.csv     what the sample sheet was saved as
    .timon_resources.config  what this machine caps a task's request at
    .work/                 Nextflow work directory, shared across runs
```

The four dotted entries are timon's own and are hidden from the results
view, so what you browse there is the runs themselves.

### Resources

Pipelines written for a cluster ask for more than a laptop has — mag-ont wants
36 GB for a step it calls *medium* — and Nextflow refuses such a request rather
than shrinking it. So before each run timon writes
`.timon_resources.config` naming what this machine actually has, and passes it
with `-c`. It is a ceiling, never a reservation: it only lowers what a process
asks for.

On a shared machine, or under a scheduler, say what your share is instead:

```console
TIMON_MAX_CPUS=8 TIMON_MAX_MEMORY=32.GB timon
```

## Configuration

Environment variables are the configuration surface:

| Variable | Meaning |
| --- | --- |
| `INPUT_DIR` | input folder — where `scan folder` looks for reads, relative to the launch directory (default `imports`) |
| `OUTPUT_DIR` | output folder — where runs write, relative to the launch directory (default `timon_results`) |
| `KRAKEN_DB` | an existing Kraken2 database to use instead of timon's installed one |
| `GTDBTK_DB` | an existing GTDB-Tk database to use instead of timon's installed one |
| `TIMON_PROFILE` | container engine Nextflow provisions tasks with (default `docker`) |
| `TIMON_NEXTFLOW` | Nextflow binary to use, for sites that `module load` their own |
| `TIMON_DB_DIR` | reference data location (default: XDG data dir) |
| `TIMON_MAX_CPUS` | cap on the CPUs a task may ask for (default: this machine's) |
| `TIMON_MAX_MEMORY` | cap on the memory a task may ask for, e.g. `32.GB` (default: this machine's) |
| `TIMON_MAX_TIME` | cap on a task's wall clock, e.g. `4.h` (default: none) |
| `TIMON_GENOMES_DB` | the CoverM genome database, named outright — a directory or a `.tar.gz`. Any set of FASTA files is valid, so a small one works; without it the full set is looked for under `TIMON_DB_DIR` |
| `TIMON_SECRET_KEY` | Flask secret key; a random one is generated per launch |

## A note on the network

timon binds to loopback by default, so the app is reachable only from the
machine it runs on. `--host` exists for the case where you need to reach it from
elsewhere (an SSH tunnel, a workstation on a trusted network) — bear in mind
that anyone who can reach the port can then browse directories on that machine,
and that timon has no authentication of its own.

## Development

### Tests

```console
pip install -e ".[dev]"
pytest
```

The suite covers the model — which parameters a run uses, what makes a
configuration and a sample sheet acceptable, the command line a configuration
describes, the workspace rule — and it needs neither Nextflow nor a container
engine, so it runs anywhere in about a second. `tests/test_config.py` is worth
knowing about: it checks the hand-written pipeline declarations against
themselves, which is where a typo would otherwise sit until someone opened the
form.

What it cannot check is that a declared default still matches the pipeline at
its pinned revision. That is a reading of the upstream repository, and it is
why bumping a revision means rechecking the defaults by hand.

### Styles

The stylesheet is built with Tailwind v4. The source is `styles/app.css`; the
built file `src/timon/app/static/style/app.css` is what ships in the wheel, so
edit the source and rebuild:

```console
npm install
npm run build      # or: npm run watch
```

Node is a dev-only toolchain — end users never need it.
