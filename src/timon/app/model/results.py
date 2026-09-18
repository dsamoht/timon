"""What a run left behind: the output folder, and one file in it.

A run writes to ``<output_folder>/<exp_id>/`` — reports, matrices, figures —
and that folder is the whole reason for having started it. This module
answers two questions about it and nothing else: what is in a folder, and
what one file in it says.

It is the only place timon reads a file's *contents*, so the rule here is
narrower than the one in ``files.py`` and has no way to be widened. A path
is judged against the output folder alone, there is no grant that reaches
past it, and anything resolving outside is refused. Browsing for reads has
to be able to leave the workspace — reads live on someone else's drive —
but nothing about opening a result does, so nothing here can.

What *kind* of thing a file is — a figure, a table, a report — is decided
here rather than in the page: it follows from the file, it is the same
answer for any front end, and it is what says whether reading the bytes is
a sensible thing to do at all. How it is then put on screen is the view's
business.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from .files import MAX_ENTRIES

# What a pipeline's outputs are worth opening as. Everything not named here
# is "other" — offered as a download and never read, which is the right
# answer for a BAM, a compressed table or an assembly graph.
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
HTML_EXTS  = {".html", ".htm"}
PDF_EXTS   = {".pdf"}
TABLE_EXTS = {".csv", ".tsv", ".tab"}
TEXT_EXTS  = {".txt", ".log", ".out", ".err", ".json", ".yaml", ".yml",
              ".md", ".config", ".nf", ".stats", ".summary", ".version"}

# Nextflow's scratch directory sits in the same folder the runs do, and holds
# one hashed directory per task — thousands of them, none of them a result.
# Hidden the way a file manager hides a dotfile: still on disk, just never
# what anyone came here for.
HIDDEN_AT_ROOT = {"work"}

# A preview is a look at a file, not a copy of it: a matrix can be hundreds
# of megabytes, and reading one into memory to show the top of it would take
# the server down. Everything below is capped, and what was left out is
# reported so the page can say so rather than quietly showing part of a file
# as if it were the whole one.
MAX_TEXT_BYTES = 200_000
MAX_TABLE_ROWS = 200
MAX_TABLE_COLS = 40


class OutsideResults(Exception):
    """A path that does not live under the output folder."""

    def __init__(self, path):
        super().__init__(str(path))
        self.path = path


def kind_of(name: str) -> str:
    """What a file is, judged by its name: the listing's answer for every row.

    A name is all a listing can afford — it has one line of work per entry
    and no business opening anything — so this is a guess, and ``preview``
    refines it once the bytes are in hand.
    """
    suffix = Path(name).suffix.lower()
    if suffix in IMAGE_EXTS:
        return "image"
    if suffix in HTML_EXTS:
        return "html"
    if suffix in PDF_EXTS:
        return "pdf"
    if suffix in TABLE_EXTS:
        return "table"
    if suffix in TEXT_EXTS:
        return "text"
    return "other"


def openable(kind: str) -> bool:
    """Whether timon can show this, as against handing it over to be saved."""
    return kind != "other"


# ── the rule ─────────────────────────────────────────────────────────────────

def output_root(output_folder) -> Path:
    """The folder every result path is judged against.

    The output folder itself, not one run's subfolder: the runs are what the
    top level of the browser lists, and a user with three of them behind
    them should not have to launch timon three times to look at them.
    """
    return Path(output_folder).expanduser().resolve()


def resolve(output_folder, rel: str | None) -> Path:
    """A path inside the output folder, or a refusal.

    ``rel`` is read as relative to the root — that is what a listing hands
    the page and what the page hands back. Symlinks are followed before the
    check, so a link inside the output folder is judged by where it actually
    goes; an absolute path is not special-cased because the containment
    check is what settles it either way.
    """
    root = output_root(output_folder)
    target = (root / (rel or "")).resolve()
    if target != root and root not in target.parents:
        raise OutsideResults(target)
    return target


def _rel(root: Path, path: Path) -> str:
    return "" if path == root else str(path.relative_to(root))


def _crumbs(root: Path, path: Path) -> list[dict]:
    crumbs = [{"name": root.name or str(root), "rel": "", "root": True}]
    for part in path.relative_to(root).parts:
        rel = f"{crumbs[-1]['rel']}/{part}" if crumbs[-1]["rel"] else part
        crumbs.append({"name": part, "rel": rel, "root": False})
    return crumbs


def _entry(root: Path, dir_entry: os.DirEntry) -> dict:
    try:
        stat = dir_entry.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        # A dangling symlink, or a file nextflow replaced mid-listing. Worth
        # showing by name; there is nothing more to say about it.
        size, mtime = None, None
    is_dir = dir_entry.is_dir()
    kind = "" if is_dir else kind_of(dir_entry.name)
    return {
        "name":     dir_entry.name,
        "rel":      _rel(root, Path(dir_entry.path)),
        "dir":      is_dir,
        "kind":     kind,
        "openable": not is_dir and openable(kind),
        "size":     None if is_dir else size,
        "mtime":    mtime,
    }


def listing(output_folder, rel: str | None = None) -> dict:
    """One folder of outputs. Raises OutsideResults, FileNotFoundError, OSError.

    A missing root is not an error: it is what a workspace looks like before
    the first run finishes, and the page has something better to say about
    that than a failure. A missing folder further down is a stale link, and
    is reported as one.
    """
    root = output_root(output_folder)
    path = resolve(output_folder, rel)
    at_root = path == root

    if not path.exists():
        if at_root:
            return {"root": str(root), "path": str(path), "rel": "", "name": root.name,
                    "parent": None, "crumbs": _crumbs(root, path), "entries": [],
                    "truncated": 0, "at_root": True, "exists": False}
        raise FileNotFoundError(str(path))
    if not path.is_dir():
        raise NotADirectoryError(str(path))

    entries, truncated = [], 0
    with os.scandir(path) as it:
        for dir_entry in it:
            if dir_entry.name.startswith("."):
                continue
            if at_root and dir_entry.name in HIDDEN_AT_ROOT:
                continue
            if len(entries) >= MAX_ENTRIES:
                truncated += 1
                continue
            entries.append(_entry(root, dir_entry))

    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))

    return {
        "root":      str(root),
        "path":      str(path),
        "rel":       _rel(root, path),
        "name":      path.name,
        "parent":    None if at_root else _rel(root, path.parent),
        "crumbs":    _crumbs(root, path),
        "entries":   entries,
        "truncated": truncated,
        "at_root":   at_root,
        "exists":    True,
    }


# ── one file ─────────────────────────────────────────────────────────────────

def _head(path: Path, limit: int) -> tuple[str, bool]:
    """The first ``limit`` bytes as text, and whether there was more.

    Decoded with replacement rather than strictly: a pipeline writes a table
    in whatever encoding its tool used, and refusing to show one because of
    a stray byte in a species name would be its own bug. A cut file loses
    its last line, which is half a record and would render as a wrong one.
    """
    with open(path, "rb") as handle:
        blob = handle.read(limit + 1)
    truncated = len(blob) > limit
    text = blob[:limit].decode("utf-8", errors="replace")
    if truncated and "\n" in text:
        text = text[:text.rfind("\n") + 1]
    return text, truncated


def _delimiter(name: str, text: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        return ","
    if suffix in {".tsv", ".tab"}:
        return "\t"
    return "\t" if "\t" in text.split("\n", 1)[0] else ","


def _is_tabular(text: str) -> bool:
    """Whether a text file is really a table nobody named as one.

    Pipelines write matrices as ``.txt`` and ``.stats`` constantly, and a
    tab-separated grid shown as a wall of text is the one thing a results
    browser must not do. The test is deliberately strict: every line of the
    head carries tabs, and they all have the same number of fields.
    """
    lines = [ln for ln in text.split("\n") if ln.strip()][:20]
    if len(lines) < 2 or not all("\t" in ln for ln in lines):
        return False
    return len({ln.count("\t") for ln in lines}) == 1


def _table(name: str, text: str) -> dict:
    rows = list(csv.reader(text.splitlines(), delimiter=_delimiter(name, text)))
    rows = [row for row in rows if row]
    columns = max((len(row) for row in rows), default=0)
    return {
        "rows":    [row[:MAX_TABLE_COLS] for row in rows[:MAX_TABLE_ROWS]],
        "columns": columns,
        "wide":    columns > MAX_TABLE_COLS,
        "long":    len(rows) > MAX_TABLE_ROWS,
    }


def preview(output_folder, rel: str) -> dict:
    """One file, ready to be shown. Raises OutsideResults, OSError.

    Only a table or a text file is read here. A figure, a report or a PDF is
    handed to the browser as bytes instead — it is the one that knows how to
    draw them — so for those this returns the facts and no content.
    """
    path = resolve(output_folder, rel)
    if path.is_dir():
        raise IsADirectoryError(str(path))
    stat = path.stat()          # FileNotFoundError for a stale link

    kind = kind_of(path.name)
    info = {
        "rel":      _rel(output_root(output_folder), path),
        "name":     path.name,
        "kind":     kind,
        "openable": openable(kind),
        "size":     stat.st_size,
        "mtime":    stat.st_mtime,
    }
    if kind not in {"table", "text"}:
        return info

    text, truncated = _head(path, MAX_TEXT_BYTES)
    # The refinement kind_of() cannot make from a name alone. It only ever
    # goes this way: a file named .csv is shown as a table even if the head
    # of it is odd, because that is what the pipeline called it.
    if kind == "text" and _is_tabular(text):
        kind = "table"
    if kind == "table":
        return {**info, "kind": "table", "truncated": truncated, **_table(path.name, text)}
    return {**info, "text": text, "truncated": truncated}
