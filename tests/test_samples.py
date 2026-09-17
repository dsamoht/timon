"""Scanning the input folder for reads, and collapsing what is found.

A scan is a suggestion the user then corrects, so what matters here is that
it groups the way a sequencer lays files out — a barcode directory is one
sample, chunked files are one sample — and never invents a path that does not
resolve.
"""

import os

from timon.app.model.samples import convert_realpaths_to_wildcards, detect_samples_files


def make(root, *relative):
    for name in relative:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    return root


# ── collapsing several files into one value ──────────────────────────────────

def test_one_file_is_left_alone():
    assert convert_realpaths_to_wildcards(["/d/a.fastq.gz"]) == "/d/a.fastq.gz"


def test_files_in_one_directory_collapse_to_a_wildcard():
    value = convert_realpaths_to_wildcards(
        ["/d/run_01.fastq.gz", "/d/run_02.fastq.gz"])
    assert value == "/d/run_0*.fastq.gz"


def test_files_across_directories_cannot_be_wildcarded():
    """A comma-separated list is what is left; a wildcard would miss one."""
    value = convert_realpaths_to_wildcards(["/a/x.fastq.gz", "/b/y.fastq.gz"])
    assert value == "/a/x.fastq.gz,/b/y.fastq.gz"


# ── the scan ─────────────────────────────────────────────────────────────────

def test_a_missing_input_folder_is_not_an_error(tmp_path):
    assert detect_samples_files(str(tmp_path / "absent")) == {}


def test_a_barcode_directory_is_one_sample(tmp_path):
    make(tmp_path, "barcode01/FAX123_pass_barcode01_0.fastq.gz",
                   "barcode01/FAX123_pass_barcode01_1.fastq.gz")
    found = detect_samples_files(str(tmp_path))
    assert len(found) == 1
    (name, value), = found.items()
    assert "barcode01" in name
    assert "*" in value


def test_chunked_files_beside_each_other_are_one_sample(tmp_path):
    make(tmp_path, "lake_A_1.fastq.gz", "lake_A_2.fastq.gz")
    found = detect_samples_files(str(tmp_path))
    assert list(found) == ["lake_A"]


def test_separate_samples_stay_separate(tmp_path):
    make(tmp_path, "lake_A.fastq.gz", "lake_B.fastq.gz")
    assert sorted(detect_samples_files(str(tmp_path))) == ["lake_A", "lake_B"]


def test_plain_fastq_is_found_as_well_as_gzipped(tmp_path):
    make(tmp_path, "lake_A.fq", "lake_B.fastq")
    assert sorted(detect_samples_files(str(tmp_path))) == ["lake_A", "lake_B"]


def test_files_that_are_not_reads_are_ignored(tmp_path):
    make(tmp_path, "notes.txt", "assembly.fasta")
    assert detect_samples_files(str(tmp_path)) == {}


def test_the_scan_does_not_descend_past_a_run_directory(tmp_path):
    """Two levels is a barcode inside a run; deeper is someone else's results."""
    make(tmp_path, "run/barcode01/a.fastq.gz", "run/barcode01/deep/b.fastq.gz")
    values = " ".join(detect_samples_files(str(tmp_path)).values())
    assert "deep" not in values


def test_every_path_the_scan_reports_can_be_opened(tmp_path):
    """A scan that guessed a path wrong would fail validation, not the scan."""
    make(tmp_path, "lake_A.fastq.gz")
    (value,) = detect_samples_files(str(tmp_path)).values()
    assert os.path.exists(value)
