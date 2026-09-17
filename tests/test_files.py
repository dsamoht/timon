"""The workspace rule, and what a listing is allowed to say.

Two things matter here and both are security-shaped: the server, not the
page, decides whether a path outside the launch directory may be read, and a
listing never carries a file's contents.
"""

import pytest

from timon.app.model import files


@pytest.fixture
def rooted(tmp_path, monkeypatch):
    """A workspace root of our own. _ROOT is captured at import, so it is set here."""
    root = tmp_path / "workspace"
    (root / "imports").mkdir(parents=True)
    monkeypatch.setattr(files, "_ROOT", root)
    monkeypatch.setattr(files.ACCESS, "_outside", False)
    return root


# ── the rule ─────────────────────────────────────────────────────────────────

def test_no_path_means_the_workspace_itself(rooted):
    assert files.resolve(None) == rooted


def test_a_relative_path_is_read_against_the_workspace(rooted):
    assert files.resolve("imports") == rooted / "imports"


def test_leaving_the_workspace_is_refused_until_it_is_allowed(rooted, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(files.PermissionRequired):
        files.resolve(str(outside))

    files.ACCESS.allow_outside()
    assert files.resolve(str(outside)) == outside


def test_climbing_out_with_dot_dot_is_the_same_refusal(rooted):
    with pytest.raises(files.PermissionRequired):
        files.resolve("../..")


def test_a_symlink_is_judged_by_where_it_actually_goes(rooted, tmp_path):
    """A link planted inside the workspace must not be a way around the rule."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (rooted / "shortcut").symlink_to(outside)
    with pytest.raises(files.PermissionRequired):
        files.resolve(str(rooted / "shortcut"))


def test_a_grant_can_be_taken_back(rooted, tmp_path):
    files.ACCESS.allow_outside()
    files.ACCESS.lock()
    with pytest.raises(files.PermissionRequired):
        files.resolve(str(tmp_path))


# ── listings ─────────────────────────────────────────────────────────────────

def test_a_listing_carries_names_and_sizes_but_never_contents(rooted):
    (rooted / "reads.fastq.gz").write_text("ACGT")
    entry, = [e for e in files.listing(str(rooted))["entries"] if not e["dir"]]
    assert entry["name"] == "reads.fastq.gz"
    assert entry["size"] == 4
    assert set(entry) == {"name", "path", "dir", "seq", "size", "mtime"}


def test_directories_sort_above_files(rooted):
    (rooted / "a_file.txt").write_text("")
    (rooted / "z_dir").mkdir()
    names = [e["name"] for e in files.listing(str(rooted))["entries"]]
    assert names == ["imports", "z_dir", "a_file.txt"]


def test_sequence_files_are_marked_so_the_page_can_pick_them_out(rooted):
    for name in ("a.fastq.gz", "b.fq", "c.fasta", "d.fna", "e.txt"):
        (rooted / name).write_text("")
    marked = {e["name"]: e["seq"] for e in files.listing(str(rooted))["entries"]}
    assert marked == {"imports": False, "a.fastq.gz": True, "b.fq": True,
                      "c.fasta": True, "d.fna": True, "e.txt": False}


def test_dotfiles_are_hidden_the_way_a_file_manager_hides_them(rooted):
    (rooted / ".nextflow.log").write_text("")
    assert [e["name"] for e in files.listing(str(rooted))["entries"]] == ["imports"]


def test_a_huge_directory_is_capped_and_says_how_much_was_left_out(rooted, monkeypatch):
    monkeypatch.setattr(files, "MAX_ENTRIES", 3)
    for i in range(10):
        (rooted / f"read_{i}.fastq").write_text("")
    listing = files.listing(str(rooted))
    assert len(listing["entries"]) == 3
    assert listing["truncated"] == 8


def test_a_file_is_not_a_folder_to_browse(rooted):
    (rooted / "reads.fastq").write_text("")
    with pytest.raises(NotADirectoryError):
        files.listing(str(rooted / "reads.fastq"))


# ── which columns get a browse button ────────────────────────────────────────

def test_the_columns_holding_a_path_are_derived_from_their_names(magont):
    assert files.path_columns(magont) == [
        "assembly_fasta", "long_reads", "short_reads_1", "short_reads_2"]


def test_the_file_column_always_gets_one(roshab):
    assert "reads" in files.path_columns(roshab)


def test_a_label_column_does_not_get_one(roshab):
    assert "info" not in files.path_columns(roshab)
    assert "date" not in files.path_columns(roshab)
