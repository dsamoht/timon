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
   specific revision so a run can be reproduced.
2. **Run configuration** — a run identifier and the pipeline parameters worth
   changing. Anything not shown keeps the pipeline's own default.
3. **Sample sheet** — one row per sample. `scan folder` fills it from the input
   folder (`imports/` by default, relative to where you launched timon), and any
   column holding a path has a browse button beside it.
4. **Execution console** — the Nextflow output, streamed live, with a stop
   button.

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

### Where things are written

Everything stays under the folder you launched from:

```
<launch dir>/
  imports/                 input folder (INPUT_DIR)
    samplesheet_*.csv      what the sample sheet was saved as
    <run identifier>/      pipeline results
    work/                  Nextflow work directory, shared across runs
```

## Configuration

Environment variables are the configuration surface:

| Variable | Meaning |
| --- | --- |
| `INPUT_DIR` | input folder, relative to the launch directory (default `imports`) |
| `KRAKEN_DB` | Kraken2 database, for pipelines that classify reads |
| `GTDBTK_DB` | GTDB-Tk database, for pipelines that classify bins |
| `TIMON_PROFILE` | container engine Nextflow provisions tasks with (default `docker`) |
| `TIMON_NEXTFLOW` | Nextflow binary to use, for sites that `module load` their own |
| `TIMON_DB_DIR` | reference data location (default: XDG data dir) |
| `TIMON_SECRET_KEY` | Flask secret key; a random one is generated per launch |

## A note on the network

timon binds to loopback by default, so the app is reachable only from the
machine it runs on. `--host` exists for the case where you need to reach it from
elsewhere (an SSH tunnel, a workstation on a trusted network) — bear in mind
that anyone who can reach the port can then browse directories on that machine,
and that timon has no authentication of its own.

## Development

The stylesheet is built with Tailwind v4. The source is `styles/app.css`; the
built file `src/timon/app/static/style/app.css` is what ships in the wheel, so
edit the source and rebuild:

```console
npm install
npm run build      # or: npm run watch
```

Node is a dev-only toolchain — end users never need it.
