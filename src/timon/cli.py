"""Command line entry point: start the local server and open a browser at it."""

import argparse
import os
import shutil
import socket
import subprocess
import threading
import time
import webbrowser

from timon import __version__


def _free_port(host: str) -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _is_wsl() -> bool:
    """Running inside Windows Subsystem for Linux."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        with open("/proc/sys/kernel/osrelease") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def _wsl_browser_command(url: str) -> list[str] | None:
    """How to open a URL in the Windows browser from inside WSL, if there is a way.

    Python's webbrowser finds no browser in WSL — there is none on the Linux
    side — and fails without a word. The one worth opening is Windows' own,
    and WSL2 forwards loopback to it, so the URL works there as it is.
    wslview (wslu) is the proper way when installed; cmd.exe is always there
    through interop. The empty argument is start's window title: without it,
    a quoted URL would be taken for one.
    """
    if shutil.which("wslview"):
        return ["wslview", url]
    if shutil.which("cmd.exe"):
        return ["cmd.exe", "/c", "start", "", url]
    return None


def _open_browser(url: str) -> None:
    # A BROWSER the user set is their answer, and webbrowser honours it.
    if _is_wsl() and not os.environ.get("BROWSER"):
        command = _wsl_browser_command(url)
        if command:
            try:
                # cmd.exe started from a Linux directory complains about UNC
                # paths on stderr; the browser opens regardless. Run from
                # a Windows-side folder when there is one to keep it quiet.
                subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 cwd="/mnt/c" if os.path.isdir("/mnt/c") else None)
                return
            except OSError:
                pass
    webbrowser.open(url)


def _open_when_ready(host: str, port: int, timeout: float = 20.0) -> None:
    """Open the browser only once the server actually accepts connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            if sock.connect_ex((host, port)) == 0:
                _open_browser(f"http://{host}:{port}")
                return
        time.sleep(0.1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="timon",
        description="Toolkit of Integrated MicrobiOme analysis "
                    "with support for Nanopore data",
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind (default: loopback only)")
    parser.add_argument("--port", type=int,
                        help="port to bind (default: pick a free one)")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open a browser — use behind an SSH tunnel")
    parser.add_argument("--version", action="version",
                        version=f"timon {__version__}")
    args = parser.parse_args()

    # Imported here so --help and --version do not pay for the Flask import.
    from timon.app import create_app, socketio

    port = args.port or _free_port(args.host)

    if not args.no_browser:
        threading.Thread(target=_open_when_ready, args=(args.host, port),
                         daemon=True).start()

    print(f"timon {__version__} → http://{args.host}:{port}   (Ctrl-C to quit)")
    try:
        socketio.run(create_app(), host=args.host, port=port,
                     allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:
        pass
    _report_running()


def _report_running() -> None:
    """Say what is still going, now that quitting no longer stops it.

    A run is launched in a session of its own and writes to a file, so
    Ctrl-C here ends the page and not the workflow — which is the point,
    since a run is hours of compute. That is worth saying out loud, along
    with where to look: any timon on this machine finds a run that is still
    going, whichever folder it was started in.
    """
    from timon.app import model

    going = model.live.running()
    if not going:
        return
    print()
    for entry in going:
        print(f"timon: {entry.exp_id} is still running (process {entry.pid})")
        print(f"       output   {entry.out_dir}")
        print(f"       log      {entry.log}")
    print("       start timon again to watch it, or to stop it")
