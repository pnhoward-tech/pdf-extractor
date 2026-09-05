#!/usr/bin/env python3
"""Run the extractor as a desktop app.

Starts the server on a free port bound to the loopback address and opens a
window on it. Nothing listens on the network, and nothing is uploaded anywhere:
statements are read, held in memory, and dropped when the app closes.

    python desktop.py

If `pywebview` is installed it opens in its own window; otherwise it opens in
the default browser and prints the address.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import sys
import threading
import time
import webbrowser
from typing import Iterable

HOST = "127.0.0.1"  # loopback only — never 0.0.0.0
TITLE = "Statement Extractor"


def say(*parts: object) -> None:
    """Print immediately: a frozen app's stdout is not a terminal, so the
    default buffering would hold the address back until exit."""
    print(*parts, flush=True)


def free_port() -> int:
    """Ask the OS for a port nothing else is using."""
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def missing_tools() -> list[tuple[str, str, str]]:
    """External programs the app needs, and how to install each."""
    needed = [
        (
            "pdftotext",
            "poppler",
            "reading text-based statements — the app cannot work without it",
        ),
        (
            "tesseract",
            "tesseract",
            "reading scanned statements; optional if none of yours are scans",
        ),
    ]
    return [(binary, pkg, why) for binary, pkg, why in needed if shutil.which(binary) is None]


def install_hint(package: str) -> str:
    if sys.platform == "darwin":
        return f"brew install {package}"
    if sys.platform.startswith("win"):
        return f"choco install {package}" if package != "poppler" else "choco install poppler"
    suffix = "-utils" if package == "poppler" else "-ocr"
    return f"sudo apt-get install {package}{suffix}"


def report_tools(missing: Iterable[tuple[str, str, str]]) -> bool:
    """Print what is missing. Returns False if the app cannot run at all."""
    fatal = False
    for binary, package, why in missing:
        required = binary == "pdftotext"
        fatal = fatal or required
        label = "REQUIRED" if required else "optional"
        say(f"  [{label}] {binary} is not installed — needed for {why}.")
        say(f"             install it with:  {install_hint(package)}")
    return not fatal


def wait_until_up(port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.4)
            if probe.connect_ex((HOST, port)) == 0:
                return True
        time.sleep(0.1)
    return False


def serve(port: int) -> None:
    import uvicorn

    from app.main import app

    uvicorn.run(app, host=HOST, port=port, log_level="warning")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, help="fixed port instead of a free one")
    parser.add_argument("--no-window", action="store_true", help="do not open a window")
    parser.add_argument(
        "--browser", action="store_true", help="use the default browser, not a native window"
    )
    args = parser.parse_args(argv)

    say(f"{TITLE}\n")
    missing = missing_tools()
    if missing and not report_tools(missing):
        say("\nInstall the required tool above, then run this again.")
        return 1
    if missing:
        say()

    port = args.port or free_port()
    url = f"http://{HOST}:{port}/"

    threading.Thread(target=serve, args=(port,), daemon=True).start()
    if not wait_until_up(port):
        print("The server did not start. Run `uvicorn app.main:app` to see why.", file=sys.stderr)
        return 1

    say(f"Running at {url}")
    say("Everything stays on this machine. Close the window or press Ctrl-C to stop.\n")

    if args.no_window:
        pass
    elif not args.browser and _open_native_window(url):
        return 0  # the window's event loop has already returned, so we are done
    else:
        webbrowser.open(url)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        say("Stopped.")
    return 0


def _open_native_window(url: str) -> bool:
    """Open a real desktop window if pywebview is available."""
    try:
        import webview
    except ImportError:
        return False
    webview.create_window(TITLE, url, width=1280, height=900)
    webview.start()
    return True


if __name__ == "__main__":
    raise SystemExit(main())
