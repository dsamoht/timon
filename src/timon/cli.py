"""Command line entry point: start the local server and open a browser at it."""

import argparse
import socket
import threading
import time
import webbrowser

from timon import __version__


def _free_port(host: str) -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def _open_when_ready(host: str, port: int, timeout: float = 20.0) -> None:
    """Open the browser only once the server actually accepts connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            if sock.connect_ex((host, port)) == 0:
                webbrowser.open(f"http://{host}:{port}")
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
    socketio.run(create_app(), host=args.host, port=port,
                 allow_unsafe_werkzeug=True)
