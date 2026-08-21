"""Browsing the machine for input files.

timon works like a notebook: the directory it was started in is the
workspace, and the file browser opens there. Reads rarely stay put, though —
a sequencing run lands on an external drive, or in a shared folder two
levels above the analysis — so leaving the workspace has to be possible.
It is also the one action here that widens what the page can see, so it is
asked for explicitly and granted for the life of this process only: quitting
timon takes the grant with it.

The rule lives here rather than in the page. The browser talks to the
server, and a hand-written request has to meet the same wall the "up" button
does; the page only reacts to the refusal. Nothing in this module opens a
file — names, sizes and dates are all that ever leave it, which matters when
`--host` puts the server on more than loopback.

What a listing says is factual: real paths, real sizes. Shortening a path for
the eye (the leading ~) is presentation and belongs to presenters.py.
"""

import os
import re
from pathlib import Path

# Captured at import — that is server start, before anything can chdir, and
# is the same launch directory the input folder is resolved against.
_ROOT = Path.cwd().resolve()

# Broader than the fastq scan in utils.py: a browser is also how an assembly
# or a short-read pair gets picked, and those columns take fasta.
SEQ_RE = re.compile(r"\.(f(ast)?q|f(ast)?a|fna|fas)(\.gz)?$", re.IGNORECASE)

# Directories of basecalled reads run to thousands of files. The cap keeps
# one careless click from building a listing no one can read anyway; the
# count of what was left out is reported so the page can say so.
MAX_ENTRIES = 2000

# Columns a browse button is offered for. Derived rather than declared: a
# pipeline entry already names its file_column, and the rest of a sample
# sheet's paths are named after what they hold.
# The trailing number is what a paired-read column ends in (short_reads_1).
PATH_COLUMN_RE = re.compile(r"(reads|fasta|fastq|fa|file|path)(_?\d+)?$", re.IGNORECASE)


class PermissionRequired(Exception):
    """A path outside the workspace was asked for without a grant in force."""

    def __init__(self, path: Path):
        super().__init__(str(path))
        self.path = path


class Access:
    """Whether browsing outside the workspace is allowed, for this process.

    Deliberately not persisted: a grant is about the session in front of the
    user, and a stored one would silently outlive the reason it was given.
    """

    def __init__(self):
        self._outside = False

    def granted(self) -> bool:
        return self._outside

    def allow_outside(self) -> None:
        self._outside = True

    def lock(self) -> None:
        self._outside = False


ACCESS = Access()


def workspace_root() -> Path:
    return _ROOT


def path_columns(pipe: dict) -> list[str]:
    """Sample-sheet columns that hold a path, so can be filled by browsing."""
    cols = [c for c in pipe["columns"] if PATH_COLUMN_RE.search(c)]
    file_col = pipe.get("file_column")
    if file_col and file_col not in cols:
        cols.append(file_col)
    return cols


def _inside(path: Path) -> bool:
    return path == _ROOT or _ROOT in path.parents


def resolve(raw: str | None) -> Path:
    """Resolve a requested path, refusing to leave the workspace unasked.

    Symlinks are followed before the check, so a link planted inside the
    workspace is judged by where it actually goes.
    """
    if not raw:
        return _ROOT
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = _ROOT / path
    path = path.resolve()
    if not _inside(path) and not ACCESS.granted():
        raise PermissionRequired(path)
    return path


def _crumbs(path: Path) -> list[dict]:
    """Breadcrumb trail: from the workspace inside it, from home or / outside.

    Each crumb is a real directory the browser can be sent back to; how its
    name reads on screen (home as ~, say) is settled when it is rendered.
    """
    if _inside(path):
        base, rel = _ROOT, path.relative_to(_ROOT)
        crumbs = [{"name": _ROOT.name or str(_ROOT), "path": str(_ROOT), "root": True}]
    else:
        home = Path.home()
        if path == home or home in path.parents:
            base, rel = home, path.relative_to(home)
            crumbs = [{"name": home.name or str(home), "path": str(home), "root": False}]
        else:
            base, rel = Path(path.anchor), path.relative_to(path.anchor)
            crumbs = [{"name": path.anchor, "path": path.anchor, "root": False}]

    for part in rel.parts:
        base = base / part
        crumbs.append({"name": part, "path": str(base), "root": False})
    return crumbs


def _entry(dir_entry: os.DirEntry) -> dict:
    try:
        stat = dir_entry.stat()
        size, mtime = stat.st_size, stat.st_mtime
    except OSError:
        # A dangling symlink or a file that vanished mid-listing: worth
        # showing by name, but there is nothing more to say about it.
        size, mtime = None, None
    is_dir = dir_entry.is_dir()
    return {
        "name": dir_entry.name,
        "path": dir_entry.path,
        "dir":  is_dir,
        "seq":  not is_dir and bool(SEQ_RE.search(dir_entry.name)),
        "size": None if is_dir else size,
        "mtime": mtime,
    }


def listing(raw: str | None = None) -> dict:
    """One directory, ready to render. Raises PermissionRequired, OSError."""
    path = resolve(raw)
    if not path.is_dir():
        raise NotADirectoryError(str(path))

    entries, truncated = [], 0
    with os.scandir(path) as it:
        for dir_entry in it:
            # Dotfiles are hidden the way a file manager hides them: the
            # noise is never what a user came here to pick.
            if dir_entry.name.startswith("."):
                continue
            if len(entries) >= MAX_ENTRIES:
                truncated += 1
                continue
            entries.append(_entry(dir_entry))

    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))

    parent = path.parent if path.parent != path else None
    return {
        "path":       str(path),
        "parent":     str(parent) if parent else None,
        "crumbs":     _crumbs(path),
        "entries":    entries,
        "truncated":  truncated,
        "inside":     _inside(path),
        "at_root":    path == _ROOT,
        "outside_ok": ACCESS.granted(),
        "root":       str(_ROOT),
    }
