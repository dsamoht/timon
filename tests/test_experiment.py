"""The run being configured — the only thing that changes state.

The rules these cover are the ones a route or a template would otherwise be
tempted to restate: which parameters a save keeps, when a run may start, and
what happens to the sample sheet on disk.
"""

import os
import shutil
from dataclasses import replace

import pytest

from timon.app.model import history
from timon.app.model import params as P
from timon.app.model.experiment import selectable_pipelines
from timon.app.model.history import RunUnavailable
from timon.paths import REFERENCE_DATA


def configuration(experiment, **over):
    """A whole form, as the page posts it: every declared field, then changes."""
    values = P.param_defaults(experiment.pipeline)
    values.update(over)
    return values


def with_databases(experiment):
    """Install every database this pipeline reads where timon looks for it.

    Most of these tests are about something else, and a run that cannot start
    for want of a Kraken2 index would not reach the thing being tested.
    """
    for key in experiment.pipeline.get("reference_data", []):
        path = REFERENCE_DATA[key].locate()
        path.mkdir(parents=True, exist_ok=True)
        # An index Bracken can run on at the pipeline's default read length:
        # the form offers only lengths the index has a distribution for.
        if key == "kraken_db":
            (path / "database300mers.kmer_distrib").touch()
    return experiment


def rows(experiment, path, n=1):
    pipe = experiment.pipeline
    out = []
    for i in range(n):
        row = {column: "x" for column in pipe["columns"]}
        row["sample_id"] = f"sample_{i}"
        if "date" in row:
            row["date"] = "2026-01-01"
        row[pipe["file_column"]] = str(path)
        out.append(row)
    return out


# ── switching pipelines ──────────────────────────────────────────────────────

def test_an_unknown_pipeline_is_refused(experiment):
    assert experiment.set_pipeline("not-a-pipeline") is False
    assert experiment.pipeline_id == "roshab-cli"


def test_a_pipeline_that_is_not_offered_cannot_be_switched_to(experiment):
    """The picker leaves isolate-wf out; a POST naming it is the same rule."""
    assert "isolate-wf" not in selectable_pipelines()
    assert experiment.set_pipeline("isolate-wf") is False
    assert experiment.pipeline_id == "roshab-cli"


def test_every_pipeline_offered_can_be_switched_to(experiment):
    for pipeline_id in selectable_pipelines():
        assert experiment.set_pipeline(pipeline_id) is True


def test_switching_pipelines_starts_the_configuration_over(experiment, reads):
    path = reads("imports/a.fastq.gz")
    with_databases(experiment)
    experiment.apply_configuration("run_1", configuration(experiment))
    experiment.set_samples(rows(experiment, path))
    assert experiment.params and experiment.samples

    assert experiment.set_pipeline("mag-ont") is True
    assert experiment.params == {}
    assert experiment.samples == []
    assert experiment.samplesheet == ""


def test_switching_pipelines_takes_the_sheet_off_disk(experiment, reads):
    path = reads("imports/a.fastq.gz")
    experiment.set_samples(rows(experiment, path))
    sheet = experiment.samplesheet
    experiment.set_pipeline("mag-ont")
    assert not os.path.exists(sheet)


# ── saving a configuration ───────────────────────────────────────────────────

def test_a_refused_save_leaves_the_run_exactly_as_it_was(experiment):
    with_databases(experiment)
    experiment.apply_configuration("run_1", configuration(experiment))
    before = dict(experiment.params)

    assert experiment.apply_configuration("", configuration(experiment, mode="both"))
    assert experiment.exp_id == "run_1"
    assert experiment.params == before


def test_a_saved_configuration_keeps_only_what_the_run_uses(experiment):
    """Values belonging to a skipped step would describe a different run."""
    with_databases(experiment)
    experiment.apply_configuration("run_1", configuration(experiment))
    assert "chopper_minq" in experiment.params

    experiment.apply_configuration("run_1", configuration(experiment, skip_qc=True))
    assert "chopper_minq" not in experiment.params
    assert experiment.params["skip_qc"] is True


def test_a_parameter_comes_back_when_the_step_does(experiment):
    with_databases(experiment)
    experiment.apply_configuration("run_1", configuration(experiment, skip_qc=True))
    experiment.apply_configuration("run_1", configuration(experiment, skip_qc=False))
    assert "chopper_minq" in experiment.params


def test_values_are_stored_as_the_type_they_were_declared(experiment):
    with_databases(experiment)
    experiment.apply_configuration(
        "run_1", configuration(experiment, chopper_minq="12", kraken_confidence="0.05"))
    assert experiment.params["chopper_minq"] == 12
    assert experiment.params["kraken_confidence"] == 0.05


# ── whether a run may start ──────────────────────────────────────────────────

def test_the_bracken_lengths_offered_are_the_ones_the_installed_index_has(experiment):
    experiment.set_pipeline("roshab-cli")
    index = REFERENCE_DATA["kraken_db"].locate()
    index.mkdir(parents=True)
    for length in (150, 75):
        (index / f"database{length}mers.kmer_distrib").touch()

    field = next(p for p in experiment.fields() if p["id"] == "bracken_length")
    assert field["enum"] == ["75", "150"]
    assert experiment.apply_configuration(
        "run_1", configuration(experiment, bracken_length="300")) != []
    assert experiment.apply_configuration(
        "run_1", configuration(experiment, bracken_length="150")) == []
    assert experiment.params["bracken_length"] == "150"


def test_a_fresh_run_is_not_ready(experiment):
    assert experiment.is_ready() is False


def test_a_run_needs_both_a_configuration_and_a_sheet(experiment, reads):
    path = reads("imports/a.fastq.gz")
    with_databases(experiment)

    experiment.apply_configuration("run_1", configuration(experiment))
    assert experiment.is_ready() is False

    assert experiment.set_samples(rows(experiment, path)) == []
    assert experiment.is_ready() is True


def test_a_missing_database_holds_the_run_back(experiment, reads):
    """What makes the install button mandatory: a whole configuration and a
    whole sheet still wait for the databases."""
    path = reads("imports/a.fastq.gz")
    experiment.apply_configuration("run_1", configuration(experiment))
    experiment.set_samples(rows(experiment, path))
    assert experiment.is_ready() is False

    with_databases(experiment)
    assert experiment.is_ready() is True


def test_a_database_the_run_never_reads_does_not_hold_it_back(experiment, reads):
    """mag-ont skipping bin QA reads no GTDB-Tk data, so none is asked for."""
    experiment.set_pipeline("mag-ont")
    path = reads("imports/a.fastq.gz")
    experiment.apply_configuration("run_1", configuration(experiment, skip_bin_qa=True))
    experiment.set_samples(rows(experiment, path))
    assert experiment.is_ready() is True


def test_a_profile_the_pipeline_does_not_support_holds_the_run_back(experiment, reads):
    path = reads("imports/a.fastq.gz")
    with_databases(experiment)
    experiment.apply_configuration("run_1", configuration(experiment))
    experiment.set_samples(rows(experiment, path))
    experiment.profile = "podman"
    assert experiment.is_ready() is False


# ── which databases this machine is missing ──────────────────────────────────
#
# The same list answers the line in the page, the button that offers to fetch
# them and the run that refuses to start. Nobody names a database: timon looks
# where it installs them, or where a variable says a copy is.

def test_a_pipeline_asks_for_what_it_reads_and_nothing_else(experiment):
    assert experiment.needed_databases() == ["kraken_db", "genomes_db"]


def test_a_database_that_is_not_installed_is_missing(experiment):
    assert experiment.missing_databases() == ["kraken_db", "genomes_db"]


def test_a_database_that_is_installed_is_not_missing(experiment, installed):
    installed("kraken_db")
    assert experiment.missing_databases() == ["genomes_db"]


def test_a_database_the_run_never_reads_cannot_be_missing(experiment):
    """mag-ont skipping bin QA reads no GTDB-Tk data, so none is asked for."""
    experiment.set_pipeline("mag-ont")
    experiment.apply_configuration("run_1", configuration(experiment, skip_bin_qa=True))
    assert experiment.needed_databases() == []
    assert experiment.missing_databases() == []


def test_a_database_the_run_reads_after_all_is_missing_again(experiment):
    experiment.set_pipeline("mag-ont")
    experiment.apply_configuration("run_1", configuration(experiment))
    assert experiment.missing_databases() == ["gtdbtk_db"]


def test_a_database_named_outright_is_found_where_it_was_named(experiment,
                                                               db_dir, monkeypatch):
    """A copy the site already has is not downloaded again."""
    monkeypatch.setenv("KRAKEN_DB", str(db_dir))
    assert "kraken_db" not in experiment.missing_databases()
    assert experiment.database_paths()["kraken_db"] == str(db_dir)


def test_a_database_named_outright_but_not_there_is_missing(experiment, tmp_path,
                                                            installed, monkeypatch):
    """Even with one installed where timon would have looked: the variable
    decided where to look, and nothing is there."""
    installed("kraken_db")
    monkeypatch.setenv("KRAKEN_DB", str(tmp_path / "gone"))
    assert "kraken_db" in experiment.missing_databases()


def test_every_pipeline_is_pointed_at_the_installed_database(experiment, installed):
    where = installed()
    assert experiment.database_paths() == {"kraken_db": str(where["kraken_db"]),
                                           "genomes_db": str(where["genomes_db"])}
    experiment.set_pipeline("mag-ont")
    experiment.apply_configuration("run_1", configuration(experiment))
    assert experiment.database_paths() == {"gtdbtk_db": str(where["gtdbtk_db"])}


def test_a_run_is_launched_with_the_databases_it_reads(experiment, installed):
    where = installed()
    assert experiment.run_spec()["databases"]["kraken_db"] == str(where["kraken_db"])


# ── the pipeline's own test ──────────────────────────────────────────────────
#
# A test profile brings its own reads and its own databases, so what can be
# tested follows from the pipeline alone — never from the form.

def test_a_pipeline_that_ships_a_test_profile_can_be_tested(experiment):
    assert experiment.pipeline_id == "roshab-cli"
    assert experiment.is_testable() is True


def test_a_pipeline_without_one_cannot(experiment):
    experiment.set_pipeline("mag-ont")
    assert experiment.is_testable() is False


def test_a_test_is_offered_before_anything_has_been_configured(experiment):
    assert experiment.is_ready() is False
    assert experiment.is_testable() is True


def test_a_test_is_refused_on_an_engine_the_pipeline_does_not_support(experiment):
    experiment.profile = "podman"
    assert experiment.is_testable() is False


# ── the sample sheet on disk ─────────────────────────────────────────────────

def test_a_saved_sheet_holds_the_pipeline_s_columns_in_order(experiment, reads):
    path = reads("imports/a.fastq.gz")
    experiment.set_samples(rows(experiment, path, n=2))
    written = open(experiment.samplesheet).read().splitlines()
    assert written[0] == ",".join(experiment.pipeline["columns"])
    assert len(written) == 3


def test_a_refused_sheet_is_not_written(experiment):
    assert experiment.set_samples([]) != []
    assert experiment.samplesheet == ""


def test_saving_a_sheet_replaces_the_one_before_it(experiment, reads):
    path = reads("imports/a.fastq.gz")
    experiment.set_samples(rows(experiment, path))
    first = experiment.samplesheet
    experiment.set_samples(rows(experiment, path, n=2))
    assert experiment.samplesheet != first
    assert not os.path.exists(first)
    assert os.path.exists(experiment.samplesheet)


def test_resetting_takes_the_sheet_with_it(experiment, reads):
    path = reads("imports/a.fastq.gz")
    experiment.set_samples(rows(experiment, path))
    sheet = experiment.samplesheet
    experiment.reset()
    assert not os.path.exists(sheet)
    assert experiment.samples == []


# ── the scan ─────────────────────────────────────────────────────────────────

def test_a_scan_fills_the_sample_column_and_the_file_column(experiment, reads):
    reads("imports/lake_A.fastq.gz")
    scanned = experiment.scan_folder()
    assert len(scanned) == 1
    row = scanned[0]
    assert row["sample_id"] == "lake_A"
    assert row["reads"].endswith("lake_A.fastq.gz")
    assert row["group"] == ""


def test_a_scan_reads_the_folder_it_is_given_and_not_the_input_folder(experiment, reads):
    reads("imports/lake_A.fastq.gz")
    chosen = reads("drive/run_7/lake_B.fastq.gz").parent
    scanned = experiment.scan_folder(str(chosen))
    assert [row["sample_id"] for row in scanned] == ["lake_B"]


def test_a_scan_is_a_suggestion_and_is_not_written(experiment, reads):
    reads("imports/lake_A.fastq.gz")
    experiment.scan_folder()
    assert experiment.samplesheet == ""


# ── reopening a run that already happened ────────────────────────────────────
#
# A record is written by a run and handed straight back to the experiment, so
# these configure a run, record it, and reopen it on a fresh experiment — the
# same path a user takes over two sessions of timon.

def a_recorded_run(experiment, reads, session="", exp_id="past_run"):
    """Configure and save a run, then write the record a launch would."""
    path = reads("data/sample.fastq")
    with_databases(experiment)
    assert experiment.apply_configuration(exp_id, configuration(experiment)) == []
    assert experiment.set_samples(rows(experiment, path)) == []
    record = history.started(experiment.run_spec(), ["nextflow", "run", "x"])
    record = history.finished(record, history.FAILED, 1, session=session)
    if session:
        # What nextflow would have left behind, and the only thing that says
        # a run can be continued rather than started over.
        os.makedirs(os.path.join(os.getcwd(), ".nextflow", "cache", session, "db"))
    return record


def test_reopening_a_run_puts_its_whole_configuration_back(experiment, reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()

    experiment.restore(record)
    assert experiment.pinned
    assert experiment.exp_id == "past_run"
    assert experiment.pipeline_id == record.pipeline_id
    assert experiment.params == record.params
    assert experiment.database_paths() == record.databases
    assert experiment.samples == record.samples
    # The sheet is written again rather than pointed at the old one: a run
    # that can be reopened is one that can be launched.
    assert os.path.isfile(experiment.samplesheet)
    assert experiment.is_ready()


def test_a_reopened_run_whose_reads_are_gone_is_run_as_it_was(
        experiment, reads, workspace):
    """What broke is the run's to report, not a form's to refuse: running it
    again has to end on the same error it ended on."""
    record = a_recorded_run(experiment, reads)
    os.remove(workspace / "data" / "sample.fastq")
    experiment.reset()

    experiment.restore(record)
    assert experiment.samples == record.samples
    assert os.path.isfile(experiment.samplesheet)
    assert experiment.is_ready()


def test_a_reopened_run_whose_database_moved_keeps_the_path(experiment, reads,
                                                           db_dir, monkeypatch):
    """Not re-judged, and not repointed: if it is gone, nextflow says so."""
    record = a_recorded_run(experiment, reads)
    ran_with = record.databases["kraken_db"]
    shutil.rmtree(ran_with)
    monkeypatch.setenv("KRAKEN_DB", str(db_dir))
    experiment.reset()

    experiment.restore(record)
    assert experiment.run_spec()["databases"]["kraken_db"] == ran_with
    assert experiment.missing_databases() == ["kraken_db"]
    assert experiment.is_ready()


def test_a_run_recorded_before_timon_found_databases_itself_is_filled_in(
        experiment, reads):
    """An old record names only the databases a form asked for."""
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    experiment.restore(replace(record, databases={"kraken_db": "/old/kraken"}))

    spec = experiment.run_spec()["databases"]
    assert spec["kraken_db"] == "/old/kraken"
    assert spec["genomes_db"] == str(REFERENCE_DATA["genomes_db"].locate())


def test_editing_a_reopened_run_lets_go_of_its_database_paths(experiment, reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    experiment.restore(replace(record, databases={"kraken_db": "/old/kraken"}))
    experiment.unpin()
    assert experiment.database_paths()["kraken_db"] == str(REFERENCE_DATA["kraken_db"].locate())


def test_a_reopened_run_is_launched_at_the_revision_it_ran_at(experiment, reads):
    """A bumped revision is different code: neither its failure nor its cache
    is the reopened run's."""
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    history.save(replace(record, revision="0" * 40))
    experiment.restore(record)

    assert experiment.run_spec()["pipeline"]["revision"] == "0" * 40
    # Not by changing the declaration every other run reads.
    assert experiment.pipeline["revision"] != "0" * 40


def test_a_reopened_run_cannot_be_changed(experiment, reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    experiment.restore(record)
    params, samples, sheet = dict(experiment.params), experiment.samples, experiment.samplesheet

    assert experiment.set_pipeline("mag-ont") is False
    assert experiment.apply_configuration("other_run", configuration(experiment)) != []
    assert experiment.set_samples([]) != []
    assert experiment.scan_folder() == samples

    assert experiment.pipeline_id == record.pipeline_id
    assert experiment.exp_id == "past_run"
    assert experiment.params == params
    assert experiment.samples == samples
    assert experiment.samplesheet == sheet


def test_editing_a_reopened_run_makes_it_an_ordinary_configuration(experiment,
                                                                    reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    history.save(replace(record, revision="0" * 40))
    experiment.restore(record)

    experiment.unpin()
    assert not experiment.pinned
    # Everything it held is kept, and it is judged like any other save now.
    assert experiment.exp_id == "past_run"
    assert experiment.apply_configuration("past_run", configuration(experiment)) == []
    assert experiment.run_spec()["pipeline"]["revision"] == experiment.pipeline["revision"]


def test_a_reopened_run_whose_folder_is_deleted_is_no_longer_held(experiment,
                                                                   reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    experiment.restore(record)
    shutil.rmtree(record.out_dir)
    assert not experiment.pinned


def test_resetting_lets_go_of_a_reopened_run(experiment, reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    experiment.restore(record)
    experiment.reset()
    assert not experiment.pinned
    assert experiment.set_pipeline("mag-ont") is True


def test_reopening_a_run_of_a_pipeline_timon_no_longer_offers_is_refused(
        experiment, reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    with pytest.raises(RunUnavailable):
        experiment.restore(replace(record, pipeline_id="isolate-wf"))


def test_reopening_a_run_on_an_engine_the_pipeline_no_longer_declares_is_refused(
        experiment, reads):
    """It cannot be run as it ran, and quietly swapping the engine would be
    running something else."""
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    with pytest.raises(RunUnavailable):
        experiment.restore(replace(record, profile="podman"))


def test_reopening_a_run_that_is_still_going_is_refused(experiment, reads):
    record = a_recorded_run(experiment, reads)
    experiment.reset()
    with pytest.raises(RunUnavailable):
        experiment.restore(replace(record, status=history.RUNNING))


# ── continuing one ───────────────────────────────────────────────────────────

def test_a_configuration_naming_no_past_run_has_nothing_to_continue(experiment,
                                                                    reads):
    with_databases(experiment)
    experiment.apply_configuration("fresh_run", configuration(experiment))
    assert experiment.previous() is None
    assert experiment.resumable() is False
    assert experiment.resume_session() == ""


def test_a_reopened_run_is_continued_rather_than_started_over(experiment, reads):
    record = a_recorded_run(experiment, reads, session="sess-1")
    experiment.reset()
    experiment.restore(record)

    assert experiment.previous().exp_id == "past_run"
    assert experiment.resumable() is True
    assert experiment.resume_session() == "sess-1"
    assert experiment.run_spec()["resume"] == "sess-1"


def test_a_run_whose_cache_is_gone_is_not_offered_as_one_to_continue(
        experiment, reads):
    """The record outlives nextflow's cache, so having one is not enough."""
    record = a_recorded_run(experiment, reads, session="sess-1")
    shutil.rmtree(os.path.join(os.getcwd(), ".nextflow"))
    experiment.reset()
    experiment.restore(record)

    assert experiment.resumable() is False
    assert experiment.run_spec()["resume"] == ""


def test_saying_no_starts_the_run_over(experiment, reads):
    a_recorded_run(experiment, reads, session="sess-1")
    experiment.apply_configuration("past_run", configuration(experiment), resume=False)

    # There is still a run there, and it is still one nextflow could continue
    # — this configuration has simply said not to.
    assert experiment.resumable() is True
    assert experiment.resume_session() == ""


def test_the_rows_a_run_used_are_part_of_what_it_is_launched_from(experiment,
                                                                  reads):
    """Which is what makes a run reopenable at all — see model.history."""
    a_recorded_run(experiment, reads)
    assert experiment.run_spec()["samples"] == experiment.samples
    assert experiment.run_spec()["pipeline_id"] == experiment.pipeline_id


def test_a_configuration_launches_at_the_pipeline_s_tag(experiment):
    assert experiment.revision == experiment.pipeline["revision"]


def test_a_reopened_run_says_the_revision_it_will_launch_at(experiment, reads):
    record = a_recorded_run(experiment, reads)
    history.save(replace(record, revision="0" * 40))
    experiment.reset()
    experiment.restore(record)

    assert experiment.revision == "0" * 40
    assert experiment.run_spec()["pipeline"]["revision"] == experiment.revision
