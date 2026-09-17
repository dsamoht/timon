"""Runs in flight: what is going, and how a timon that did not start it knows.

A run outlives the timon that launched it, so "is it still running" cannot be
answered by this process remembering that it started something. It is asked of
the operating system, and these are about that answer being trustworthy: a
recycled pid must not pass for a run, a pointer left behind by a timon that
crashed must not either, and a run started in one workspace has to be findable
from another.

Nothing here launches nextflow. A short-lived python program stands in for it,
which is all a pid and a log file need to be real.
"""

import os
import subprocess
import sys
import time

import pytest

from timon.app.model import live


def sleeper(seconds: float = 30) -> subprocess.Popen:
    """A process that will still be there when it is asked about."""
    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


@pytest.fixture
def process():
    started = []

    def make(seconds: float = 30) -> subprocess.Popen:
        proc = sleeper(seconds)
        started.append(proc)
        return proc

    yield make
    for proc in started:
        proc.kill()
        proc.wait()


def entry(proc, out_dir, **over) -> live.Live:
    base = dict(exp_id="run_1", pid=proc.pid, out_dir=str(out_dir),
                launch_dir="/ws", output_folder=str(out_dir) + "/..",
                log=live.log_path(out_dir), started_at=time.time(),
                proc_start=live.process_start(proc.pid))
    base.update(over)
    return live.Live(**base)


# ── whether a run is going ───────────────────────────────────────────────────

def test_a_process_that_is_there_is_a_run_that_is_going(tmp_path, process):
    assert live.alive(entry(process(), tmp_path / "run_1")) is True


def test_a_process_that_has_ended_is_a_run_that_is_over(tmp_path, process):
    proc = process(0.01)
    one = entry(proc, tmp_path / "run_1")
    proc.wait()
    assert live.alive(one) is False


def test_an_entry_with_no_process_behind_it_is_not_going(tmp_path):
    assert live.alive(live.Live(exp_id="x", pid=0, out_dir=str(tmp_path))) is False


def test_a_pid_handed_out_again_is_not_the_run_that_had_it(tmp_path, process):
    """The number comes back around; the moment it started does not.

    This is the failure the whole check exists for: a laptop left running
    for weeks will reissue the pid of a run that ended, and a run reported
    as going would lock the page against a workflow nobody could stop.
    """
    proc = process()
    impostor = entry(proc, tmp_path / "run_1",
                     proc_start="Mon Jan  1 00:00:00 2001")
    assert live.alive(impostor) is False


# ── the pointer a run leaves ─────────────────────────────────────────────────

def test_a_registered_run_is_found_by_the_folder_it_writes(tmp_path, process):
    one = live.register(entry(process(), tmp_path / "run_1"))
    assert live.find(one.out_dir).pid == one.pid


def test_a_run_that_is_over_is_not_found_and_its_pointer_goes(tmp_path, process):
    """A timon that crashed leaves the pointer behind; the next one clears it."""
    proc = process(0.01)
    one = live.register(entry(proc, tmp_path / "run_1"))
    proc.wait()
    assert live.find(one.out_dir) is None
    assert live.running() == []
    assert list(live.registry().glob("*.json")) == []


def test_a_run_is_found_from_a_workspace_it_was_not_started_in(tmp_path, process):
    """Which is the whole reason the pointers are not kept in the workspace."""
    one = live.register(entry(process(), tmp_path / "elsewhere" / "run_1",
                              output_folder=str(tmp_path / "elsewhere")))
    assert [e.exp_id for e in live.running()] == ["run_1"]
    assert live.running(str(tmp_path / "here")) == []
    assert [e.exp_id for e in live.running(one.output_folder)] == ["run_1"]


def test_forgetting_a_run_leaves_nothing_behind(tmp_path, process):
    one = live.register(entry(process(), tmp_path / "run_1"))
    live.forget(one)
    assert live.find(one.out_dir) is None


# ── stopping one ─────────────────────────────────────────────────────────────

def test_stopping_a_run_ends_it(tmp_path, process):
    proc = process()
    assert live.stop(entry(proc, tmp_path / "run_1")) is True
    assert proc.poll() is not None


def test_stopping_reaches_what_the_run_started(tmp_path):
    """Nextflow's tasks are the run as much as nextflow is.

    A run is launched into a session of its own precisely so that stopping
    it can be sent to the whole group. Killing only the process on top would
    leave the tasks holding the machine with nothing left that knows about
    them.
    """
    parent = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess, sys, time;"
         "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
         "print(child.pid, flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE, text=True, start_new_session=True)
    child_pid = int(parent.stdout.readline().strip())
    try:
        live.stop(live.Live(exp_id="run_1", pid=parent.pid, out_dir=str(tmp_path),
                            proc_start=live.process_start(parent.pid)))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.2)
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        parent.kill()
        parent.wait()


# ── reading the log ──────────────────────────────────────────────────────────

def test_the_tail_reads_a_log_that_is_already_written(tmp_path):
    log = tmp_path / live.LOG_NAME
    log.write_bytes(b"one\ntwo\n")
    assert "".join(live.Tail(log).chunks(lambda: False, poll=0, settle=0)) == "one\ntwo\n"


def test_the_tail_keeps_reading_while_the_run_is_going(tmp_path):
    """What a page attaching to a run in progress is doing."""
    log = tmp_path / live.LOG_NAME
    log.write_bytes(b"first\n")
    passes = [2]

    def alive_now():
        # Going for two more passes, then over: long enough for what was
        # appended below to be picked up after the first read hit the end.
        passes[0] -= 1
        return passes[0] > 0

    with open(log, "ab") as handle:
        handle.write(b"second\n")
    assert "".join(live.Tail(log).chunks(alive_now, poll=0, settle=0)) \
        == "first\nsecond\n"


def test_only_the_end_of_a_long_log_is_replayed(tmp_path):
    """A day-long run writes more than a browser should be handed at once."""
    log = tmp_path / live.LOG_NAME
    log.write_bytes(b"early\n" + b"x" * 4096 + b"\nthe end\n")
    out = "".join(live.Tail(log, replay=16).chunks(lambda: False, poll=0, settle=0))
    assert out == "the end\n"


def test_a_replayed_log_starts_at_a_line_and_not_mid_word(tmp_path):
    """Coming in at an arbitrary byte could open the console on half an
    escape sequence, which is printed rather than obeyed."""
    log = tmp_path / live.LOG_NAME
    log.write_bytes(b"a line that is long enough to be cut\nand another\n")
    out = "".join(live.Tail(log, replay=20).chunks(lambda: False, poll=0, settle=0))
    assert out == "and another\n"


def test_a_process_that_has_ended_but_not_been_collected_is_not_a_run(tmp_path):
    """The moment between a run ending and its timon waiting on the process.

    A zombie still answers to its pid, and counting it as a run would leave
    the page locked against a workflow that is already over.
    """
    proc = sleeper(0.01)
    one = entry(proc, tmp_path / "run_1")
    time.sleep(0.5)
    try:
        assert live.alive(one) is False
    finally:
        proc.wait()


def test_a_log_that_is_not_there_reads_as_nothing(tmp_path):
    assert list(live.Tail(tmp_path / "gone.log").chunks(lambda: False)) == []
