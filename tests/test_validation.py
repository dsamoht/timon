"""What makes a run configuration and a sample sheet acceptable."""

import pytest

from timon.app.model import validation


# ── the run configuration ────────────────────────────────────────────────────

PIPE = {"name": "p", "columns": ["sample_id"], "params": []}


def config_errors(exp_id="run_1", values=None, fields=()):
    return validation.validate_configuration(PIPE, exp_id, values or {}, list(fields))


def test_a_select_whose_database_offers_nothing_is_refused():
    field = {"id": "bracken_length", "label": "Bracken read length", "type": "select",
             "options_from": "bracken_lengths", "enum": []}
    errors = config_errors(values={"bracken_length": "300"}, fields=[field])
    assert errors == ["'Bracken read length': the installed database offers no value for it"]


def test_a_run_identifier_is_required():
    assert "run identifier is required" in config_errors(exp_id="")


def test_a_run_identifier_may_not_carry_path_separators():
    """It becomes a directory name under the input folder."""
    assert config_errors(exp_id="../escape")
    assert config_errors(exp_id="with space")
    assert not config_errors(exp_id="run-1_A")


def test_a_run_identifier_has_to_be_long_enough_to_recognise():
    assert config_errors(exp_id="ab")
    assert config_errors(exp_id="x" * 65)


def test_a_number_outside_its_declared_range_is_refused():
    field = {"id": "q", "label": "min. Q", "type": "number", "step": 1, "min": 0, "max": 60}
    assert config_errors(values={"q": "61"}, fields=[field])
    assert config_errors(values={"q": "-1"}, fields=[field])
    assert not config_errors(values={"q": "9"}, fields=[field])


@pytest.mark.parametrize("raw", ["nan", "inf", "-inf", "1e400", "1e3", "1_000", "abc", "9" * 40,
                                 "0,5", "1,000"])
def test_a_number_that_is_not_plain_decimal_is_refused(raw):
    """NaN compares false against both bounds, so it has to be refused before them."""
    field = {"id": "c", "label": "confidence", "type": "number", "step": "any", "min": 0, "max": 1}
    errors = config_errors(values={"c": raw}, fields=[field])
    assert any("plain number" in e for e in errors), errors


def test_a_number_declared_without_a_floor_still_refuses_a_negative():
    field = {"id": "n", "label": "n", "type": "number", "step": 1, "default": 5}
    assert config_errors(values={"n": "-1"}, fields=[field])


def test_the_range_error_names_both_bounds():
    field = {"id": "q", "label": "min. Q", "type": "number", "step": 1, "min": 0, "max": 60}
    assert "'min. Q' must be between 0 and 60" in config_errors(values={"q": "600"}, fields=[field])


def test_a_whole_number_field_refuses_a_fraction():
    field = {"id": "n", "label": "n", "type": "number", "step": 1, "min": 0}
    assert any("whole number" in e for e in config_errors(values={"n": "1.5"}, fields=[field]))


def test_a_number_with_a_default_is_required():
    field = {"id": "n", "label": "n", "type": "number", "step": 1, "default": 5}
    assert any("required" in e for e in config_errors(values={"n": ""}, fields=[field]))


def test_a_number_the_pipeline_leaves_unset_may_be_left_empty():
    field = {"id": "cpus", "label": "CPUs", "type": "number", "step": 1, "default": None, "min": 1}
    assert not config_errors(values={"cpus": ""}, fields=[field])
    assert not config_errors(values={"cpus": None}, fields=[field])
    # Given, it is judged like any other number.
    assert config_errors(values={"cpus": "0"}, fields=[field])


def test_a_float_field_accepts_a_fraction():
    field = {"id": "c", "label": "confidence", "type": "number", "step": "any",
             "min": 0, "max": 1}
    assert not config_errors(values={"c": "0.05"}, fields=[field])


def test_a_select_only_takes_what_it_declared():
    field = {"id": "mode", "label": "mode", "type": "select", "enum": ["reads", "both"]}
    assert config_errors(values={"mode": "assembly"}, fields=[field])
    assert not config_errors(values={"mode": "both"}, fields=[field])


def test_a_required_text_field_says_so_plainly():
    field = {"id": "model", "label": "Medaka model", "type": "text", "required": True}
    assert "'Medaka model' is required" in config_errors(values={"model": ""}, fields=[field])


def test_a_conditionally_required_field_names_what_asked_for_it():
    field = {"id": "db", "label": "antiSMASH databases", "type": "text",
             "required_when": {"mode": ["both"]}}
    mode = {"id": "mode", "label": "screening mode", "type": "select", "enum": ["reads", "both"]}
    errors = config_errors(values={"mode": "both", "db": ""}, fields=[field, mode])
    assert any("'screening mode' is 'both'" in e for e in errors)
    assert not config_errors(values={"mode": "reads", "db": ""}, fields=[field, mode])


def test_a_missing_database_is_not_a_mistake_in_the_form():
    """Nothing about a database is submitted — timon finds it — so a saved
    configuration can be waiting for an install without being refused."""
    assert not config_errors(values={"kraken_db": ""})


# ── the sample sheet ─────────────────────────────────────────────────────────

def test_an_empty_sheet_is_refused(roshab):
    assert validation.validate_samples([], roshab) == [
        "sample sheet is empty — add at least one sample"]


def test_every_column_is_required_unless_the_pipeline_says_otherwise(roshab):
    """roshab-cli's own schema requires all five, so it declares nothing."""
    assert validation.required_columns(roshab) == roshab["columns"]
    errors = validation.validate_samples(
        [{"sample_id": "s1", "group": "g", "info": "", "date": "2026-01-01",
          "reads": "reads_*.fastq.gz"}], roshab)
    assert "row 1 · 'info' is required" in errors


def test_a_long_read_only_sheet_is_accepted_where_the_pipeline_accepts_one(magont, reads):
    """mag-ont marks the short reads and the assembly optional; so must timon."""
    path = reads("imports/demo/a.fastq.gz")
    assert validation.validate_samples(
        [{"sample_id": "s1", "group": "g", "assembly_fasta": "",
          "long_reads": str(path), "short_reads_1": "", "short_reads_2": ""}],
        magont) == []


def test_a_row_with_neither_reads_nor_an_assembly_is_refused(magont):
    errors = validation.validate_samples(
        [{"sample_id": "s1", "group": "g", "assembly_fasta": "", "long_reads": "",
          "short_reads_1": "", "short_reads_2": ""}], magont)
    assert any("'assembly_fasta' or 'long_reads'" in e for e in errors)


def test_a_missing_read_file_is_refused(roshab):
    errors = validation.validate_samples(
        [{"sample_id": "s1", "group": "g", "info": "lake", "date": "2026-01-01",
          "reads": "/nowhere/reads.fastq.gz"}], roshab)
    assert any("path not found" in e for e in errors)


def test_a_wildcard_is_left_to_nextflow_to_resolve(roshab):
    """There is nothing on disk to look for, so it must not be looked for."""
    assert validation.validate_samples(
        [{"sample_id": "s1", "group": "g", "info": "lake", "date": "2026-01-01",
          "reads": "/nowhere/reads_*.fastq.gz"}], roshab) == []


def test_a_date_column_wants_an_unambiguous_date(roshab, reads):
    path = reads("imports/a.fastq.gz")
    row = {"sample_id": "s1", "group": "g", "info": "lake", "reads": str(path)}
    assert any("YYYY-MM-DD" in e
               for e in validation.validate_samples([{**row, "date": "01/02/2026"}], roshab))
    assert validation.validate_samples([{**row, "date": "2026-02-01"}], roshab) == []


def test_duplicate_sample_ids_are_refused(roshab, reads):
    path = reads("imports/a.fastq.gz")
    row = {"sample_id": "s1", "group": "g", "info": "lake", "date": "2026-01-01",
           "reads": str(path)}
    errors = validation.validate_samples([row, dict(row)], roshab)
    assert "duplicate sample_id: 's1'" in errors


def test_a_sample_id_may_not_carry_a_path_separator(roshab, reads):
    path = reads("imports/a.fastq.gz")
    errors = validation.validate_samples(
        [{"sample_id": "a/b", "group": "g", "info": "lake", "date": "2026-01-01",
          "reads": str(path)}], roshab)
    assert any("sample_id" in e for e in errors)


@pytest.mark.parametrize("sample_id", [".hidden", "-flag", "_private"])
def test_a_sample_id_must_start_with_a_letter_or_a_digit(roshab, reads, sample_id):
    """roshab-cli refuses these itself, after the run has started."""
    path = reads("imports/a.fastq.gz")
    errors = validation.validate_samples(
        [{"sample_id": sample_id, "group": "g", "info": "lake", "date": "2026-01-01",
          "reads": str(path)}], roshab)
    assert any("must start with a letter or digit" in e for e in errors)


def test_a_sample_id_may_still_carry_dots_hyphens_and_underscores_after_that(roshab, reads):
    path = reads("imports/a.fastq.gz")
    assert validation.validate_samples(
        [{"sample_id": "lake_A-2.1", "group": "g", "info": "lake", "date": "2026-01-01",
          "reads": str(path)}], roshab) == []
