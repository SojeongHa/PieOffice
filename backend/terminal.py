"""Terminal utilities: tmux session listing and caffeinate manager."""

import os
import subprocess
import sys
import threading
from dataclasses import dataclass


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
# Caffeinate manager — prevent Mac sleep during active phone terminal sessions
# ---------------------------------------------------------------------------


class CaffeinateManager:
    """Ref-counted caffeinate process. Starts on first WebSocket open,
    stops when all WebSocket sessions close."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._count: int = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Called when a terminal WebSocket session opens."""
        with self._lock:
            self._count += 1
            if self._process is None:
                self._start()

    def release(self) -> None:
        """Called when a terminal WebSocket session closes."""
        with self._lock:
            self._count = max(0, self._count - 1)
            if self._count == 0:
                self._stop()

    def _start(self) -> None:
        try:
            self._process = subprocess.Popen(
                ["caffeinate", "-s"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[Terminal] caffeinate ON — phone connected", file=sys.stderr)
        except FileNotFoundError:
            pass

    def _stop(self) -> None:
        if self._process is not None:
            self._process.terminate()
            self._process = None
            print("[Terminal] caffeinate OFF — no phone sessions", file=sys.stderr)


caffeinate = CaffeinateManager()
