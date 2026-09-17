"""The declarations themselves.

Almost everything about a pipeline is written by hand in config.py, so a
typo there is the likeliest way timon breaks: a group heading that never
appears, a condition naming a parameter that was renamed, a select whose
default is not one of its own options. None of that shows up until someone
opens the form, unless it is checked here.

What these cannot check is the one thing that matters most — that a declared
default still matches the pipeline at the pinned revision. That is a reading
of the upstream repository, and it is why bumping a revision is a deliberate
act with the defaults rechecked by hand.
"""

import re

import pytest

from timon.app.config import DATABASE_BUNDLE, DB_SOURCES, PIPELINES
from timon.paths import REFERENCE_DATA, db_root
from timon.app.model import downloads, params as P
from timon.app.model.validation import required_columns

PIPES = list(PIPELINES.items())
IDS = [name for name, _ in PIPES]


@pytest.fixture(params=[pipe for _, pipe in PIPES], ids=IDS)
def pipe(request):
    return request.param


# ── the entry ────────────────────────────────────────────────────────────────

def test_every_pipeline_declares_what_a_card_and_a_run_need(pipe):
    for key in ("name", "description", "icon", "pipeline", "profiles",
                "columns", "file_column", "params"):
        assert key in pipe, key


def test_a_pipeline_is_named_as_owner_and_repo(pipe):
    """It is passed straight to `nextflow run`."""
    assert pipe["pipeline"].count("/") == 1


def test_a_revision_is_a_release_tag(pipe):
    """A branch moves, so two runs of one timon version could not be compared,
    and a bare commit names no release anyone can look up. A tag is both."""
    if not pipe.get("revision"):
        return
    assert re.fullmatch(r"v?\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?", pipe["revision"]), pipe["revision"]


def test_the_default_profile_is_one_the_pipeline_supports(pipe):
    assert pipe["profiles"]
    assert "docker" in pipe["profiles"]


def test_a_test_profile_is_not_one_of_the_container_engines(pipe):
    """"profiles" is engines only — the test profile is run beside one of them,
    as `-profile test,docker`, and would select no container on its own."""
    test_profile = pipe.get("test_profile")
    if test_profile is None:
        return
    assert isinstance(test_profile, str) and test_profile
    assert test_profile not in pipe["profiles"]


def test_a_pipeline_that_cannot_be_run_is_not_offered(pipe):
    """An unpinned pipeline refuses every run, so a card for it only misleads."""
    if not pipe.get("revision"):
        assert pipe.get("selectable") is False


# ── the sample sheet ─────────────────────────────────────────────────────────

def test_the_file_column_is_one_of_the_columns(pipe):
    assert pipe["file_column"] in pipe["columns"]


def test_required_columns_are_columns(pipe):
    assert set(required_columns(pipe)) <= set(pipe["columns"])


def test_one_of_columns_are_columns(pipe):
    for group in pipe.get("one_of_columns") or []:
        assert set(group) <= set(pipe["columns"])


def test_a_column_is_never_both_always_required_and_only_sometimes(pipe):
    required = set(required_columns(pipe))
    for group in pipe.get("one_of_columns") or []:
        assert not required & set(group)


# ── the databases ────────────────────────────────────────────────────────────

def test_a_database_a_pipeline_reads_is_one_timon_can_find(pipe):
    for key in pipe.get("reference_data", []):
        assert key in REFERENCE_DATA


def test_a_database_a_pipeline_reads_has_a_flag_to_be_passed_under(pipe):
    from timon.app.model.nextflow import REFERENCE_FLAGS
    for key in pipe.get("reference_data", []):
        assert key in REFERENCE_FLAGS


def test_a_database_is_never_also_declared_as_a_parameter(pipe):
    """timon and the form would be two sources for one value."""
    declared = {p["id"] for p in pipe["params"]}
    assert not declared & set(pipe.get("reference_data", []))


def test_a_database_excused_by_a_flag_is_excused_by_a_real_one(pipe):
    declared = {p["id"] for p in pipe["params"]}
    for key, flags in (pipe.get("db_optional_when") or {}).items():
        assert key in pipe.get("reference_data", [])
        assert set(flags) <= declared


# ── the parameters ───────────────────────────────────────────────────────────

def test_no_parameter_is_declared_twice(pipe):
    ids = [p["id"] for p in pipe["params"]]
    assert len(ids) == len(set(ids))


def test_no_parameter_takes_a_name_the_form_already_uses(pipe):
    """The configuration form posts its own fields alongside the declared ones.

    A parameter sharing one of their names would be read as that field and
    passed to nextflow as a flag, which is two bugs rather than one.
    """
    for p in P.fields(pipe):
        assert p["id"] not in {"exp-id", "resume", "pipeline_select"}, p["id"]


def test_a_select_defaults_to_one_of_its_own_options(pipe):
    for p in P.fields(pipe):
        if p["type"] == "select":
            assert str(p["default"]) in p["enum"], p["id"]


def test_a_number_defaults_inside_its_own_range(pipe):
    for p in P.fields(pipe):
        if p["type"] != "number" or p["default"] is None:
            continue
        assert "min" not in p or p["default"] >= p["min"], p["id"]
        assert "max" not in p or p["default"] <= p["max"], p["id"]


def test_a_number_is_bounded_on_both_sides(pipe):
    """Nothing in the form can be negative or unbounded: a typo has a ceiling."""
    for p in pipe["params"]:
        if p.get("type") != "number":
            continue
        assert "min" in p and "max" in p, p["id"]
        assert 0 <= p["min"] < p["max"], p["id"]


def test_a_whole_number_does_not_default_to_a_fraction(pipe):
    for p in P.fields(pipe):
        if p["type"] == "number" and p.get("step") == 1 and p["default"] is not None:
            assert float(p["default"]) == int(p["default"]), p["id"]


def test_a_condition_names_a_parameter_that_exists(pipe):
    known = {p["id"] for p in P.fields(pipe)} | set(pipe.get("reference_data", []))
    for p in pipe["params"]:
        for key in list(p.get("active_when") or {}) + list(p.get("required_when") or {}):
            assert key in known, f"{p['id']} → {key}"


def test_a_condition_names_a_value_that_parameter_can_hold(pipe):
    fields = {p["id"]: p for p in P.fields(pipe)}
    for p in pipe["params"]:
        for key, wanted in (p.get("active_when") or {}).items():
            controller = fields.get(key)
            if controller is None or controller["type"] != "select":
                continue
            assert {str(v) for v in wanted} <= set(controller["enum"]), f"{p['id']} → {key}"


def test_a_parameter_never_depends_on_itself(pipe):
    for p in pipe["params"]:
        assert p["id"] not in (p.get("active_when") or {}), p["id"]


def test_a_default_configuration_does_not_take_itself_apart(pipe):
    """Every condition has to be answerable, and settle, on the defaults alone."""
    P.inactive_ids(pipe, {})


def test_every_group_used_has_a_heading_and_every_heading_is_used(pipe):
    blurbs = set(pipe.get("param_groups") or {})
    if not blurbs:
        return
    used = {p.get("group") for p in pipe["params"] if p.get("group")}
    used.discard(None)
    assert used == blurbs


def test_a_path_field_says_what_kind_of_path_it_takes(pipe):
    for p in P.fields(pipe):
        assert p["path"] in ("", "dir", "file", "any"), p["id"]


# ── where a missing database can be got ──────────────────────────────────────
#
# DB_SOURCES is read by model/downloads.py and by nothing else, and a typo in
# it is only found when a user presses install — after the URL has already
# been fetched, or worse, after gigabytes have landed under a name timon does
# not look for.

# Every build of every database, not every entry: a database published in
# more than one (the two caps of the Kraken2 index) has a URL and an
# install_as per build, and a typo in the second would sit unnoticed while
# the first went on working. Read through downloads.variants, which is what
# normalises the two ways an entry can be written — so these check what the
# download will really use rather than what was typed.
SOURCED = [(db, build) for db in DB_SOURCES for build in downloads.variants(db)]
SOURCE_IDS = [f"{db}-{build.variant}" if build.variant else db
              for db, build in SOURCED]


@pytest.fixture(params=SOURCED, ids=SOURCE_IDS)
def declared_source(request):
    return request.param


def test_a_database_published_more_than_one_way_declares_which_to_prefer():
    """The build the install button takes when the user has said nothing. One
    that named no default would fetch whichever happened to be declared first."""
    for db, entry in DB_SOURCES.items():
        if not entry.get("variants"):
            continue
        ids = [build.variant for build in downloads.variants(db)]
        assert entry.get("default") in ids
        # The default is what variants() puts first, which is what every
        # caller that wants "the build to fetch" takes.
        assert ids[0] == entry["default"]
        assert len(ids) == len(set(ids)), f"{db}: two builds share an id"


def test_every_build_of_a_database_lands_somewhere_of_its_own():
    """Two builds installing as one name would each be found when the other
    was fetched, and the second would be refused as already there."""
    for db in DB_SOURCES:
        landings = [build.install_as for build in downloads.variants(db)]
        assert len(landings) == len(set(landings)), db


def test_a_source_names_a_database_timon_knows_about():
    assert set(DB_SOURCES) <= set(REFERENCE_DATA)


def test_the_bundle_is_made_of_databases_timon_knows_about():
    assert DATABASE_BUNDLE
    assert set(DATABASE_BUNDLE) <= set(REFERENCE_DATA)


def test_every_database_a_pipeline_reads_can_be_fetched():
    """One that cannot could only ever be reported missing, and the user left
    to find it themselves."""
    read = {key for pipe in PIPELINES.values() for key in pipe.get("reference_data", [])}
    assert read <= set(DB_SOURCES)


def test_the_whole_bundle_can_be_fetched():
    """It is one button: a member it cannot fetch would leave it stuck short."""
    assert set(DATABASE_BUNDLE) <= set(DB_SOURCES)


def test_a_source_declares_what_fetching_it_needs(declared_source):
    _, source = declared_source
    for key in ("label", "size", "url", "install_as"):
        assert getattr(source, key), key


def test_a_source_is_fetched_over_https(declared_source):
    _, source = declared_source
    assert source.url.startswith("https://")


def test_an_archive_is_declared_as_one(declared_source):
    """``archive`` is what decides whether it is unpacked, so a tarball that
    does not say so would be installed as a file no pipeline can read."""
    _, source = declared_source
    assert source.url.endswith(".tar.gz") == source.archive


def test_a_database_is_installed_under_a_name_paths_looks_for(declared_source):
    """One of the names timon will find it under: anywhere else and the
    download lands beside the place that was being filled, leaving it still
    empty. Every build of a database needs its own such name, which is why
    paths.py holds a list per database and not one name."""
    db, source = declared_source
    looked_for = {db_root() / name for name in REFERENCE_DATA[db].names}
    assert db_root() / source.install_as in looked_for


def test_a_name_paths_looks_for_is_one_something_can_be_installed_under():
    """The other direction: a name left in paths.py after the build that
    landed there was dropped would have timon looking for something nothing
    can fetch."""
    for db in DB_SOURCES:
        landings = {build.install_as for build in downloads.variants(db)}
        assert set(REFERENCE_DATA[db].names) == landings, db
