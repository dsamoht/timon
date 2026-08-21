#!/usr/bin/env bash
#
# Launch timon from a source checkout.
#
# Creates (and keeps up to date) a local virtualenv holding an editable
# install of this working tree, checks the things a run needs, then hands
# over to the `timon` entry point. Every argument is passed straight
# through, so this accepts everything `timon --help` lists:
#
#     ./run.sh                      # open a browser on a free port
#     ./run.sh --port 8000          # fixed port
#     ./run.sh --no-browser         # for use behind an SSH tunnel
#
# Environment:
#   TIMON_VENV      virtualenv location            (default: ./.venv)
#   TIMON_PYTHON    interpreter to build it with   (default: first suitable python3)
#   TIMON_DB_DIR    reference data                 (default: ./data if present)
#   TIMON_NEXTFLOW  nextflow binary                (default: nextflow on PATH)
#
# Note this runs the *checkout*. An installed timon (conda, pip) is just
# `timon` — you do not need this script for that.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${TIMON_VENV:-$REPO_ROOT/.venv}"
MIN_PY_MINOR=10   # pyproject requires >=3.10

# ── output ───────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    C_DIM=$'\033[2m'; C_CYAN=$'\033[36m'; C_YEL=$'\033[33m'
    C_RED=$'\033[31m'; C_OFF=$'\033[0m'
else
    C_DIM=''; C_CYAN=''; C_YEL=''; C_RED=''; C_OFF=''
fi
info() { printf '%s▸%s %s\n' "$C_CYAN" "$C_OFF" "$*"; }
note() { printf '%s  %s%s\n' "$C_DIM" "$*" "$C_OFF"; }
warn() { printf '%s!%s %s\n' "$C_YEL" "$C_OFF" "$*" >&2; }
die()  { printf '%s✗%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }

# ── locate an interpreter new enough to build the venv ───────────────────
find_python() {
    local candidate
    for candidate in "${TIMON_PYTHON:-}" python3 python3.13 python3.12 python3.11 python3.10; do
        [ -n "$candidate" ] || continue
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

# ── build or refresh the environment ─────────────────────────────────────
# uv is preferred when present: venvs it creates ship without pip, so a
# checkout set up with uv cannot be installed into by pip alone.
have_uv() { command -v uv >/dev/null 2>&1; }

install_editable() {
    if have_uv; then
        uv pip install --quiet --python "$VENV/bin/python" --editable "$REPO_ROOT"
    elif "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
        "$VENV/bin/python" -m pip install --quiet --editable "$REPO_ROOT"
    else
        note "no pip in the virtualenv — bootstrapping with ensurepip"
        "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 \
            || die "this virtualenv has no pip and ensurepip failed.
    Install uv, or delete $VENV and re-run this script."
        "$VENV/bin/python" -m pip install --quiet --editable "$REPO_ROOT"
    fi
}

if [ ! -x "$VENV/bin/python" ]; then
    info "creating virtualenv at ${VENV/#$HOME/\~}"
    if have_uv; then
        if ! uv_out="$(uv venv "$VENV" 2>&1)"; then
            printf '%s\n' "$uv_out" >&2
            die "could not create the virtualenv"
        fi
    else
        PYTHON="$(find_python)" || die "no python3 >= 3.$MIN_PY_MINOR found (set TIMON_PYTHON)"
        note "using $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"
        "$PYTHON" -m venv "$VENV" || die "could not create the virtualenv"
    fi
fi

# Reinstall when the entry point is missing, or when pyproject.toml has
# changed since the last install (dependencies or the script name may have
# moved). Comparing against the dist-info directory is enough.
DIST_INFO="$(find "$VENV/lib" -maxdepth 3 -name 'timon-*.dist-info' -print -quit 2>/dev/null || true)"
if [ ! -x "$VENV/bin/timon" ] || [ -z "$DIST_INFO" ] || [ "$REPO_ROOT/pyproject.toml" -nt "$DIST_INFO" ]; then
    info "installing timon (editable) into the virtualenv"
    install_editable || die "editable install failed — run it by hand to see why:
    uv pip install --python $VENV/bin/python -e $REPO_ROOT"
fi

# ── reference data ───────────────────────────────────────────────────────
# A checkout that still has the genome set beside it is the common case, so
# adopt it rather than making the user export the variable every time.
GENOMES="cyanobacteriota_ncbi_dRep_n220"
if [ -z "${TIMON_DB_DIR:-}" ] && [ -d "$REPO_ROOT/data/$GENOMES" ]; then
    export TIMON_DB_DIR="$REPO_ROOT/data"
    note "reference data: $TIMON_DB_DIR"
fi
DB_ROOT="${TIMON_DB_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/timon}"
if [ ! -d "$DB_ROOT/$GENOMES" ]; then
    warn "genome database not found at $DB_ROOT/$GENOMES"
    note "roshab-cli runs will refuse to start; set TIMON_DB_DIR to an existing copy"
fi

# ── nextflow ─────────────────────────────────────────────────────────────
NEXTFLOW="${TIMON_NEXTFLOW:-nextflow}"
if command -v "$NEXTFLOW" >/dev/null 2>&1; then
    note "nextflow: $(command -v "$NEXTFLOW")"
else
    warn "'$NEXTFLOW' is not on PATH — the app will start, but runs are disabled"
    note "install it with: conda install -c conda-forge -c bioconda 'nextflow>=26.04.0'"
fi

# ── hand over ────────────────────────────────────────────────────────────
# exec so Ctrl-C reaches timon directly and no wrapper shell lingers.
info "starting timon"
exec "$VENV/bin/timon" "$@"
