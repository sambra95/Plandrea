"""Entry point for the packaged Plandrea bundle, on macOS and on Windows.

No console here, so everything is mirrored to a log file. Streamlit is started
on a free port, the browser pointed at it, and the whole thing quits once the
last tab closes. Run by Plandrea.app or Plandrea.cmd; a checkout runs streamlit
directly.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

import backcompatability

RESOURCES = Path(__file__).resolve().parent
START_TIMEOUT = 120
WINDOWS = sys.platform == "win32"

#: What the app is called, and the folders it keeps for itself are named.
NAME = "Plandrea"

#: Where the app is served under, so its name follows the port in the address
#: bar. The same as server.baseUrlPath in .streamlit/config.toml.
URL_PATH = "plandrea"

#: Keeps a console window from flashing up behind the app's own, since the
#: launcher starts it without one. Nothing to do anywhere else.
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if WINDOWS else {}

#: Grace after the last tab closes; 0 keeps it running until quit by hand.
IDLE_TIMEOUT = 30
IDLE_POLL = 3


def _writable(root: Path) -> Path:
    """`root`, made if it is not there yet, or somewhere temporary if it cannot
    be: the app is no use unable to write at all."""
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except OSError:
        return Path(tempfile.gettempdir())


def _support_parent() -> Path:
    """Each platform's own spot for what an app keeps for itself."""
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return Path.home() / "Library" / "Application Support"


def _support_dir() -> Path:
    """Somewhere writable for the database, never inside the bundle."""
    return _writable(_support_parent() / NAME)


def _log_file() -> Path:
    """Beside the database on Windows; where a Mac keeps logs on a Mac."""
    root = (_support_dir() if WINDOWS
            else _writable(Path.home() / "Library" / "Logs" / NAME))
    return root / "plandrea.log"


class _Tee:
    """Write to the real stream, if there is one, and to the log."""

    def __init__(self, stream, handle):
        self._stream, self._handle = stream, handle

    def write(self, data):
        if self._stream is not None:
            try:
                self._stream.write(data)
            except (OSError, ValueError):
                pass
        self._handle.write(data)
        self._handle.flush()

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except (OSError, ValueError):
                pass
        self._handle.flush()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _serving(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _open_tabs(port: int) -> int | None:
    """Browser tabs holding the app open, or None if it cannot be told. The
    websocket closes with the tab, so this counts tabs, not activity."""
    command = (["netstat", "-n", "-p", "TCP"] if WINDOWS
               else ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED"])
    try:
        found = subprocess.run(command, capture_output=True, text=True,
                               timeout=10, **NO_WINDOW).stdout
    except Exception:
        return None
    if WINDOWS:
        # netstat lists every connection, and a loopback one twice - once from
        # each end. Only the rows arriving at the server's port are ours.
        rows = (line.split() for line in found.splitlines())
        return sum(1 for row in rows if len(row) > 3 and row[3] == "ESTABLISHED"
                   and row[1].endswith(f":{port}"))
    # lsof exits 1 with no output when nothing matches: a real zero.
    return max(0, len([line for line in found.splitlines() if line.strip()]) - 1)


def _idle_timeout() -> float:
    raw = os.environ.get("PLANDREA_IDLE_TIMEOUT", "").strip()
    try:
        return max(0.0, float(raw)) if raw else float(IDLE_TIMEOUT)
    except ValueError:
        return float(IDLE_TIMEOUT)


def _wait_until_closed(port: int, server: subprocess.Popen) -> None:
    """Stay up while a tab is open, and for a grace period after the last one."""
    timeout = _idle_timeout()
    if not timeout:
        print("[Plandrea] Idle shutdown off; quit this app by hand.")
        server.wait()
        return

    print(f"[Plandrea] Quitting {timeout:.0f}s after the last tab closes.")
    empty_since = None
    while server.poll() is None:
        time.sleep(IDLE_POLL)
        tabs = _open_tabs(port)
        if tabs is None:          # cannot tell: never quit on a guess
            empty_since = None
            continue
        if tabs > 0:
            empty_since = None
            continue
        empty_since = empty_since or time.time()
        if time.time() - empty_since >= timeout:
            print("[Plandrea] No tabs left; shutting down.")
            return


def _quit(signum, frame):
    """Turn a quit signal into an exception so the server is stopped on the way
    out; the default handler would leave it orphaned."""
    raise KeyboardInterrupt


def main() -> int:
    # Windows has no SIGHUP, and nothing else to put in its place.
    for name in ("SIGINT", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _quit)

    # Before anything makes the new folder, which would leave the old one where
    # it is. Not when pointed at a database of its own: that one is not moved.
    if not os.environ.get("PLANDREA_DB", "").strip():
        backcompatability.move_support_folder(_support_parent(), NAME,
                                              "plandrea.db")

    log = open(_log_file(), "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, log)
    sys.stderr = _Tee(sys.stderr, log)
    print(f"\n[Plandrea] Starting {time.strftime('%Y-%m-%d %H:%M:%S')}")

    env = dict(os.environ)
    # The bundle is signed, and a .pyc written inside it afterwards breaks the
    # seal.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("PLANDREA_DB", str(_support_dir() / "plandrea.db"))
    print(f"[Plandrea] Data: {env['PLANDREA_DB']}")

    port = _free_port()
    server = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run",
         str(RESOURCES / "streamlit_app.py"),
         "--server.port", str(port), "--server.address", "127.0.0.1",
         "--server.headless", "true", "--browser.gatherUsageStats", "false"],
        cwd=RESOURCES, env=env, **NO_WINDOW)
    try:
        deadline = time.time() + START_TIMEOUT
        while time.time() < deadline and not _serving(port):
            if server.poll() is not None:
                print(f"[Plandrea] Server exited with {server.returncode}")
                return server.returncode or 1
            time.sleep(0.2)
        if not _serving(port):
            print("[Plandrea] Server did not start in time.")
            return 1

        address = f"http://127.0.0.1:{port}/{URL_PATH}"
        print(f"[Plandrea] Ready on {address}")
        webbrowser.open(address)
        _wait_until_closed(port, server)
        return 0
    except KeyboardInterrupt:
        print("[Plandrea] Asked to quit.")
        return 0
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        print("[Plandrea] Stopped.")
        log.close()


if __name__ == "__main__":
    raise SystemExit(main())
