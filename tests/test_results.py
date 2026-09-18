"""The output folder: what may be read, and what a file turns out to be.

Two rules live here and both are worth a test of their own. This is the one
module that reads a file's contents, so a path resolving outside the output
folder has to be refused with no way to ask for it; and a preview is a look
at a file rather than a copy of it, so what it leaves out it has to say.
"""

import pytest

from timon.app.model import results


@pytest.fixture
def outputs(tmp_path):
    """An output folder with one run's worth of files in it."""
    root = tmp_path / "imports"
    run = root / "exp1"
    run.mkdir(parents=True)
    (run / "report.html").write_text("<h1>report</h1>")
    (run / "abundance.tsv").write_text("sample\ttaxon\tcount\na\tphage\t12\n")
    (run / "log.txt").write_text("all good\n")
    (run / "reads.bam").write_bytes(b"\x00\x01")
    (root / "work").mkdir()
    return root


# ── the rule ─────────────────────────────────────────────────────────────────

def test_no_path_means_the_output_folder_itself(outputs):
    assert results.resolve(outputs, None) == outputs.resolve()


def test_a_path_is_read_against_the_output_folder(outputs):
    assert results.resolve(outputs, "exp1/report.html") == (outputs / "exp1/report.html").resolve()


def test_climbing_out_is_refused(outputs):
    with pytest.raises(results.OutsideResults):
        results.resolve(outputs, "../..")


def test_an_absolute_path_elsewhere_is_refused(outputs, tmp_path):
    elsewhere = tmp_path / "secrets.txt"
    elsewhere.write_text("no")
    with pytest.raises(results.OutsideResults):
        results.resolve(outputs, str(elsewhere))


def test_a_symlink_is_judged_by_where_it_goes(outputs, tmp_path):
    """A link a pipeline wrote must not be a way out of the output folder."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (outputs / "exp1" / "shortcut").symlink_to(elsewhere)
    with pytest.raises(results.OutsideResults):
        results.resolve(outputs, "exp1/shortcut")


def test_nothing_widens_the_rule(outputs, tmp_path):
    """files.ACCESS grants browsing outside the workspace; this is not that."""
    from timon.app.model import files
    files.ACCESS.allow_outside()
    try:
        with pytest.raises(results.OutsideResults):
            results.resolve(outputs, str(tmp_path))
    finally:
        files.ACCESS.lock()


# ── the listing ──────────────────────────────────────────────────────────────

def test_the_root_lists_the_runs(outputs):
    listing = results.listing(outputs)
    assert [e["name"] for e in listing["entries"]] == ["exp1"]
    assert listing["at_root"] is True
    assert listing["parent"] is None


def test_nextflows_scratch_directory_is_not_a_result(outputs):
    assert "work" not in [e["name"] for e in results.listing(outputs)["entries"]]


def test_a_folder_named_work_further_down_is_left_alone(outputs):
    (outputs / "exp1" / "work").mkdir()
    names = [e["name"] for e in results.listing(outputs, "exp1")["entries"]]
    assert "work" in names


def test_folders_come_first_then_files_by_name(outputs):
    (outputs / "exp1" / "krona").mkdir()
    names = [e["name"] for e in results.listing(outputs, "exp1")["entries"]]
    assert names == ["krona", "abundance.tsv", "log.txt", "reads.bam", "report.html"]


def test_an_entry_says_what_it_is_and_whether_it_opens(outputs):
    entries = {e["name"]: e for e in results.listing(outputs, "exp1")["entries"]}
    assert entries["report.html"]["kind"] == "html"
    assert entries["abundance.tsv"]["kind"] == "table"
    assert entries["reads.bam"]["kind"] == "other"
    assert entries["reads.bam"]["openable"] is False
    assert entries["report.html"]["openable"] is True


def test_a_listing_carries_no_file_contents(outputs):
    """The listing is names, sizes and dates — reading is a separate ask."""
    entry = results.listing(outputs, "exp1")["entries"][0]
    assert set(entry) == {"name", "rel", "dir", "kind", "openable", "size", "mtime"}


def test_crumbs_lead_back_to_the_root(outputs):
    crumbs = results.listing(outputs, "exp1")["crumbs"]
    assert [c["rel"] for c in crumbs] == ["", "exp1"]
    assert crumbs[0]["root"] is True


def test_an_output_folder_that_does_not_exist_yet_is_not_an_error(tmp_path):
    """Before the first run there is nothing there, and that is normal."""
    listing = results.listing(tmp_path / "imports")
    assert listing["exists"] is False
    assert listing["entries"] == []


def test_a_folder_that_went_away_is_reported(outputs):
    with pytest.raises(FileNotFoundError):
        results.listing(outputs, "exp1/gone")


def test_a_very_large_folder_is_capped(outputs, monkeypatch):
    monkeypatch.setattr(results, "MAX_ENTRIES", 3)
    for i in range(10):
        (outputs / "exp1" / f"bin_{i}.fa").write_text("")
    listing = results.listing(outputs, "exp1")
    assert len(listing["entries"]) == 3
    assert listing["truncated"] == 11


# ── one file ─────────────────────────────────────────────────────────────────

def test_a_table_comes_back_as_rows(outputs):
    view = results.preview(outputs, "exp1/abundance.tsv")
    assert view["kind"] == "table"
    assert view["rows"] == [["sample", "taxon", "count"], ["a", "phage", "12"]]
    assert view["columns"] == 3


def test_a_csv_is_split_on_commas(outputs):
    (outputs / "exp1" / "bins.csv").write_text("bin,completeness\nbin.1,98.2\n")
    assert results.preview(outputs, "exp1/bins.csv")["rows"][1] == ["bin.1", "98.2"]


def test_a_matrix_written_as_txt_is_still_a_table(outputs):
    """Pipelines name tab-separated matrices .txt constantly."""
    (outputs / "exp1" / "matrix.txt").write_text("a\tb\n1\t2\n3\t4\n")
    assert results.preview(outputs, "exp1/matrix.txt")["kind"] == "table"


def test_prose_is_not_mistaken_for_a_table(outputs):
    assert results.preview(outputs, "exp1/log.txt")["kind"] == "text"


def test_a_long_table_is_cut_and_says_so(outputs, monkeypatch):
    monkeypatch.setattr(results, "MAX_TABLE_ROWS", 5)
    rows = "\n".join(f"s{i}\t{i}" for i in range(50))
    (outputs / "exp1" / "big.tsv").write_text(f"sample\tcount\n{rows}\n")
    view = results.preview(outputs, "exp1/big.tsv")
    assert len(view["rows"]) == 5
    assert view["long"] is True


def test_a_wide_table_is_cut_and_still_counts_its_columns(outputs, monkeypatch):
    monkeypatch.setattr(results, "MAX_TABLE_COLS", 4)
    header = "\t".join(f"c{i}" for i in range(30))
    (outputs / "exp1" / "wide.tsv").write_text(f"{header}\n{header}\n")
    view = results.preview(outputs, "exp1/wide.tsv")
    assert len(view["rows"][0]) == 4
    assert view["columns"] == 30
    assert view["wide"] is True


def test_a_huge_text_file_is_read_no_further_than_the_cap(outputs, monkeypatch):
    monkeypatch.setattr(results, "MAX_TEXT_BYTES", 64)
    (outputs / "exp1" / "nextflow.log").write_text("x" * 5000 + "\n")
    view = results.preview(outputs, "exp1/nextflow.log")
    assert len(view["text"]) <= 64
    assert view["truncated"] is True


def test_a_cut_file_does_not_end_mid_line(outputs, monkeypatch):
    monkeypatch.setattr(results, "MAX_TEXT_BYTES", 20)
    (outputs / "exp1" / "lines.log").write_text("first line\nsecond line\nthird line\n")
    assert results.preview(outputs, "exp1/lines.log")["text"] == "first line\n"


def test_a_figure_is_described_but_not_read(outputs):
    (outputs / "exp1" / "plot.png").write_bytes(b"\x89PNG\r\n")
    view = results.preview(outputs, "exp1/plot.png")
    assert view["kind"] == "image"
    assert "text" not in view and "rows" not in view


def test_a_file_timon_cannot_show_says_so_rather_than_being_read(outputs):
    view = results.preview(outputs, "exp1/reads.bam")
    assert view["openable"] is False
    assert "text" not in view


def test_a_preview_cannot_leave_the_output_folder(outputs, tmp_path):
    (tmp_path / "secrets.txt").write_text("no")
    with pytest.raises(results.OutsideResults):
        results.preview(outputs, "../secrets.txt")


def test_a_folder_is_not_a_file(outputs):
    with pytest.raises(IsADirectoryError):
        results.preview(outputs, "exp1")
