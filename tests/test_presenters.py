"""Model facts, put into the shape the page renders.

The templates are written against what these return, so the folding and the
wording are the part with real decisions in them — and they are decisions
about a page, which is why they are tested apart from the model.
"""

from datetime import datetime

import pytest

from timon.app import presenters
from timon.app.model import Container, Engine, downloads, history


def sections(experiment):
    return {s["title"]: s for s in presenters.param_sections(experiment)}


# The two engines a run needs, as this machine would report them if it had
# both. Written out rather than detected: the suite runs where neither is
# installed.
NEXTFLOW = Engine(binary="nextflow", path="/usr/bin/nextflow")
NO_NEXTFLOW = Engine(binary="nextflow")
DOCKER = Container(profile="docker", binary="docker",
                   path="/usr/bin/docker", version="Docker version 27.3.1, build ce12230",
                   daemon=True)
NO_DOCKER = Container(profile="docker", binary="docker")


# ── the engine indicator ─────────────────────────────────────────────────────

def test_a_missing_engine_says_what_to_do_about_it():
    view = presenters.engine_view(Engine(binary="nextflow"))
    assert view["ok"] is False
    assert "PATH" in view["detail"]
    assert "TIMON_NEXTFLOW" in view["detail"]


def test_a_found_engine_shows_its_version_and_where_it_is():
    view = presenters.engine_view(
        Engine(binary="nextflow", path="/usr/bin/nextflow",
               version="nextflow version 24.10.0"))
    assert view["ok"] is True
    assert view["label"] == "nextflow 24.10.0"
    assert view["detail"] == "/usr/bin/nextflow"


# ── the container indicator ──────────────────────────────────────────────────

def test_a_missing_container_engine_says_what_to_do_about_it():
    view = presenters.container_view(Container(profile="docker", binary="docker"))
    assert view["ok"] is False
    assert view["label"] == "docker not found"
    assert "PATH" in view["detail"]
    assert "TIMON_PROFILE" in view["detail"]


def test_an_engine_that_is_installed_but_down_is_not_a_missing_one():
    """The commonest state of a laptop, and a different errand entirely."""
    view = presenters.container_view(
        Container(profile="docker", binary="docker", path="/usr/local/bin/docker",
                  version="Docker version 27.3.1, build ce12230", daemon=False))
    assert view["ok"] is False
    assert view["label"] == "docker not running"
    assert "start it" in view["detail"]


def test_a_running_engine_shows_its_version_under_its_profile_name():
    """Its own version line is three words and a build hash; the number is
    the only part a tile has room for."""
    view = presenters.container_view(
        Container(profile="docker", binary="docker", path="/usr/local/bin/docker",
                  version="Docker version 27.3.1, build ce12230", daemon=True))
    assert view["ok"] is True
    assert view["label"] == "docker 27.3.1"
    assert view["detail"] == "/usr/local/bin/docker"


def test_an_engine_with_no_version_to_give_is_still_reported_ready():
    view = presenters.container_view(
        Container(profile="singularity", binary="singularity",
                  path="/usr/bin/singularity"))
    assert view["ok"] is True
    assert view["label"] == "singularity ready"


def test_a_profile_with_nothing_local_is_not_reported_as_an_approval():
    """timon checked nothing, and the tile says so rather than a version."""
    view = presenters.container_view(Container(profile="wave"))
    assert view["ok"] is True
    assert "nothing for timon to look for" in view["detail"]


# ── paths as they read ───────────────────────────────────────────────────────

def test_a_path_under_home_is_shortened(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert presenters.display_path(tmp_path / "projects" / "bloom") == "~/projects/bloom"


def test_a_path_elsewhere_is_left_alone(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert presenters.display_path("/mnt/reads") == "/mnt/reads"


# ── the form ─────────────────────────────────────────────────────────────────

def test_a_folded_section_still_renders_its_fields(experiment):
    """Otherwise a parameter would not be submitted, and would silently reset."""
    for section in presenters.param_sections(experiment):
        assert section["fields"] or section["flags"]


def test_a_database_is_never_a_field_of_the_form(experiment):
    """timon finds it; there is nothing for the user to type."""
    ids = {f["id"] for s in presenters.param_sections(experiment)
           for f in s["fields"] + s["flags"]}
    assert not ids & {"kraken_db", "gtdbtk_db", "genomes_db"}


def test_a_value_that_is_not_the_default_opens_its_section(experiment):
    assert sections(experiment)["read QC"]["open"] is False
    experiment.params = {"chopper_minq": 20}
    assert sections(experiment)["read QC"]["open"] is True


def test_a_section_belonging_to_a_route_this_run_does_not_take_is_inactive(experiment):
    """The `reads` mode never assembles, so the assembly heading is empty."""
    experiment.params = {"mode": "reads"}
    assert sections(experiment)["assembly"]["active"] is False
    experiment.params = {"mode": "both"}
    assert sections(experiment)["assembly"]["active"] is True


def test_the_first_section_still_standing_is_where_the_form_starts(experiment):
    open_sections = [s for s in presenters.param_sections(experiment)
                     if s["active"] and s["open"]]
    assert open_sections
    assert open_sections[0]["title"] == "workflow"


# ── the databases card ───────────────────────────────────────────────────────

def test_a_fresh_install_offers_the_button_and_says_the_run_is_waiting(experiment):
    view = presenters.databases_view(experiment)
    assert view["installed"] is False
    assert view["can_install"] is True
    assert view["holding"] == ["Kraken2 database", "genome database"]
    assert [row["key"] for row in view["bundle"]] == ["kraken_db", "genomes_db"]


def test_an_installed_bundle_freezes_the_button(experiment, installed):
    installed("kraken_db", "genomes_db")
    view = presenters.databases_view(experiment)
    assert view["installed"] is True
    assert view["can_install"] is False
    assert view["holding"] == []
    assert all(row["present"] for row in view["bundle"])


def test_the_button_is_still_offered_while_one_of_the_two_is_there(experiment, installed):
    """Pressing it again after one download failed fetches the other."""
    installed("kraken_db")
    view = presenters.databases_view(experiment)
    assert view["installed"] is False
    assert view["can_install"] is True
    assert view["holding"] == ["genome database"]


def test_a_database_nothing_can_fetch_names_the_variable_instead(experiment, monkeypatch):
    """A source can be withdrawn — a URL that goes dead is a config.py edit —
    and the row still has something to say."""
    monkeypatch.delitem(downloads.DB_SOURCES, "genomes_db")
    view = presenters.databases_view(experiment)
    genomes = next(row for row in view["bundle"] if row["key"] == "genomes_db")
    assert genomes["env"] == "TIMON_GENOMES_DB"
    assert "nowhere declared" in genomes["reason"]
    assert genomes["can_install"] is False


def test_a_database_published_in_two_builds_offers_the_choice(experiment):
    """The Kraken2 index is capped at 8 GB or at 16 GB, and which to fetch is
    the user's — the row draws a choice only where there is one to make."""
    view = presenters.databases_view(experiment)
    kraken = next(row for row in view["bundle"] if row["key"] == "kraken_db")
    genomes = next(row for row in view["bundle"] if row["key"] == "genomes_db")

    assert [build["id"] for build in kraken["variants"]] == ["16GB", "8GB"]
    assert all(build["size"] and build["note"] for build in kraken["variants"])
    # Published one way, so there is nothing to choose between.
    assert genomes["variants"] == []


def test_the_row_says_what_it_would_fetch_and_not_what_it_would_have(experiment):
    """Picking the smaller build changes the size on the row: a card that went
    on showing 11.1 GB would be describing a download nobody asked for."""
    default = presenters.databases_view(experiment)
    chosen = presenters.databases_view(experiment, {"kraken_db": "8GB"})

    was = next(row for row in default["bundle"] if row["key"] == "kraken_db")
    now = next(row for row in chosen["bundle"] if row["key"] == "kraken_db")
    assert was["variant"] == "16GB" and now["variant"] == "8GB"
    assert was["size"] != now["size"]
    # And the path with it: a row saying 5.5 GB while pointing at where the
    # 11.1 GB build would land describes a download that is not going to
    # happen.
    assert was["where"] != now["where"]
    assert now["where"].endswith("k2_pluspf_08_GB_20260626")


def test_a_database_pointed_elsewhere_keeps_saying_where(experiment, monkeypatch, tmp_path):
    """The path is the actionable half of that row — it is the value the user
    set and has to fix — so a build chosen in the card does not replace it."""
    monkeypatch.setenv("KRAKEN_DB", str(tmp_path / "moved"))
    view = presenters.databases_view(experiment, {"kraken_db": "8GB"})
    kraken = next(row for row in view["bundle"] if row["key"] == "kraken_db")

    assert kraken["where"].endswith("moved")
    assert "KRAKEN_DB" in kraken["reason"]


def test_a_build_nobody_declared_falls_back_to_the_default(experiment):
    """The choice comes off a request, so it can say anything at all. The row
    then describes the default and offers to fetch it — saying one thing and
    doing another is the failure worth avoiding here."""
    view = presenters.databases_view(experiment, {"kraken_db": "enormous"})
    kraken = next(row for row in view["bundle"] if row["key"] == "kraken_db")
    assert kraken["variant"] == "16GB"
    assert kraken["can_install"] is True
    assert kraken["reason"] == ""


def test_a_database_outside_the_bundle_is_offered_only_to_a_run_that_reads_it(experiment):
    experiment.set_pipeline("mag-ont")
    assert [row["key"] for row in presenters.databases_view(experiment)["extra"]] == ["gtdbtk_db"]

    experiment.params = {"skip_bin_qa": True}
    view = presenters.databases_view(experiment)
    assert view["extra"] == []
    assert view["holding"] == []


# ── the run ──────────────────────────────────────────────────────────────────

def test_the_button_and_the_model_give_one_answer(experiment, configured):
    configured(experiment)

    assert presenters.run_view(experiment, NEXTFLOW, DOCKER)["can_start"] is True
    # A ready run with nothing to launch it is still not one that can start.
    assert presenters.run_view(experiment, NO_NEXTFLOW, DOCKER)["can_start"] is False
    # Nor one with nothing to run its tasks inside: it would start, and die
    # in the first task.
    assert presenters.run_view(experiment, NEXTFLOW, NO_DOCKER)["can_start"] is False


def test_a_run_is_configured_before_it_is_ready(experiment):
    from timon.app.model import params as P
    experiment.apply_configuration("run_1", P.param_defaults(experiment.pipeline))

    view = presenters.run_view(experiment, NO_NEXTFLOW, DOCKER)
    assert view["configured"] is True
    assert view["ready"] is False


def test_a_quick_test_is_offered_for_the_pipeline_that_ships_one(experiment):
    """And with no configuration at all — that is the point of it."""
    view = presenters.run_view(experiment, NEXTFLOW, DOCKER)
    assert view["can_test"] is True
    assert view["can_start"] is False


def test_no_quick_test_for_a_pipeline_without_one(experiment):
    experiment.set_pipeline("mag-ont")
    assert presenters.run_view(experiment, NEXTFLOW, DOCKER)["can_test"] is False


def test_no_quick_test_without_nextflow(experiment):
    """It is a nextflow run like any other."""
    assert presenters.run_view(experiment, NO_NEXTFLOW, DOCKER)["can_test"] is False


def test_no_quick_test_without_a_container_engine(experiment):
    """It answers whether the install works, and half an install does not."""
    assert presenters.run_view(experiment, NEXTFLOW, NO_DOCKER)["can_test"] is False


def test_a_profile_timon_cannot_look_for_holds_nothing_up(experiment, configured):
    """An unknown is not a refusal: wave containerises in Seqera's cloud, so
    there is nothing on this machine to find and nothing to wait for."""
    configured(experiment)
    wave = Container(profile="wave")
    assert presenters.run_view(experiment, NEXTFLOW, wave)["can_start"] is True


def test_the_picker_only_offers_pipelines_that_can_be_picked(experiment, workspace):
    view = presenters.index_view(experiment, NO_NEXTFLOW, NO_DOCKER, "0", "2026")
    assert "roshab-cli" in view["pipelines"]
    assert "isolate-wf" not in view["pipelines"]


# ── the results browser ──────────────────────────────────────────────────────

def test_a_size_is_written_the_way_a_person_reads_one():
    assert presenters.size_label(0) == "0 B"
    assert presenters.size_label(900) == "900 B"
    assert presenters.size_label(2048) == "2.0 KB"
    assert presenters.size_label(20 * 1024) == "20 KB"
    assert presenters.size_label(5 * 1024 ** 3) == "5.0 GB"


def test_a_folder_has_no_size_to_show():
    assert presenters.size_label(None) == ""
    assert presenters.when(None) == ""


def test_every_kind_gets_a_mark_of_its_own():
    """Two kinds sharing a glyph would make the listing say less than it knows."""
    glyphs = presenters.KIND_GLYPHS
    assert len(set(glyphs.values())) == len(glyphs)


def test_the_run_being_configured_is_marked_only_at_the_top(tmp_path):
    from timon.app.model import results
    (tmp_path / "exp1").mkdir()
    (tmp_path / "exp1" / "exp1").mkdir()

    top = presenters.results_view(results.listing(tmp_path), "exp1")
    assert [e["current"] for e in top["entries"]] == [True]

    # The same name one level down is a folder a pipeline happened to write.
    inside = presenters.results_view(results.listing(tmp_path, "exp1"), "exp1")
    assert [e["current"] for e in inside["entries"]] == [False]


def test_a_run_that_was_never_named_marks_nothing(tmp_path):
    from timon.app.model import results
    (tmp_path / "exp1").mkdir()
    view = presenters.results_view(results.listing(tmp_path), "")
    assert [e["current"] for e in view["entries"]] == [False]


# ── past runs ────────────────────────────────────────────────────────────────

def test_how_long_ago_is_said_the_way_a_person_says_it():
    now = datetime.now().timestamp()
    assert presenters.since(now - 10) == "just now"
    assert presenters.since(now - 5 * 60) == "5 min ago"
    assert presenters.since(now - 3 * 3600) == "3 h ago"
    assert presenters.since(now - 26 * 3600) == "yesterday"
    assert presenters.since(now - 3 * 86400) == "3 days ago"


def test_past_a_week_the_date_itself_is_what_tells_two_runs_apart():
    old = datetime.now().timestamp() - 30 * 86400
    assert presenters.since(old) == presenters.when(old)


def test_a_run_that_never_started_has_no_age():
    assert presenters.since(0) == ""


def test_how_long_a_run_took_is_written_in_nextflow_s_units():
    assert presenters.duration_label(42) == "42s"
    assert presenters.duration_label(599) == "9m 59s"
    assert presenters.duration_label(3 * 3600 + 25 * 60) == "3h 25m"
    # Still running: there is nothing to say yet.
    assert presenters.duration_label(0) == ""


def test_a_row_carries_the_word_and_the_mark_for_how_a_run_ended():
    row = presenters.run_row(history.Run(exp_id="past", pipeline_id="roshab-cli",
                                         status=history.FAILED, started_at=1.0))
    assert row["status"]["label"] == "failed"
    assert row["status"]["tone"] == "bad"
    assert row["rel"] == "past"
    assert row["current"] is False


def test_the_run_being_configured_is_the_one_marked_in_the_list():
    record = history.Run(exp_id="past", status=history.FINISHED, started_at=1.0)
    assert presenters.run_row(record, "past")["current"] is True


def test_a_configuration_naming_no_past_run_has_nothing_to_say_about_one(experiment):
    view = presenters.restart_view(experiment)
    assert view["previous"] is False
    assert view["can_resume"] is False


# ── the version beside the pipeline ──────────────────────────────────────────

def test_a_release_tag_is_shown_as_it_is():
    assert presenters.revision_label("v0.1.0") == "v0.1.0"


def test_a_commit_a_run_was_recorded_at_is_shortened():
    """Runs from before the tags were pinned to a full commit."""
    assert presenters.revision_label("83c51339c17614783f3f425f4fcd32f1123c3134") == "83c5133"


# ── timon's own version ──────────────────────────────────────────────────────
#
# The version is the git tag (hatch-vcs), so the brand can link at the release
# it names — as long as there is one. A build made between tags is not a
# release and must not claim a page of its own.

@pytest.mark.parametrize("version", ["0.1.0", "1.2.3", "1.0.0rc1", "0.2.0.post1"])
def test_a_released_version_links_to_its_own_release(version):
    assert presenters.release_url(version).endswith(f"/releases/tag/v{version}")


@pytest.mark.parametrize("version", [
    "0.1.1.dev2+g3fc222c",   # built between tags
    "0.1.0+dirty",           # built off an edited tree
    "0+unknown",             # a source tree that was never installed
    "",                      # nothing to go on at all
])
def test_a_version_with_no_release_behind_it_links_to_the_list(version):
    assert presenters.release_url(version).endswith("/releases")


# ── numbers in the form ──────────────────────────────────────────────────────

@pytest.mark.parametrize("value, shown", [
    (0.00001, "0.00001"), (1e-7, "0.0000001"), (0.5, "0.5"), (90.0, "90"), (500000, "500000"),
    ("0.25", "0.25"), (None, ""), ("nan", ""), (float("inf"), ""),
])
def test_a_number_is_written_the_way_the_form_reads_one(value, shown):
    """No exponent and no comma: a saved run must reopen with values the form accepts."""
    assert presenters.number_text(value) == shown
