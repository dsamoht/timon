"""Scanning the input folder for reads, and collapsing what is found.

A scan is a suggestion the user then corrects, so what matters here is that
it groups the way a sequencer lays files out — a barcode directory is one
sample, chunked files are one sample — that what it suggests is a value the
pipeline would take, and that it never invents a path that does not resolve.
"""

import os

import pytest

from conftest import write_fastq
from timon.app.model.samples import (Unreadable, detect_samples_files, holds_data,
                                     sample_value)


def make(root, *relative, reads=1):
    for name in relative:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_fastq(path, reads)
    return root


# ── what is in a read file ───────────────────────────────────────────────────

def test_a_gzipped_fastq_with_no_reads_is_empty_though_it_has_bytes(tmp_path):
    make(tmp_path, "empty.fastq.gz", reads=0)
    assert (tmp_path / "empty.fastq.gz").stat().st_size > 0
    assert not holds_data(str(tmp_path / "empty.fastq.gz"))


def test_a_fastq_with_a_read_holds_data(tmp_path):
    make(tmp_path, "a.fastq.gz", "b.fastq")
    assert holds_data(str(tmp_path / "a.fastq.gz"))
    assert holds_data(str(tmp_path / "b.fastq"))


def test_a_file_named_gz_that_is_not_gzip_is_unreadable(tmp_path):
    (tmp_path / "a.fastq.gz").write_text("@r\nACGT\n+\nIIII\n")
    with pytest.raises(Unreadable, match="not gzip"):
        holds_data(str(tmp_path / "a.fastq.gz"))


# ── one value for a sample's files ───────────────────────────────────────────

def test_one_file_is_left_alone():
    assert sample_value(["/d/a.fastq.gz"], folders_ok=True) == "/d/a.fastq.gz"


def test_files_alone_in_their_folder_are_named_by_the_folder(tmp_path):
    make(tmp_path, "s/run_01.fastq.gz", "s/run_02.fastq.gz")
    paths = sorted(str(p) for p in (tmp_path / "s").iterdir())
    assert sample_value(paths, folders_ok=True) == str(tmp_path / "s")


def test_a_folder_shared_with_another_sample_does_not_stand_for_one(tmp_path):
    """The pipeline would read the other sample's reads too."""
    make(tmp_path, "s/a_1.fastq.gz", "s/a_2.fastq.gz", "s/b.fastq.gz")
    paths = [str(tmp_path / "s/a_1.fastq.gz"), str(tmp_path / "s/a_2.fastq.gz")]
    assert sample_value(paths, folders_ok=True) == ",".join(paths)


def test_a_pipeline_taking_one_file_is_given_the_list(tmp_path):
    """Which the save then explains: there is no one path to give it."""
    make(tmp_path, "s/run_01.fastq.gz", "s/run_02.fastq.gz")
    paths = sorted(str(p) for p in (tmp_path / "s").iterdir())
    assert sample_value(paths, folders_ok=False) == ",".join(paths)


def test_a_value_is_never_a_wildcard(tmp_path):
    make(tmp_path, "s/run_01.fastq.gz", "s/run_02.fastq.gz", "s/other.fastq.gz")
    paths = [str(tmp_path / "s/run_01.fastq.gz"), str(tmp_path / "s/run_02.fastq.gz")]
    for folders_ok in (True, False):
        assert "*" not in sample_value(paths, folders_ok)


# ── the scan ─────────────────────────────────────────────────────────────────

def test_a_missing_input_folder_is_not_an_error(tmp_path):
    assert detect_samples_files(str(tmp_path / "absent")) == {}


def test_a_barcode_directory_is_one_sample_named_by_its_folder(tmp_path):
    make(tmp_path, "barcode01/FAX123_pass_barcode01_0.fastq.gz",
                   "barcode01/FAX123_pass_barcode01_1.fastq.gz")
    found = detect_samples_files(str(tmp_path))
    assert len(found) == 1
    (name, value), = found.items()
    assert "barcode01" in name
    assert value == str(tmp_path / "barcode01")


def test_a_barcode_with_only_empty_reads_is_ignored(tmp_path):
    """What MinKNOW leaves for a barcode nothing was read into."""
    make(tmp_path, "barcode01/a_0.fastq.gz")
    make(tmp_path, "barcode02/b_0.fastq.gz", "barcode02/b_1.fastq.gz", reads=0)
    found = detect_samples_files(str(tmp_path))
    assert len(found) == 1
    assert "barcode02" not in " ".join(found.values())


def test_an_empty_chunk_beside_good_ones_does_not_lose_the_sample(tmp_path):
    make(tmp_path, "barcode01/a_0.fastq.gz", "barcode01/a_1.fastq.gz")
    make(tmp_path, "barcode01/a_2.fastq.gz", reads=0)
    (value,) = detect_samples_files(str(tmp_path)).values()
    assert value == str(tmp_path / "barcode01")


def test_an_empty_file_is_not_a_sample(tmp_path):
    make(tmp_path, "lake_A.fastq.gz")
    make(tmp_path, "lake_B.fastq.gz", reads=0)
    assert list(detect_samples_files(str(tmp_path))) == ["lake_A"]


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
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "assembly.fasta").write_text(">c\nACGT\n")
    assert detect_samples_files(str(tmp_path)) == {}


def test_the_scan_does_not_descend_past_a_run_directory(tmp_path):
    """Two levels is a barcode inside a run; deeper is someone else's results."""
    make(tmp_path, "run/barcode01/a.fastq.gz", "run/barcode01/deep/b.fastq.gz")
    values = " ".join(detect_samples_files(str(tmp_path)).values())
    assert "deep" not in values


def test_every_path_the_scan_reports_can_be_opened(tmp_path):
    """A scan that guessed a path wrong would fail validation, not the scan."""
    make(tmp_path, "lake_A.fastq.gz", "barcode01/x_0.fastq.gz", "barcode01/x_1.fastq.gz")
    for value in detect_samples_files(str(tmp_path)).values():
        assert os.path.exists(value)
