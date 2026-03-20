"""Web terminal: tmux session listing, WebSocket I/O relay, caffeinate."""

import json
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

from config import TERMINAL_IDLE_TIMEOUT

# Filter out terminal status line sequences (DCS, OSC) that corrupt xterm.js.
# Matches: ESC P ... ST, ESC ] ... ST, ESC ] ... BEL
_STATUS_LINE_RE = re.compile(
    r"(\x1bP[^\x1b]*(?:\x1b\\|\x07))"   # DCS ... ST
    r"|(\x1b\][^\x07\x1b]*(?:\x07|\x1b\\))"  # OSC ... BEL/ST
)


# ---------------------------------------------------------------------------
# Tmux session discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TmuxSession:
    """Parsed tmux session info."""

    name: str
    windows: int
    attached: int
    cwd: str


def parse_tmux_list(raw: str) -> list[TmuxSession]:
    """Parse `tmux list-sessions -F` output into TmuxSession objects."""
    sessions: list[TmuxSession] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        sessions.append(TmuxSession(
            name=parts[0],
            windows=int(parts[1]),
            attached=int(parts[2]),
            cwd=parts[3],
        ))
    return sessions


def list_tmux_sessions() -> list[TmuxSession]:
    """List tmux sessions that were started by the claude wrapper."""
    result = subprocess.run(
        [
            "tmux", "list-sessions", "-F",
            "#{session_name}:#{session_windows}:#{session_attached}:#{pane_current_path}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [s for s in parse_tmux_list(result.stdout) if s.name.startswith("claude-")]


# ---------------------------------------------------------------------------
# Caffeinate manager — prevent Mac sleep during active terminal sessions
# ---------------------------------------------------------------------------


class CaffeinateManager:
    """Manages a single caffeinate process. Starts on first terminal open,
    stops after TERMINAL_IDLE_TIMEOUT of no active sessions."""

    def __init__(self, idle_timeout: int = TERMINAL_IDLE_TIMEOUT):
        self._process: subprocess.Popen | None = None
        self._active_count: int = 0
        self._lock = threading.Lock()
        self._idle_timeout = idle_timeout
        self._idle_timer: threading.Timer | None = None

    def acquire(self) -> None:
        """Called when a terminal WebSocket session opens."""
        with self._lock:
            self._cancel_idle_timer()
            self._active_count += 1
            if self._process is None:
                self._start()

    def release(self) -> None:
        """Called when a terminal WebSocket session closes."""
        with self._lock:
            self._active_count = max(0, self._active_count - 1)
            if self._active_count == 0:
                self._schedule_idle_stop()

    def _start(self) -> None:
        """Start caffeinate -s (prevent sleep while on power)."""
        try:
            self._process = subprocess.Popen(
                ["caffeinate", "-s"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[Terminal] caffeinate started — Mac will stay awake", file=sys.stderr)
        except FileNotFoundError:
            print("[Terminal] caffeinate not found (not macOS?)", file=sys.stderr)

    def stop(self) -> None:
        """Kill caffeinate process."""
        if self._process is not None:
            self._process.terminate()
            self._process = None
            print("[Terminal] caffeinate stopped — Mac can sleep", file=sys.stderr)

    def _schedule_idle_stop(self) -> None:
        self._cancel_idle_timer()
        self._idle_timer = threading.Timer(self._idle_timeout, self._idle_stop)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _idle_stop(self) -> None:
        with self._lock:
            if self._active_count == 0:
                self.stop()

    def _cancel_idle_timer(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None


# Singleton
caffeinate = CaffeinateManager()


# ---------------------------------------------------------------------------
# ttyd process manager — one ttyd instance per tmux session
# ---------------------------------------------------------------------------

# Active ttyd instances: session_name → {"proc": Popen, "port": int}
_ttyd_instances: dict[str, dict] = {}
_ttyd_lock = threading.Lock()
_TTYD_PORT_BASE = 17600  # ttyd ports: 17600, 17601, ...


def get_or_start_ttyd(session_name: str) -> int | None:
    """Start a ttyd process for a tmux session, return its port.
    Reuses existing instance if already running."""
    with _ttyd_lock:
        if session_name in _ttyd_instances:
            inst = _ttyd_instances[session_name]
            if inst["proc"].poll() is None:
                return inst["port"]
            # Process died, clean up
            del _ttyd_instances[session_name]

        port = _TTYD_PORT_BASE + len(_ttyd_instances)
        # Find an unused port
        for p in range(_TTYD_PORT_BASE, _TTYD_PORT_BASE + 100):
            if not any(i["port"] == p for i in _ttyd_instances.values()):
                port = p
                break

        proc = subprocess.Popen(
            [
                "ttyd",
                "--port", str(port),
                "--interface", "127.0.0.1",  # localhost only — Flask proxies
                "--writable",
                "--once",  # exit after client disconnects
                "tmux", "attach-session", "-t", session_name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _ttyd_instances[session_name] = {"proc": proc, "port": port}
        print(f"[Terminal] ttyd started for '{session_name}' on port {port} (pid={proc.pid})",
              file=sys.stderr)
        return port


def stop_ttyd(session_name: str) -> None:
    """Stop the ttyd process for a session."""
    with _ttyd_lock:
        inst = _ttyd_instances.pop(session_name, None)
    if inst and inst["proc"].poll() is None:
        inst["proc"].terminate()
        print(f"[Terminal] ttyd stopped for '{session_name}'", file=sys.stderr)


def stop_all_ttyd() -> None:
    """Stop all ttyd processes."""
    with _ttyd_lock:
        for name, inst in _ttyd_instances.items():
            if inst["proc"].poll() is None:
                inst["proc"].terminate()
        _ttyd_instances.clear()
