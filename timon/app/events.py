import os
import threading
import time
from flask_socketio import emit
from . import socketio
from .core import EXP_CONFIG, WF_SUBPROCESS


@socketio.on("run_workflow")
def handle_run():
    if not EXP_CONFIG.is_ready():
        emit('workflow_output', {'data': '[Error] Configuration incomplete.'})
        emit('finish', {'finished': True})
        return

    WF_SUBPROCESS.start(EXP_CONFIG.as_dict())
    
    if not WF_SUBPROCESS.process:
        emit('workflow_output', {'data': '[Error] Failed to start process.'})
        return

    try:
        for line in iter(WF_SUBPROCESS.process.stdout.readline, ''):
            if line:
                emit('workflow_output', {'data': line})
    except Exception as e:
        emit('workflow_output', {'data': f'[Error reading output] {str(e)}'})

    emit('finish', {'finished': True})

@socketio.on("cancel_workflow")
def handle_cancel():
    WF_SUBPROCESS.cancel()
    emit("workflow_cancelled", {"success": True})
    emit('workflow_output', {'data': '[Workflow Cancelled by User]'})

@socketio.on('disconnect')
def handle_disconnect():
    """
    Shut down the server if no clients are connected.
    Useful for local electron/browser-based apps.
    """
    try:
        clients = len(socketio.server.manager.rooms.get('/', {}))
        if clients == 0:
            print("No clients connected. Shutting down in 3 seconds...")
            def shutdown():
                time.sleep(3)
                os._exit(0) # Force exit
            threading.Thread(target=shutdown, daemon=True).start()
    except Exception:
        pass
