"""What a run leaves behind, and what is read back from it.

A record is written by the run that made it and read by the page listing
past runs, so these hold both ends of that: the note lands in the folder the
run wrote, and everything about the run that a user would need to launch it
again comes back out.
"""

import json
import os
import subprocess
import sys

from timon.app.model import history, live, nfstate, results


def spec(workspace, exp_id="run_1", **over):
    base = {
        "pipeline":     {"name": "demo-pipe", "revision": "abc123"},
        "pipeline_id":  "demo-pipe",
        "exp_id":       exp_id,
        "output_folder": str(workspace / "timon_results"),
        "profile":      "docker",
        "params":       {"mode": "reads"},
        "databases":    {"kraken_db": "/db/kraken"},
        "samples":      [{"sample_id": "s1", "reads": "/reads/s1.fastq"}],
    }
    base.update(over)
    return base


def started(workspace, exp_id="run_1", **over):
    return history.started(spec(workspace, exp_id, **over), ["nextflow", "run", "x"])


# ── writing one ──────────────────────────────────────────────────────────────

def test_a_launched_run_is_recorded_in_the_folder_it_writes(workspace):
    run = started(workspace)
    assert os.path.isfile(workspace / "timon_results" / "run_1" / history.RECORD_NAME)
    assert run.status == history.RUNNING
    assert run.started_at > 0


def test_the_record_carries_what_it_takes_to_configure_the_run_again(workspace):
    started(workspace)
    run = history.load(workspace / "timon_results", "run_1")
    assert run.pipeline_id == "demo-pipe"
    assert run.revision == "abc123"
    assert run.profile == "docker"
    assert run.params == {"mode": "reads"}
    assert run.databases == {"kraken_db": "/db/kraken"}
    assert run.samples == [{"sample_id": "s1", "reads": "/reads/s1.fastq"}]


def test_the_record_is_not_one_of_the_files_the_results_browser_shows(workspace):
    """Hidden by the same dot rule a file manager uses, not by a rule of its own."""
    started(workspace)
    listing = results.listing(workspace / "timon_results", "run_1")
    assert [entry["name"] for entry in listing["entries"]] == []


def test_how_a_run_ended_is_written_down_with_the_session_it_was(workspace):
    history.finished(started(workspace), history.FAILED, 1, session="sess-1")
    run = history.load(workspace / "timon_results", "run_1")
    assert (run.status, run.exit_code, run.session) == (history.FAILED, 1, "sess-1")
    assert run.ended_at >= run.started_at
    assert run.duration >= 0


def test_a_run_recorded_twice_keeps_only_the_second(workspace):
    """Continuing a run writes over its record: one folder, one run."""
    history.finished(started(workspace), history.FAILED, 1)
    history.finished(started(workspace), history.FINISHED, 0)
    assert history.load(workspace / "timon_results", "run_1").status == history.FINISHED
    assert len(history.runs(workspace / "timon_results")) == 1


# ── reading them back ────────────────────────────────────────────────────────

def test_runs_are_listed_newest_first(workspace):
    for exp_id in ("old", "new"):
        history.finished(started(workspace, exp_id), history.FINISHED, 0)
    listed = history.runs(workspace / "timon_results")
    assert [run.exp_id for run in listed] == ["new", "old"]


def test_a_folder_with_no_record_is_not_a_run(workspace):
    """nextflow's work directory, a quick test's outputs, a folder of the
    user's own — all of them live beside the runs and none of them is one."""
    started(workspace)
    (workspace / "timon_results" / "work").mkdir()
    (workspace / "timon_results" / "demo-pipe_test").mkdir()
    assert [run.exp_id for run in history.runs(workspace / "timon_results")] == ["run_1"]


def test_a_record_that_is_not_readable_is_passed_over(workspace):
    started(workspace)
    (workspace / "timon_results" / "junk").mkdir()
    (workspace / "timon_results" / "junk" / history.RECORD_NAME).write_text("{not json")
    assert [run.exp_id for run in history.runs(workspace / "timon_results")] == ["run_1"]


def test_keys_a_record_does_not_know_about_are_dropped(workspace):
    """A workspace outlives the timon that wrote in it, in both directions."""
    started(workspace)
    path = history.record_path(workspace / "timon_results", "run_1")
    data = json.loads(path.read_text())
    path.write_text(json.dumps({**data, "invented_later": True}))
    assert history.load(workspace / "timon_results", "run_1").exp_id == "run_1"


def test_there_is_no_record_of_a_run_that_never_happened(workspace):
    assert history.load(workspace / "timon_results", "never") is None
    assert history.load(workspace / "timon_results", "") is None


def test_nothing_is_listed_for_a_workspace_with_no_output_folder(workspace):
    assert history.runs(workspace / "timon_results") == []


# ── a record left saying "running" ───────────────────────────────────────────

def test_a_run_this_timon_is_not_running_is_not_still_running(workspace):
    """A laptop closed mid-run leaves a record claiming otherwise for ever."""
    started(workspace)
    assert history.runs(workspace / "timon_results")[0].status == history.INTERRUPTED
    assert history.load(workspace / "timon_results", "run_1").status == history.INTERRUPTED


def test_the_run_this_timon_is_running_still_is(workspace):
    started(workspace)
    assert history.runs(workspace / "timon_results", active="run_1")[0].status == history.RUNNING


def test_a_restart_holds_on_to_the_session_it_is_continuing(workspace):
    """Until nextflow has given the new attempt one, which is the end of it.

    An interrupted restart that had forgotten it would be a run with cached
    work behind it and no way to say so.
    """
    history.finished(started(workspace), history.FAILED, 1, session="sess-1")
    assert started(workspace).session == "sess-1"
    assert history.load(workspace / "timon_results", "run_1").session == "sess-1"


def test_the_session_of_the_new_attempt_replaces_it_once_it_ends(workspace):
    history.finished(started(workspace), history.FAILED, 1, session="sess-1")
    history.finished(started(workspace), history.FINISHED, 0, session="sess-2")
    assert history.load(workspace / "timon_results", "run_1").session == "sess-2"


# ── a record left saying "running" by a timon that is gone ───────────────────
#
# A run outlives the timon that started it, so a record claiming to be running
# is not enough to go on and neither is this process's memory. What decides it
# is whether the nextflow behind the record is still there — and if it is not,
# what nextflow's own history says became of it.

def nextflow_history(workspace, out_dir, status="OK", session="sess-1"):
    folder = workspace / nfstate.NEXTFLOW_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "history").write_text(
        f"2026-09-10 21:40:41\t9m\tname\t{status}\tabc123\t{session}\t"
        f"nextflow run owner/demo-pipe --outdir {out_dir}\n")


def test_a_run_whose_nextflow_is_still_there_is_still_running(workspace):
    """Started by a timon that has since been closed — the run did not stop
    with it, and calling it interrupted would be simply wrong."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                            start_new_session=True)
    out_dir = str(workspace / "timon_results" / "run_1")
    live.register(live.Live(exp_id="run_1", pid=proc.pid, out_dir=out_dir,
                            output_folder=str(workspace / "timon_results"),
                            proc_start=live.process_start(proc.pid)))
    try:
        started(workspace)
        assert history.load(workspace / "timon_results", "run_1").status == history.RUNNING
    finally:
        proc.kill()
        proc.wait()


def test_a_run_that_ended_with_nobody_watching_is_read_back_from_nextflow(workspace):
    """The timon that would have written the outcome down is gone; nextflow
    closed its own line off regardless, which is a better answer than a
    shrug."""
    started(workspace)
    nextflow_history(workspace, workspace / "timon_results" / "run_1", status="OK")
    run = history.load(workspace / "timon_results", "run_1")
    assert run.status == history.FINISHED
    assert run.session == "sess-1"


def test_a_run_nextflow_says_failed_is_recorded_as_failed(workspace):
    started(workspace)
    nextflow_history(workspace, workspace / "timon_results" / "run_1", status="ERR")
    assert history.load(workspace / "timon_results", "run_1").status == history.FAILED


def test_a_run_that_left_no_trace_of_how_it_ended_is_interrupted(workspace):
    """A machine that went to sleep, or a process killed outright."""
    started(workspace)
    assert history.load(workspace / "timon_results", "run_1").status == history.INTERRUPTED


def test_the_correction_is_written_down_and_not_only_reported(workspace):
    """A record only has to be worked out once — and the session it was
    comes back with it, which is what makes an interrupted run resumable."""
    started(workspace)
    nextflow_history(workspace, workspace / "timon_results" / "run_1", status="ERR")
    history.load(workspace / "timon_results", "run_1")
    raw = json.loads((workspace / "timon_results" / "run_1" / history.RECORD_NAME).read_text())
    assert raw["status"] == history.FAILED
    assert raw["session"] == "sess-1"


def test_a_run_stopped_on_purpose_is_not_recorded_as_a_failure(workspace):
    """Nextflow's history cannot tell the two apart, so it is written down at
    the moment of stopping instead."""
    started(workspace)
    history.cancelled(workspace / "timon_results", "run_1", session="sess-9")
    run = history.load(workspace / "timon_results", "run_1")
    assert run.status == history.CANCELLED
    assert run.session == "sess-9"
