"""Socket.IO surface: the console, and the buttons that start and stop a run.

The other half of the view. It starts a run, forwards what nextflow is
saying and puts the end of it into the words the terminal shows — it does
not decide whether a run may start, what argv it gets, whether a run is
still going or whether being stopped counts as cancelled. Those are
``model.EXPERIMENT``'s, ``model.RUN``'s and ``model.live``'s answers.

What shapes this file is that a run belongs to the machine rather than to
this page, or even to this timon: it is launched in a session of its own and
writes to a file, so it survives the browser being closed and the server
being quit. A console that owned a pipe could not survive either. So nothing
here streams a run — it *watches* one, by reading the log of whichever run
is going, and that is the same act whether this timon started the run or
found it already in progress.

The page is therefore never sent a stream it has to keep up with. It is sent
a state: what is running, and what it has said so far.
"""

import os
import threading
import time

from flask import request
from flask_socketio import emit

from . import model, presenters, socketio

# How often the operating system is asked whether the run being watched is
# still going. The asking costs a subprocess and the watching is a loop, so
# it happens on a timer rather than on every pass through it.
LIVENESS_EVERY = 3.0

# The model reports an Outcome; the wording for it is here, next to the rest
# of the console's voice.
# Which run each page is being sent, by socket id. Only ever consulted to
# avoid starting a second watcher for a page that already has one.
WATCHING: dict[str, str] = {}

STOPPING_LINE  = "\n[Stopping the workflow — waiting for nextflow to take its tasks down]\n"
CANCELLED_LINE = "[Workflow stopped]\n"


def _target(exp_id: str = ""):
    """The run the page is asking about: the one it named, or this workspace's.

    A named run is looked for on the whole machine and not only in this
    workspace, because a run named by the page is one the page is showing —
    and the runs view shows what is going elsewhere too, so that a workflow
    started in a folder the user has since left is not lost to them.

    Unnamed, it is this workspace's run: that is the one the console shows
    and the one the run button is locked by, and a workspace is what a
    timon is open on.

    Either way the answer comes from the runs actually going rather than
    from the list of past ones, because this is only ever asked in order to
    watch or to stop something, and neither can be done to a run that is
    over.
    """
    entries = model.EXPERIMENT.in_flight()
    if not exp_id:
        return entries[0] if entries else None
    everywhere = entries + [entry for entry in model.live.running()
                            if entry not in entries]
    return next((entry for entry in everywhere if entry.exp_id == exp_id), None)


def _state(entry=None, over=None) -> dict:
    """What is running, for a page that has just asked or has just been told.

    The same shape the page was given when it loaded, built by the same
    presenter: a page has one way of being told about a run, and it does
    not matter which of the two brought the news.

    ``over`` is the run that has just stopped, if one has, and its record is
    read from the workspace *it* belongs to — which is not necessarily this
    one, since a page can watch a run started in another folder.
    """
    record = model.history.load(over.output_folder, over.exp_id) if over else None
    return presenters.run_state_view(model.EXPERIMENT, model.engine(),
                                     model.container(model.EXPERIMENT.profile),
                                     entry, model.RUN.entry, record)


def _broadcast(entry=None, over=None) -> None:
    """Tell every page open on this timon, not only the one that asked.

    Two tabs on one workspace are two views of one run, and a run started in
    either has to lock both.
    """
    socketio.emit("run_state", _state(entry, over))


def _fail(message: str) -> None:
    """A run that never started: say why, and give the page its button back."""
    emit("workflow_output", {"data": message})
    emit("run_state", _state())


# ── watching a run ───────────────────────────────────────────────────────────

def _watch(sid: str, entry) -> None:
    """Forward what a run is writing to one page, until the run is over.

    Runs in a background task, and reads the log from a little way back so
    that a page which has just attached to a run that started an hour ago
    has something to show. ``socketio.emit`` rather than ``emit`` because
    this is off the request context, and ``to=sid`` because what one page is
    watching is that page's own business — another tab may be watching a
    different run.
    """
    checked, was_alive = 0.0, True

    def alive_now() -> bool:
        nonlocal checked, was_alive
        now = time.monotonic()
        if now - checked >= LIVENESS_EVERY:
            was_alive, checked = model.live.alive(entry), now
        return was_alive

    try:
        for chunk in model.Tail(entry.log).chunks(alive_now):
            socketio.emit("workflow_output", {"data": chunk}, to=sid)
    except Exception as exc:
        socketio.emit("workflow_output",
                      {"data": f"[ERROR reading the run's log] {exc}\n"}, to=sid)
    # The run this page was watching is over. What it is over *as* comes from
    # the record, which the run that ended wrote — or which was corrected on
    # the way in here, if the timon that started it is gone.
    if WATCHING.get(sid) == entry.out_dir:
        del WATCHING[sid]
    socketio.emit("run_state", _state(_target(), over=entry), to=sid)


def _attach(sid: str, entry) -> None:
    """Start sending one page one run, unless it is already being sent it.

    Kept here rather than left to the page to get right: a page asks to be
    attached whenever it learns that something is running, and it learns
    that from more than one direction — its own request, a run it started, a
    run somebody else started. Two watchers on one page would print every
    line of the run twice.
    """
    if WATCHING.get(sid) == entry.out_dir:
        return
    WATCHING[sid] = entry.out_dir
    socketio.start_background_task(_watch, sid, entry)


@socketio.on("attach")
def handle_attach(data=None):
    """Show this page whatever is going, which is how it recovers a run.

    Sent on every connection, so closing the browser mid-run and opening it
    again — or quitting timon and starting a new one, in this workspace or
    any other — puts the run back on the page with its output, rather than
    leaving an idle-looking page whose run button would start the same
    pipeline a second time.
    """
    exp_id = (data or {}).get("exp_id", "") if isinstance(data, dict) else ""
    entry = _target(exp_id)
    emit("run_state", _state(entry))
    if entry is not None:
        _attach(request.sid, entry)
    elif not exp_id:
        _replay()


def _replay() -> None:
    """With nothing going, show the last run of this configuration's identifier.

    Which, for a run that has just been reopened, is the run that failed:
    its log is still in its folder, and its end is the error worth reading
    before running it again. Sent whole, once, rather than watched — the run
    is over and nothing more is coming.
    """
    record = model.EXPERIMENT.previous()
    if record is None or not record.ended or not record.log:
        return
    text = "".join(model.Tail(record.log).chunks(lambda: False, poll=0, settle=0))
    emit("replay", presenters.replay_view(record, text))


# ── starting one ─────────────────────────────────────────────────────────────

@socketio.on("run_workflow")
def handle_run():
    sid = request.sid

    if not model.EXPERIMENT.is_ready():
        _fail("[ERROR] Configuration incomplete.\n")
        return

    try:
        model.RUN.start(model.EXPERIMENT.run_spec())
    except FileNotFoundError as exc:
        _fail(f"[ERROR] Could not launch nextflow — is it on PATH?\n  {exc}\n")
        return
    except Exception as exc:
        _fail(f"[ERROR] Failed to start workflow:\n  {exc}\n")
        return

    _started(sid)


@socketio.on("run_test")
def handle_test():
    """The pipeline's own test profile, over the same console as a real run.

    Nothing is asked of the configuration: what makes a test worth having is
    that it answers "does this install work at all" before there is a
    configuration to answer it with. Whether the pipeline has one to run is
    model.EXPERIMENT's answer, and building the command is where it is given.
    """
    sid = request.sid

    try:
        model.RUN.start_test(model.EXPERIMENT.test_spec())
    except FileNotFoundError as exc:
        _fail(f"[ERROR] Could not launch nextflow — is it on PATH?\n  {exc}\n")
        return
    except Exception as exc:
        _fail(f"[ERROR] Failed to start the test run:\n  {exc}\n")
        return

    _started(sid)


def _started(sid: str) -> None:
    """A run has just been launched: lock every page, and watch it from this one.

    The command is echoed into the log rather than to the page, so that it
    is there for whoever opens the run next — including a timon that finds
    it hours from now.
    """
    entry = model.RUN.entry
    _broadcast(entry)
    socketio.start_background_task(_reap)
    if entry is not None:
        _attach(sid, entry)


def _reap() -> None:
    """Wait for this timon's own run and write down how it ended.

    Only the process that started a run can wait on it, and only waiting
    gives an exit code. A run whose timon is gone is closed off from
    nextflow's own history instead, when someone next reads the record.
    """
    model.RUN.outcome()
    _broadcast(_target())


# ── stopping one ─────────────────────────────────────────────────────────────

@socketio.on("cancel_workflow")
def handle_cancel(data=None):
    """Stop a run — this timon's, or one it is only watching.

    Off the request, because stopping is not instant: nextflow is asked
    first and given time to take its tasks and their containers with it,
    and only a nextflow that has stopped answering is killed. Waiting for
    that is the difference between a stopped run and a machine still full of
    containers nothing knows about.
    """
    exp_id = (data or {}).get("exp_id", "") if isinstance(data, dict) else ""
    entry = _target(exp_id)
    if entry is None:
        emit("run_state", _state())
        return
    emit("workflow_output", {"data": STOPPING_LINE})
    socketio.start_background_task(_stop, entry)


def _stop(entry) -> None:
    mine = model.RUN.entry
    if mine is not None and mine.out_dir == entry.out_dir:
        model.RUN.cancel()
    else:
        model.stop(entry)
    socketio.emit("workflow_output", {"data": CANCELLED_LINE})
    _broadcast(_target(), over=entry)


# ── the page going away ──────────────────────────────────────────────────────

@socketio.on("disconnect")
def handle_disconnect():
    WATCHING.pop(request.sid, None)

    def _idle() -> bool:
        return (len(socketio.server.manager.rooms.get("/", {})) == 0
                and not model.RUN.running)

    try:
        # A run of this timon's own is a reason to stay: it no longer keeps
        # the workflow alive — nextflow has a session of its own now — but
        # this is the only process that can wait on it and write down how it
        # ended. A page reload also fires disconnect, so re-check after the
        # grace period to see whether the client came back.
        if _idle():
            def shutdown():
                time.sleep(3)
                if _idle():
                    print("No clients connected. Shutting down.")
                    os._exit(0)
            threading.Thread(target=shutdown, daemon=True).start()
    except Exception:
        pass
