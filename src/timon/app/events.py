"""Socket.IO surface: the console, and the button that stops it.

The other half of the view. It starts a run, forwards what nextflow says and
puts the end of it into the words the terminal shows — it does not decide
whether a run may start, what argv it gets, or whether being killed counts as
cancelled. Those are model.EXPERIMENT's and model.RUN's answers.
"""

import os
import threading
import time

from flask import request
from flask_socketio import emit

from . import model, socketio

# The model reports an Outcome; the wording for it is here, next to the rest
# of the console's voice.
CANCELLED_LINE = "[Workflow cancelled by user]\n"


def _fail(message: str) -> None:
    """A run that never started: say why, and give the page its button back."""
    emit('workflow_output', {'data': message})
    emit('finish', {'finished': True})


def _stream_output(sid: str):
    """Runs in a background task: forward the run's output, then its outcome.

    socketio.emit is used rather than emit() because this is off the request
    context; `to=sid` keeps it on the page that asked for the run.
    """
    run = model.RUN
    try:
        for line in run.lines():
            socketio.emit('workflow_output', {'data': line}, to=sid)
    except Exception as exc:
        socketio.emit('workflow_output',
                      {'data': f'[ERROR reading output] {exc}\n'}, to=sid)

    outcome, code = run.outcome()

    if outcome is model.Outcome.CANCELLED:
        socketio.emit('workflow_cancelled', {'success': True}, to=sid)
        socketio.emit('workflow_output', {'data': CANCELLED_LINE}, to=sid)
        return

    if outcome is model.Outcome.FAILED:
        socketio.emit('workflow_output',
                      {'data': f'[ERROR] nextflow exited with code {code}\n'}, to=sid)
    socketio.emit('finish', {'finished': True}, to=sid)


@socketio.on("run_workflow")
def handle_run():
    sid = request.sid

    if not model.EXPERIMENT.is_ready():
        _fail('[ERROR] Configuration incomplete.\n')
        return

    try:
        model.RUN.start(model.EXPERIMENT.run_spec())
    except FileNotFoundError as exc:
        _fail(f'[ERROR] Could not launch nextflow — is it on PATH?\n  {exc}\n')
        return
    except Exception as exc:
        _fail(f'[ERROR] Failed to start workflow:\n  {exc}\n')
        return

    # Echo the exact command — invaluable for debugging flag/path issues
    emit('workflow_output', {'data': f'[CMD] {" ".join(model.RUN.command)}\n'})

    socketio.start_background_task(_stream_output, sid)


@socketio.on("cancel_workflow")
def handle_cancel():
    model.RUN.cancel()
    emit("workflow_cancelled", {"success": True})
    emit('workflow_output', {'data': CANCELLED_LINE})


@socketio.on('disconnect')
def handle_disconnect():
    def _idle() -> bool:
        return (len(socketio.server.manager.rooms.get('/', {})) == 0
                and not model.RUN.running)

    try:
        # Never quit out from under a running workflow: natively installed,
        # os._exit would orphan the nextflow subprocess rather than stop a
        # container. A page reload also fires disconnect, so re-check after
        # the grace period to see whether the client came back.
        if _idle():
            def shutdown():
                time.sleep(3)
                if _idle():
                    print("No clients connected. Shutting down.")
                    os._exit(0)
            threading.Thread(target=shutdown, daemon=True).start()
    except Exception:
        pass
