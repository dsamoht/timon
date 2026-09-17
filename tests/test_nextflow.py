"""Finding nextflow, and the command line a configuration describes.

build_command is pure, so what a run *would* launch is checked here without
launching anything — which is the only way to test it at all on a machine
with no nextflow and no container engine.
"""

import subprocess
import sys

import pytest

from timon.app.model import live, nextflow, nfstate
from timon.app.model.nextflow import (WorkflowError, build_command,
                                      build_test_command, engine)

PIPE = {
    "name": "demo-pipe",
    "pipeline": "owner/demo-pipe",
    "revision": "abc123",
    "profiles": ["docker", "singularity"],
    "columns": ["sample_id"],
    "file_column": "reads",
    "reference_data": [],
    "params": [
        {"id": "mode", "type": "select", "default": "reads", "enum": ["reads", "both"]},
        {"id": "skip_qc", "type": "bool", "default": False},
        {"id": "min_len", "type": "number", "default": 500,
         "active_when": {"skip_qc": [False]}},
        {"id": "note", "type": "text", "default": ""},
    ],
}


TEST_PIPE = {**PIPE, "name": "tested-pipe", "test_profile": "test"}


def spec(**over):
    base = {
        "pipeline": PIPE,
        "exp_id": "run_1",
        "samplesheet": "/ws/timon_results/.samplesheet.csv",
        "output_folder": "/ws/timon_results",
        "profile": "docker",
        "params": {},
        "databases": {},
    }
    base.update(over)
    return base


def flag_value(cmd, flag):
    return cmd[cmd.index(flag) + 1]


# ── the engine ───────────────────────────────────────────────────────────────

def test_a_missing_nextflow_is_reported_not_raised(monkeypatch):
    """It is not a python dependency, so absent is a normal state."""
    monkeypatch.setattr(nextflow.shutil, "which", lambda _: None)
    found = engine()
    assert found.found is False
    assert found.path == ""
    assert found.binary == "nextflow"


def test_the_binary_can_be_pointed_elsewhere(monkeypatch):
    """For sites that `module load` their own."""
    monkeypatch.setenv("TIMON_NEXTFLOW", "/opt/nf/nextflow")
    monkeypatch.setattr(nextflow.shutil, "which", lambda name: name)
    assert engine().binary == "/opt/nf/nextflow"


def test_a_binary_that_cannot_be_asked_its_version_is_still_found(monkeypatch):
    monkeypatch.setattr(nextflow.shutil, "which", lambda _: "/usr/bin/nextflow")
    monkeypatch.setattr(nextflow, "_version", lambda _: "")
    found = engine()
    assert found.found is True
    assert found.version == ""


# ── the container engine ─────────────────────────────────────────────────────

@pytest.fixture
def engines(monkeypatch):
    """A machine with the named binaries on PATH, and daemons that answer.

    The daemon probe is bypassed rather than mocked at the subprocess: what
    is being tested is what timon makes of the answer, and the answer costs a
    process on a machine that may have neither engine.
    """
    def machine(*present, daemon=True):
        monkeypatch.setattr(nextflow.shutil, "which",
                            lambda name: f"/usr/bin/{name}" if name in present else None)
        monkeypatch.setattr(nextflow, "_container_version", lambda _: "")
        monkeypatch.setattr(nextflow, "_daemon_answers_now", lambda _: daemon)
    return machine


def test_a_missing_container_engine_is_reported_not_raised(engines):
    """Like nextflow, it is not something pip installed."""
    engines()
    found = nextflow.container("docker")
    assert found.found is False
    assert found.ready is False
    assert found.binary == "docker"


def test_an_engine_with_no_daemon_of_its_own_is_ready_once_it_is_there(engines):
    """Nothing to ask: apptainer runs the container in the calling process."""
    engines("apptainer")
    found = nextflow.container("apptainer")
    assert found.found is True
    assert found.daemon is None
    assert found.ready is True


def test_docker_installed_but_not_running_is_found_and_not_ready(engines):
    """The two states a laptop alternates between, and only one of them runs
    a pipeline."""
    engines("docker", daemon=False)
    found = nextflow.container("docker")
    assert found.found is True
    assert found.daemon is False
    assert found.ready is False


def test_a_profile_timon_cannot_look_for_is_ready(engines):
    """wave containerises tasks in Seqera's cloud. There is nothing here to
    find, so refusing the run would be refusing it over an unknown."""
    engines()
    found = nextflow.container("wave")
    assert found.binary == ""
    assert found.ready is True


def test_the_profile_falls_back_to_the_one_this_timon_was_configured_with(engines,
                                                                          monkeypatch):
    monkeypatch.setattr(nextflow.Config, "PROFILE", "singularity")
    engines("singularity")
    assert nextflow.container().profile == "singularity"


def test_a_daemons_answer_is_not_remembered_for_the_life_of_the_process(monkeypatch):
    """Starting Docker and reloading the page has to report the truth, which
    is the whole difference between this and the version cache."""
    answers = iter([False, True])
    calls = []

    def probe(cmd, **kw):
        calls.append(cmd)
        return type("P", (), {"returncode": 0 if next(answers) else 1})()

    monkeypatch.setattr(nextflow.subprocess, "run", probe)
    nextflow._daemon_answers.clear()
    assert nextflow._daemon_answers_now("/usr/bin/docker") is False
    # Held briefly, so a page and the saves behind it share one probe...
    assert nextflow._daemon_answers_now("/usr/bin/docker") is False
    assert len(calls) == 1
    # ...but not past that.
    monkeypatch.setattr(nextflow.time, "monotonic",
                        lambda: nextflow._daemon_answers["/usr/bin/docker"][0]
                                + nextflow.DAEMON_TTL + 1)
    assert nextflow._daemon_answers_now("/usr/bin/docker") is True


def test_an_engine_that_never_answers_is_not_one_to_start_a_run_against(monkeypatch):
    def hangs(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 20)

    monkeypatch.setattr(nextflow.subprocess, "run", hangs)
    nextflow._daemon_answers.clear()
    assert nextflow._daemon_answers_now("/usr/bin/docker") is False


# ── refusals ─────────────────────────────────────────────────────────────────

def test_an_unpinned_pipeline_refuses_to_run():
    """Two runs of the same timon version have to mean the same pipeline."""
    with pytest.raises(WorkflowError, match="no pinned revision"):
        build_command(spec(pipeline={**PIPE, "revision": None}))


def test_a_profile_the_pipeline_does_not_support_refuses_to_run():
    with pytest.raises(WorkflowError, match="does not support profile"):
        build_command(spec(profile="podman"))


def test_a_database_with_no_path_in_the_spec_is_refused():
    """Where a database is comes from the experiment; a spec without it is not
    one a run can be built from."""
    with pytest.raises(WorkflowError, match="genomes_db"):
        build_command(spec(pipeline={**PIPE, "reference_data": ["genomes_db"]}))


def test_the_command_does_not_look_at_the_disk_for_a_database():
    """Pure: whether it is there was settled before a run could start."""
    cmd = build_command(spec(pipeline={**PIPE, "reference_data": ["genomes_db"]},
                             databases={"genomes_db": "/nowhere/genomes"}))
    assert flag_value(cmd, "--genomes_db") == "/nowhere/genomes"


# ── the command ──────────────────────────────────────────────────────────────

def test_the_run_is_pinned_and_pointed_at_the_workspace():
    cmd = build_command(spec())
    assert cmd[:3] == ["nextflow", "run", "owner/demo-pipe"]
    assert flag_value(cmd, "-r") == "abc123"
    assert flag_value(cmd, "-profile") == "docker"
    assert flag_value(cmd, "--input") == "/ws/timon_results/.samplesheet.csv"
    assert flag_value(cmd, "--outdir") == "/ws/timon_results/run_1"
    assert flag_value(cmd, "-w") == "/ws/timon_results/.work"


def test_the_console_gets_the_table_nextflow_redraws_in_a_terminal():
    assert flag_value(build_command(spec()), "-ansi-log") == "true"


def test_escape_sequences_reach_the_log_without_losing_the_sites_jvm_options():
    env = nextflow.run_environment({"NXF_OPTS": "-Xms1g -Xmx4g"})
    assert env["NXF_OPTS"].split() == ["-Xms1g", "-Xmx4g", "-Djansi.passthrough=true"]
    # Launched twice from one environment, the flag is not stacked.
    assert nextflow.run_environment(env)["NXF_OPTS"] == env["NXF_OPTS"]
    assert nextflow.run_environment({})["NXF_OPTS"] == "-Djansi.passthrough=true"


def test_a_flag_that_is_off_by_default_is_set_by_naming_it():
    cmd = build_command(spec(params={"skip_qc": True}))
    assert "--skip_qc" in cmd
    # Named on its own: "--skip_qc true" would be the same run, but naming it
    # is how a nextflow boolean is set, and "false" after it would invert it.
    assert cmd[cmd.index("--skip_qc") + 1:cmd.index("--skip_qc") + 2] != ["false"]


def test_a_flag_that_is_off_by_default_and_stays_off_is_left_out():
    assert "--skip_qc" not in build_command(spec(params={"skip_qc": False}))


def test_a_flag_that_is_on_by_default_can_only_be_turned_off_explicitly():
    pipe = {**PIPE, "params": [{"id": "keep", "type": "bool", "default": True}]}
    cmd = build_command(spec(pipeline=pipe, params={"keep": False}))
    assert cmd[cmd.index("--keep") + 1] == "false"


def test_an_empty_value_is_not_put_on_the_command_line():
    """Nextflow would read it as an empty string, not as "unset"."""
    assert "--note" not in build_command(spec(params={"note": "   "}))


def test_a_value_that_starts_with_a_dash_is_joined_to_its_flag():
    """Given separately, nextflow reads `--careful` as a flag of its own and
    the parameter arrives as `true` (checked against nextflow 26.04)."""
    cmd = build_command(spec(params={"note": "--careful"}))
    assert "--note=--careful" in cmd
    assert "--note" not in cmd


def test_an_ordinary_value_still_follows_its_flag():
    assert flag_value(build_command(spec(params={"note": "a note"})), "--note") == "a note"


def test_a_number_the_pipeline_leaves_unset_stays_off_the_command_line():
    pipe = {**PIPE, "params": [{"id": "cpus", "type": "number", "default": None, "min": 1}]}
    assert not any(arg.startswith("--cpus") for arg in
                   build_command(spec(pipeline=pipe, params={"cpus": None})))


def test_a_zero_is_a_value_and_stays_on_the_command_line():
    pipe = {**PIPE, "params": [{"id": "confidence", "type": "number",
                                "step": "any", "default": 0.5}]}
    assert flag_value(build_command(spec(pipeline=pipe, params={"confidence": 0})),
                      "--confidence") == "0"


def test_a_database_the_run_reads_is_passed_under_its_flag():
    pipe = {**PIPE, "reference_data": ["kraken_db"]}
    cmd = build_command(spec(pipeline=pipe, databases={"kraken_db": "/db/k2"}))
    assert flag_value(cmd, "--kraken_db") == "/db/k2"


def test_a_database_whose_steps_this_run_skips_is_not_named():
    """Naming it would describe a run that never opens it."""
    pipe = {**PIPE, "reference_data": ["gtdbtk_db"],
            "db_optional_when": {"gtdbtk_db": ["skip_qc"]}}
    cmd = build_command(spec(pipeline=pipe, params={"skip_qc": True},
                             databases={"gtdbtk_db": "/db/gtdb"}))
    assert "--gtdbtk_db" not in cmd


# ── the ceiling this machine imposes ─────────────────────────────────────────
#
# Without one, a pipeline sized for a cluster is simply refused: nextflow
# compares the request against the machine and stops rather than scaling down.
# mag-ont asks 36 GB for a process it calls medium, so a laptop cannot run
# anything at all.

def test_the_machine_is_reported_as_the_ceiling(monkeypatch):
    monkeypatch.setattr(nextflow.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(nextflow, "_physical_memory_gb", lambda: 16)
    assert nextflow.resource_limits() == {"cpus": "8", "memory": "16.GB"}


def test_the_ceiling_can_be_overridden(monkeypatch):
    """Which is what a shared node wants: the machine's totals are not its share."""
    monkeypatch.setenv("TIMON_MAX_CPUS", "4")
    monkeypatch.setenv("TIMON_MAX_MEMORY", "8.GB")
    monkeypatch.setenv("TIMON_MAX_TIME", "2.h")
    assert nextflow.resource_limits() == {"cpus": "4", "memory": "8.GB", "time": "2.h"}


def test_a_memory_written_with_a_space_is_made_into_a_groovy_literal(monkeypatch):
    """`16 GB` is a syntax error in the config file; `16.GB` is a value."""
    monkeypatch.setenv("TIMON_MAX_MEMORY", "16 GB")
    assert nextflow.resource_limits()["memory"] == "16.GB"


def test_no_wall_clock_limit_unless_one_is_asked_for(monkeypatch):
    monkeypatch.delenv("TIMON_MAX_TIME", raising=False)
    assert "time" not in nextflow.resource_limits()


def test_a_machine_that_cannot_be_asked_its_memory_still_caps_cpus(monkeypatch):
    monkeypatch.setattr(nextflow, "_physical_memory_gb", lambda: 0)
    limits = nextflow.resource_limits()
    assert "memory" not in limits
    assert "cpus" in limits


def test_the_rendered_config_is_what_nextflow_reads():
    rendered = nextflow.render_resources({"cpus": "8", "memory": "16.GB"})
    assert "process.resourceLimits = [ cpus: 8, memory: 16.GB ]" in rendered
    assert rendered.endswith("\n")


def test_the_command_names_the_config_beside_the_sample_sheet(monkeypatch):
    monkeypatch.setattr(nextflow, "resource_limits", lambda: {"cpus": "4"})
    cmd = build_command(spec())
    assert flag_value(cmd, "-c") == "/ws/timon_results/.timon_resources.config"


def test_a_machine_with_no_ceiling_to_impose_adds_no_config(monkeypatch):
    monkeypatch.setattr(nextflow, "resource_limits", lambda: {})
    assert "-c" not in build_command(spec())


def test_building_a_command_writes_nothing(tmp_path):
    """build_command is pure — the file is written when a run actually starts."""
    build_command(spec(output_folder=str(tmp_path)))
    assert list(tmp_path.iterdir()) == []


def test_starting_a_run_writes_the_config_the_command_named(tmp_path, monkeypatch):
    monkeypatch.setattr(nextflow, "resource_limits", lambda: {"memory": "16.GB"})
    written = nextflow.write_resources_config(spec(output_folder=str(tmp_path)))
    assert written == str(tmp_path / nextflow.RESOURCES_CONFIG_NAME)
    assert "16.GB" in open(written).read()


# ── the pipeline's own test ──────────────────────────────────────────────────
#
# A smoke test of the install: the profile brings its own sample sheet and its
# own databases, so nothing the form holds may reach the command line.

def test_the_test_profile_is_run_alongside_the_container_engine():
    cmd = build_test_command(spec(pipeline=TEST_PIPE))
    assert flag_value(cmd, "-profile") == "test,docker"
    assert flag_value(cmd, "-r") == "abc123"


def test_a_test_run_passes_nothing_of_the_configuration():
    """The profile names its own input; a sheet or a flag on top of it would
    describe a different run from the one being tested."""
    cmd = build_test_command(spec(pipeline=TEST_PIPE, params={"mode": "both"},
                                  databases={"kraken_db": "/db/k2"}))
    assert "--input" not in cmd
    assert "--mode" not in cmd
    assert "--kraken_db" not in cmd


def test_a_test_run_writes_where_the_user_can_see_it():
    """Left alone it writes inside nextflow's own copy of the pipeline."""
    cmd = build_test_command(spec(pipeline=TEST_PIPE))
    assert flag_value(cmd, "--outdir") == "/ws/timon_results/tested-pipe_test"


def test_a_test_run_never_writes_over_the_run_being_configured():
    cmd = build_test_command(spec(pipeline=TEST_PIPE, exp_id="tested-pipe"))
    assert flag_value(cmd, "--outdir") != "/ws/timon_results/tested-pipe"


def test_a_pipeline_with_no_test_profile_is_refused():
    with pytest.raises(WorkflowError, match="no test profile"):
        build_test_command(spec())


def test_a_test_run_is_pinned_like_any_other():
    unpinned = {**TEST_PIPE, "revision": None}
    with pytest.raises(WorkflowError, match="pinned revision"):
        build_test_command(spec(pipeline=unpinned))


def test_a_test_run_refuses_an_engine_the_pipeline_does_not_support():
    with pytest.raises(WorkflowError, match="does not support profile"):
        build_test_command(spec(pipeline=TEST_PIPE, profile="podman"))


def test_a_test_run_is_capped_like_any_other(monkeypatch):
    """A test profile is sized for a CI runner, not for this machine."""
    monkeypatch.setattr(nextflow, "resource_limits", lambda: {"cpus": "4"})
    cmd = build_test_command(spec(pipeline=TEST_PIPE))
    assert flag_value(cmd, "-c") == "/ws/timon_results/.timon_resources.config"


def test_building_a_test_command_writes_nothing(tmp_path):
    build_test_command(spec(pipeline=TEST_PIPE, output_folder=str(tmp_path)))
    assert list(tmp_path.iterdir()) == []


# ── what the console is given ────────────────────────────────────────────────
#
# A run writes to a file and the console reads that file, so these are about
# the reading: a stand-in program stands in for nextflow, and nothing is
# installed to run them.

def run_stand_in(tmp_path, monkeypatch, body: str) -> str:
    """Read a tiny python program the way the console reads a run."""
    script = tmp_path / "stand_in.py"
    script.write_text(body)
    monkeypatch.setattr(nextflow, "build_command",
                        lambda _: [sys.executable, str(script)])
    run = nextflow.WorkflowRun()
    run.start(spec(output_folder=str(tmp_path)))
    assert run.outcome()[0] is nextflow.Outcome.FINISHED
    tail = live.Tail(run.entry.log if run.entry else
                     live.log_path(tmp_path / "run_1"))
    return "".join(tail.chunks(lambda: False, poll=0, settle=0))


def test_a_carriage_return_reaches_the_console_as_itself(tmp_path, monkeypatch):
    """It is how a progress bar redraws in place. A newline in its place
    would make a thousand lines of the same word."""
    out = run_stand_in(tmp_path, monkeypatch,
                       "import sys; sys.stdout.write('10%\\r100%\\ndone\\n')")
    assert out.endswith("10%\r100%\ndone\n")


def test_output_that_is_not_utf8_does_not_end_the_run(tmp_path, monkeypatch):
    """A pipeline's output is not timon's to be strict about."""
    out = run_stand_in(tmp_path, monkeypatch,
                       "import sys; sys.stdout.buffer.write(b'caf\\xe9\\nstill here\\n')")
    assert out.endswith("still here\n")


def test_the_log_is_where_the_run_wrote_it(tmp_path, monkeypatch):
    """In the run's own folder, and hidden from the results browser by the
    same dot rule that hides its record."""
    run_stand_in(tmp_path, monkeypatch, "print('hello')")
    log = tmp_path / "run_1" / live.LOG_NAME
    assert log.is_file() and "hello" in log.read_text()


def test_the_command_is_written_into_the_log_before_the_run(tmp_path, monkeypatch):
    """So that two attempts on one folder can be told apart in it."""
    run_stand_in(tmp_path, monkeypatch, "print('hello')")
    assert "stand_in.py" in (tmp_path / "run_1" / live.LOG_NAME).read_text()


# ── one run to a folder ──────────────────────────────────────────────────────

def test_a_second_run_is_refused_while_the_first_is_going(tmp_path, monkeypatch):
    """Two nextflows in one output folder would overwrite each other."""
    script = tmp_path / "stand_in.py"
    script.write_text("import time; time.sleep(30)")
    monkeypatch.setattr(nextflow, "build_command",
                        lambda _: [sys.executable, str(script)])
    run = nextflow.WorkflowRun()
    run.start(spec(output_folder=str(tmp_path)))
    try:
        with pytest.raises(WorkflowError, match="already running"):
            run.start(spec(output_folder=str(tmp_path)))
        other = nextflow.WorkflowRun()
        with pytest.raises(WorkflowError, match="already running"):
            other.start(spec(output_folder=str(tmp_path)))
    finally:
        run.cancel()
        run.outcome()


def test_a_run_that_is_over_leaves_nothing_claiming_to_be_going(tmp_path, monkeypatch):
    run_stand_in(tmp_path, monkeypatch, "print('done')")
    assert live.find(str(tmp_path / "run_1")) is None
    assert live.running(str(tmp_path)) == []


# ── continuing a run ─────────────────────────────────────────────────────────
#
# A restart is the same command with one flag more. What decides whether that
# flag is there is not here: the spec is handed the session to continue, or
# an empty string, and this only honours it.

def test_a_spec_naming_a_session_continues_it():
    cmd = build_command(spec(resume="sess-1"))
    assert cmd[cmd.index("-resume") + 1] == "sess-1"


def test_a_spec_with_nothing_to_continue_starts_the_run_over():
    assert "-resume" not in build_command(spec(resume=""))
    assert "-resume" not in build_command(spec())


def test_a_quick_test_never_continues_anything():
    """It is of the install, and a cached task would be the thing not tested."""
    assert "-resume" not in build_test_command({**spec(resume="sess-1"),
                                                "pipeline": TEST_PIPE})


# ── what nextflow remembers of its own runs ──────────────────────────────────

HISTORY_LINE = ("2026-09-10 21:40:41\t9m 59s\tnostalgic_curry\t{status}\tabc123\t"
                "{session}\tnextflow run owner/demo-pipe --outdir {outdir}\n")


def write_history(launch_dir, *entries, status="OK"):
    folder = launch_dir / nextflow.NEXTFLOW_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "history").write_text("".join(
        HISTORY_LINE.format(session=session, outdir=outdir, status=status)
        for session, outdir in entries))


def test_the_session_of_a_run_is_found_by_the_folder_it_wrote(tmp_path):
    write_history(tmp_path, ("sess-old", "/ws/imports/run_0"),
                  ("sess-new", "/ws/imports/run_1"))
    assert nextflow.session_id(str(tmp_path), "/ws/imports/run_1") == "sess-new"


def test_the_last_run_of_a_folder_is_the_one_that_counts(tmp_path):
    """A run continued into the same folder is the one worth continuing next."""
    write_history(tmp_path, ("sess-first", "/ws/imports/run_1"),
                  ("sess-second", "/ws/imports/run_1"))
    assert nextflow.session_id(str(tmp_path), "/ws/imports/run_1") == "sess-second"


def test_a_folder_nextflow_never_wrote_has_no_session(tmp_path):
    write_history(tmp_path, ("sess-1", "/ws/imports/run_1"))
    assert nextflow.session_id(str(tmp_path), "/ws/imports/other") == ""


def test_a_workspace_nextflow_has_never_run_in_has_no_sessions(tmp_path):
    assert nextflow.session_id(str(tmp_path), "/ws/imports/run_1") == ""


def test_a_session_can_be_continued_while_its_cache_is_there(tmp_path):
    (tmp_path / nextflow.NEXTFLOW_DIR / "cache" / "sess-1" / "db").mkdir(parents=True)
    assert nextflow.can_resume(str(tmp_path), "sess-1") is True


def test_a_session_whose_cache_is_gone_cannot_be_continued(tmp_path):
    """Which is what a workspace opened from somewhere else looks like."""
    assert nextflow.can_resume(str(tmp_path), "sess-1") is False
    assert nextflow.can_resume("", "sess-1") is False
    assert nextflow.can_resume(str(tmp_path), "") is False


def test_every_way_a_run_can_end_is_one_a_record_can_hold():
    from timon.app.model import history
    assert set(nextflow.RECORDED_AS) == set(nextflow.Outcome)
    assert set(nextflow.RECORDED_AS.values()) <= {
        history.FINISHED, history.CANCELLED, history.FAILED}


def test_a_folder_whose_name_is_the_start_of_another_is_not_it(tmp_path):
    """``run_1`` is the beginning of ``run_10``, and answering for the wrong
    one would continue a run the user never asked about."""
    write_history(tmp_path, ("sess-ten", "/ws/imports/run_10"))
    assert nextflow.session_id(str(tmp_path), "/ws/imports/run_1") == ""
    assert nextflow.session_id(str(tmp_path), "/ws/imports/run_10") == "sess-ten"


# ── how a run ended, as nextflow tells it ────────────────────────────────────
#
# Read for a run whose timon is gone: the process that should have written the
# outcome down did not live to do it, and nextflow closed its own line off
# whether or not anybody was watching.

def test_nextflow_says_a_finished_run_finished(tmp_path):
    write_history(tmp_path, ("sess-1", "/ws/imports/run_1"))
    assert nfstate.status_of(str(tmp_path), "/ws/imports/run_1") == nfstate.OK


def test_nextflow_says_a_failed_run_failed(tmp_path):
    write_history(tmp_path, ("sess-1", "/ws/imports/run_1"), status="ERR")
    assert nfstate.status_of(str(tmp_path), "/ws/imports/run_1") == nfstate.ERR


def test_a_run_nextflow_has_not_closed_off_has_no_outcome(tmp_path):
    """Which is what its line says while the run is still going."""
    write_history(tmp_path, ("sess-1", "/ws/imports/run_1"), status="-")
    assert nfstate.status_of(str(tmp_path), "/ws/imports/run_1") == ""
    assert nfstate.status_of(str(tmp_path), "/ws/imports/never") == ""
