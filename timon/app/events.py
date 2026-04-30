import os
import threading
import time
from flask import request
from flask_socketio import emit
from . import socketio
from .core import EXP_CONFIG, WF_SUBPROCESS


def _stream_output(sid: str):
    """
    Runs in a background task. Reads stdout (stderr merged) line-by-line
    and forwards each line to the client via socketio.emit (thread-safe).
    """
    proc = WF_SUBPROCESS.process
    try:
        for line in iter(proc.stdout.readline, ''):
            if line:
                socketio.emit('workflow_output', {'data': line}, to=sid)
    except Exception as e:
        socketio.emit('workflow_output',
                      {'data': f'[ERROR reading output] {e}\n'}, to=sid)

    proc.wait()
    rc = proc.returncode

    if rc == 0:
        socketio.emit('finish', {'finished': True}, to=sid)
    elif rc in (-9, -15):          # killed by cancel()
        socketio.emit('workflow_cancelled', {'success': True}, to=sid)
        socketio.emit('workflow_output',
                      {'data': '[Workflow cancelled by user]\n'}, to=sid)
    else:
        socketio.emit('workflow_output',
                      {'data': f'[ERROR] nextflow exited with code {rc}\n'}, to=sid)
        socketio.emit('finish', {'finished': True}, to=sid)


@socketio.on("run_workflow")
def handle_run():
    sid = request.sid

    if not EXP_CONFIG.is_ready():
        emit('workflow_output', {'data': '[ERROR] Configuration incomplete.\n'})
        emit('finish', {'finished': True})
        return

    try:
        WF_SUBPROCESS.start(EXP_CONFIG.as_dict())
    except FileNotFoundError as e:
        emit('workflow_output',
             {'data': f'[ERROR] Could not launch nextflow — is it on PATH?\n  {e}\n'})
        emit('finish', {'finished': True})
        return
    except Exception as e:
        emit('workflow_output',
             {'data': f'[ERROR] Failed to start workflow:\n  {e}\n'})
        emit('finish', {'finished': True})
        return

    if not WF_SUBPROCESS.process:
        emit('workflow_output', {'data': '[ERROR] Process is None after start.\n'})
        emit('finish', {'finished': True})
        return

    # Echo the exact command — invaluable for debugging flag/path issues
    emit('workflow_output', {'data': f'[CMD] {" ".join(WF_SUBPROCESS.last_cmd)}\n'})

    socketio.start_background_task(_stream_output, sid)


@socketio.on("cancel_workflow")
def handle_cancel():
    WF_SUBPROCESS.cancel()
    emit("workflow_cancelled", {"success": True})
    emit('workflow_output', {'data': '[Workflow cancelled by user]\n'})


@socketio.on('disconnect')
def handle_disconnect():
    try:
        clients = len(socketio.server.manager.rooms.get('/', {}))
        if clients == 0:
            print("No clients connected. Shutting down in 3 seconds...")
            def shutdown():
                time.sleep(3)
                os._exit(0)
            threading.Thread(target=shutdown, daemon=True).start()
    except Exception:
        pass
