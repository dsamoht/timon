"""Normalising declarations, and working out what a run still uses.

The conditions are the part worth testing hardest: whether a parameter is
part of a run decides what the form shows, what validation insists on and
what reaches the command line, and it is answered in exactly one place.
"""

import pytest

from timon.app.model import params as P

PIPE = {
    "columns": ["sample_id"],
    "params": [
        {"id": "mode", "type": "select", "default": "reads",
         "enum": ["reads", "assembly", "both"]},
        {"id": "skip_qc", "type": "bool", "default": False},
        {"id": "min_len", "type": "number", "default": 500, "min": 0,
         "active_when": {"skip_qc": [False]}},
        {"id": "trim", "type": "number", "default": 0.5, "step": "any",
         "active_when": {"skip_qc": [False]}},
        {"id": "note", "type": "text"},
    ],
}


# ── normalising ──────────────────────────────────────────────────────────────

def test_id_is_the_label_when_none_is_given():
    note = next(p for p in P.fields(PIPE) if p["id"] == "note")
    assert note["label"] == "note"
    assert note["type"] == "text"
    assert note["default"] == ""
    assert note["required"] is False


def test_numbers_get_an_integer_step_unless_declared_otherwise():
    fields = {p["id"]: p for p in P.fields(PIPE)}
    assert fields["min_len"]["step"] == 1
    assert fields["trim"]["step"] == "any"


def test_a_database_is_never_also_a_parameter():
    """timon finds it, so a field for it could only disagree with timon."""
    pipe = {**PIPE, "reference_data": ["kraken_db"],
            "params": PIPE["params"] + [{"id": "kraken_db", "type": "text"}]}
    assert "kraken_db" not in {p["id"] for p in P.fields(pipe)}


def test_a_database_drops_out_with_the_step_that_reads_it():
    pipe = {**PIPE, "reference_data": ["gtdbtk_db"],
            "db_optional_when": {"gtdbtk_db": ["skip_qc"]}}
    assert "gtdbtk_db" not in P.inactive_ids(pipe, {"skip_qc": False})
    assert "gtdbtk_db" in P.inactive_ids(pipe, {"skip_qc": True})


# ── which parameters a run uses ──────────────────────────────────────────────

def test_nothing_drops_out_of_a_default_run():
    assert P.inactive_ids(PIPE, {}) == set()


def test_a_skipped_step_takes_its_parameters_with_it():
    assert P.inactive_ids(PIPE, {"skip_qc": True}) == {"min_len", "trim"}


def test_conditions_are_answered_against_defaults_before_anything_is_saved():
    """The freshly rendered form is the pipeline's defaults, not an empty dict."""
    pipe = {**PIPE, "params": PIPE["params"] + [
        {"id": "assembler", "type": "text", "active_when": {"mode": ["assembly"]}}]}
    assert "assembler" in P.inactive_ids(pipe, {})
    assert "assembler" not in P.inactive_ids(pipe, {"mode": "assembly"})


def test_a_condition_on_a_dropped_parameter_drops_too():
    """`skip Nanoplot` sits under `skip QC`: skipping QC has to take both."""
    pipe = {**PIPE, "params": PIPE["params"] + [
        {"id": "min_len_strict", "type": "bool", "default": False,
         "active_when": {"min_len": [500]}}]}
    inactive = P.inactive_ids(pipe, {"skip_qc": True})
    assert {"min_len", "min_len_strict"} <= inactive


def test_every_condition_has_to_hold_not_just_one():
    pipe = {**PIPE, "params": PIPE["params"] + [
        {"id": "polish", "type": "bool", "default": False,
         "active_when": {"mode": ["assembly"], "skip_qc": [False]}}]}
    assert "polish" not in P.inactive_ids(pipe, {"mode": "assembly", "skip_qc": False})
    assert "polish" in P.inactive_ids(pipe, {"mode": "assembly", "skip_qc": True})


def test_a_form_value_matches_a_condition_written_as_the_config_writes_it():
    """A select arrives as a string; a condition may name a number or a bool."""
    pipe = {"columns": [], "params": [
        {"id": "n", "type": "number", "default": 1},
        {"id": "on_two", "type": "text", "active_when": {"n": [2]}}]}
    assert "on_two" not in P.inactive_ids(pipe, {"n": "2"})


def test_a_database_only_some_steps_read_drops_with_them():
    pipe = {**PIPE, "requires_db": ["gtdbtk_db"],
            "db_optional_when": {"gtdbtk_db": ["skip_qc"]}}
    assert "gtdbtk_db" not in P.inactive_ids(pipe, {})
    assert "gtdbtk_db" in P.inactive_ids(pipe, {"skip_qc": True})


# ── required, and customised ─────────────────────────────────────────────────

def test_required_when_names_the_choice_that_asked_for_the_value():
    p = {"id": "db", "required_when": {"mode": ["assembly", "both"]}}
    assert P.required_trigger(p, {"mode": "both"}) == ("mode", "both")
    assert P.required_trigger(p, {"mode": "reads"}) is None


def test_a_value_equal_to_the_default_is_not_customised():
    fields = {p["id"]: p for p in P.fields(PIPE)}
    assert not P.is_customised(fields["min_len"], {"min_len": 500})
    assert not P.is_customised(fields["min_len"], {"min_len": "500"})
    assert P.is_customised(fields["min_len"], {"min_len": 400})


def test_an_unset_parameter_is_not_customised():
    fields = {p["id"]: p for p in P.fields(PIPE)}
    assert not P.is_customised(fields["min_len"], {})


def test_a_number_the_pipeline_leaves_unset_is_customised_only_by_a_value():
    p = P._normalise({"id": "cpus", "type": "number", "default": None})
    assert not P.is_customised(p, {"cpus": None})
    assert not P.is_customised(p, {"cpus": ""})
    assert P.is_customised(p, {"cpus": 8})


def test_an_empty_unset_number_is_cast_to_nothing():
    assert P.coerce({"type": "number", "step": 1, "default": None}, "") is None


# ── casting ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("declared, raw, expected", [
    ({"type": "bool"}, "on", True),
    ({"type": "bool"}, None, False),
    ({"type": "number", "step": 1}, "80", 80),
    ({"type": "number", "step": 1}, "80.0", 80),
    ({"type": "number", "step": "any"}, "0.05", 0.05),
    ({"type": "text"}, None, ""),
    ({"type": "text"}, " kept ", " kept "),
])
def test_a_submitted_value_becomes_what_belongs_on_the_command_line(declared, raw, expected):
    assert P.coerce(declared, raw) == expected


def test_a_fraction_declared_as_a_float_is_not_rounded_to_zero():
    """step "any" is the whole difference between 0.05 and a run at 0."""
    assert P.coerce({"type": "number", "step": "any"}, "0.05") == 0.05
    assert P.coerce({"type": "number", "step": 1}, "0.05") == 0


def test_an_unreadable_number_falls_back_to_the_declared_default():
    assert P.coerce({"type": "number", "step": 1, "default": 9}, "abc") == 9


# ── reading a number ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "nan", "NaN", "inf", "-inf", "infinity", "1e3", "1e400", "1_000", "0x10",
    "١٢", "12 34", "--1", "1.2.3", "", "   ", None, True, float("nan"), float("inf"),
    "9" * 21, "0,5", "1,000", "80.", ".5", "1.000,5", "1 000",
])
def test_only_a_plain_finite_decimal_is_a_number(raw):
    assert P.parse_number(raw) is None


@pytest.mark.parametrize("raw, expected", [
    ("80", 80.0), (" 80 ", 80.0), ("0.5", 0.5), ("1000.25", 1000.25), ("-3", -3.0), (7, 7.0), (0.25, 0.25),
])
def test_a_plain_decimal_is_read_as_written(raw, expected):
    assert P.parse_number(raw) == expected


def test_a_number_declared_without_a_floor_cannot_go_negative():
    assert P._normalise({"id": "n", "type": "number", "default": 1})["min"] == 0
    assert P._normalise({"id": "n", "type": "number", "default": 1, "min": 5})["min"] == 5


def test_an_unreadable_number_never_reaches_the_command_line_as_nan():
    assert P.coerce({"type": "number", "step": "any", "default": 0.5}, "nan") == 0.5
    assert P.coerce({"type": "number", "step": 1, "default": 9}, "1e400") == 9


# ── options read from a database ─────────────────────────────────────────────

LENGTH = {"id": "bracken_length", "type": "select", "default": "300",
          "options_from": "bracken_lengths"}


def test_a_select_from_a_database_offers_what_the_database_holds():
    p = P._normalise(LENGTH, {"bracken_lengths": ["100", "300"]})
    assert p["enum"] == ["100", "300"]
    assert p["default"] == "300"


def test_before_the_database_can_be_read_the_default_is_the_only_option():
    p = P._normalise(LENGTH, {"bracken_lengths": None})
    assert p["enum"] == ["300"]
    assert p["options_known"] is False
    assert P._normalise(LENGTH)["enum"] == ["300"]


def test_a_default_the_database_lacks_moves_to_the_nearest_it_has():
    assert P._normalise(LENGTH, {"bracken_lengths": ["50", "250"]})["default"] == "250"
    assert P._normalise(LENGTH, {"bracken_lengths": ["50", "1000"]})["default"] == "50"


def test_a_database_holding_none_offers_nothing():
    assert P._normalise(LENGTH, {"bracken_lengths": []})["enum"] == []
