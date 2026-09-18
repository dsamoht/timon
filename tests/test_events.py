"""The console, over a real Socket.IO client.

What is tested here is the one thing the socket adds over the model: a page
is never streaming a run, it is told what is running and then sent that run's
log. Which makes closing the browser mid-run — and opening it again, and
opening a second one beside it — something the page can be put through rather
than argued about.

Nothing installs nextflow. A short python program stands in for it, which is
all a pid and a log need to be real.
"""

import sys
import time

import pytest

from timon.app import model, socketio as sio
from timon.app.model import nextflow
from timon.app.model.experiment import Experiment

# Long enough to still be going while the page is closed and reopened, short
# enough that a test which loses control of it is not a nuisance.
STAND_IN = ("import sys, time\n"
            "print('N E X T F L O W', flush=True)\n"
            "for i in range(60):\n"
            "    print('[%02d/abc] process > DEMO' % i, flush=True)\n"
            "    time.sleep(0.2)\n")


@pytest.fixture
def console(app, workspace, configured, monkeypatch):
    """A configured run over a stand-in nextflow, and a page watching it.

    Filled in through the same Experiment methods the form posts to, which is
    the shortest honest way to a run that is ready to start.
    """
    experiment = Experiment()
    monkeypatch.setattr(model, "EXPERIMENT", experiment)
    monkeypatch.setattr(model, "RUN", nextflow.WorkflowRun())

    script = workspace / "stand_in.py"
    script.write_text(STAND_IN)
    monkeypatch.setattr(nextflow, "build_command",
                        lambda _: [sys.executable, str(script)])
    monkeypatch.setattr(nextflow, "build_test_command",
                        lambda _: [sys.executable, str(script)])

    configured(experiment)
    assert experiment.is_ready()

    clients = []

    def open_page():
        client = sio.test_client(app)
        clients.append(client)
        client.get_received()      # the state sent on connect
        return client

    yield open_page, experiment

    model.RUN.cancel()
    model.RUN.outcome()
    for client in clients:
        if client.is_connected():
            client.disconnect()


def wait_for(client, event: str, timeout: float = 20.0) -> dict:
    """The next message of this kind, or a failure that says what came instead."""
    seen = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for message in client.get_received():
            seen.append(message["name"])
            if message["name"] == event:
                return message["args"][0]
        time.sleep(0.1)
    raise AssertionError(f"no {event!r} within {timeout}s; saw {seen}")


def collect(client, seconds: float = 2.0) -> tuple[str, list]:
    """Everything one page is sent for a moment: its output, and its states."""
    text, states = "", []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for message in client.get_received():
            if message["name"] == "workflow_output":
                text += message["args"][0]["data"]
            elif message["name"] == "run_state":
                states.append(message["args"][0])
        time.sleep(0.1)
    return text, states


def start(page) -> dict:
    page.emit("run_workflow")
    return wait_for(page, "run_state")


# ── what a page is told ──────────────────────────────────────────────────────

def test_a_page_that_connects_to_nothing_is_told_so(console):
    open_page, experiment = console
    page = open_page()
    page.emit("attach", {})
    state = wait_for(page, "run_state")
    assert state["running"] is False
    assert state["can_start"] is True


def test_a_started_run_locks_the_page_and_reaches_the_console(console):
    open_page, experiment = console
    page = open_page()
    assert start(page)["running"] is True
    text, _ = collect(page)
    assert "N E X T F L O W" in text


def test_every_page_open_is_told_a_run_has_started(console):
    """Two tabs on one workspace are two views of one run."""
    open_page, experiment = console
    page, other = open_page(), open_page()
    start(page)
    state = wait_for(other, "run_state")
    assert state["running"] is True
    assert state["can_start"] is False


def test_a_reopened_run_that_failed_shows_its_own_error(console, workspace):
    """With nothing going, a page is sent the end of the last run of this
    identifier — for a run reopened to be run again, the error it ended on,
    rather than anything the page might say about it."""
    open_page, experiment = console
    log = workspace / "failed.log"
    log.write_text("N E X T F L O W\nERROR ~ Process `KRAKEN2` terminated with an error\n")
    record = model.history.started(experiment.run_spec(), ["nextflow"], log=str(log))
    model.history.finished(record, model.history.FAILED, 1)
    experiment.restore(model.history.load(experiment.output_folder, experiment.exp_id))

    page = open_page()
    page.emit("attach", {})
    replay = wait_for(page, "replay")
    assert replay["id"] == experiment.exp_id
    assert replay["status"]["label"] == "failed"
    assert "ERROR ~ Process `KRAKEN2`" in replay["data"]


# ── closing the browser ──────────────────────────────────────────────────────

def test_closing_the_browser_leaves_the_run_going(console):
    open_page, experiment = console
    page = open_page()
    start(page)
    collect(page, 1.0)
    page.disconnect()
    time.sleep(1.0)
    assert [entry.exp_id for entry in experiment.in_flight()] == [experiment.exp_id]


def test_a_page_opened_again_mid_run_is_given_the_run_and_its_output(console):
    """The whole of what recovering a run is: the page asks what is going,
    and is sent the log from a little way back rather than from whatever
    happens to be written next."""
    open_page, experiment = console
    page = open_page()
    start(page)
    collect(page, 1.0)
    page.disconnect()

    reopened = open_page()
    reopened.emit("attach", {})
    state = wait_for(reopened, "run_state")
    assert state["running"] is True
    assert state["run"]["id"] == experiment.exp_id
    assert state["run"]["mine"] is True
    assert state["can_start"] is False
    text, _ = collect(reopened)
    assert "N E X T F L O W" in text


def test_a_page_is_not_sent_the_same_run_twice(console):
    """It asks to be attached whenever it learns something is running, and it
    learns that from more than one direction."""
    open_page, experiment = console
    page = open_page()
    start(page)
    page.emit("attach", {"exp_id": experiment.exp_id})
    page.emit("attach", {"exp_id": experiment.exp_id})
    text, _ = collect(page, 2.0)
    assert text.count("N E X T F L O W") == 1


# ── starting one twice ───────────────────────────────────────────────────────

def test_a_second_run_is_refused_while_one_is_going(console):
    open_page, experiment = console
    page = open_page()
    start(page)
    page.emit("run_workflow")
    text, _ = collect(page, 2.0)
    assert "already running" in text


# ── stopping one ─────────────────────────────────────────────────────────────

def test_stopping_a_run_ends_it_and_says_how_it_ended(console):
    open_page, experiment = console
    page = open_page()
    start(page)
    collect(page, 1.0)
    page.emit("cancel_workflow", {"exp_id": experiment.exp_id})

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        _, states = collect(page, 1.0)
        if states and states[-1]["running"] is False:
            break
    assert states[-1]["running"] is False
    assert states[-1]["can_start"] is True
    assert experiment.in_flight() == []
    assert model.history.load(experiment.output_folder, experiment.exp_id).status \
        == model.history.CANCELLED
