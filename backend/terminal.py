"""Web terminal: tmux session listing, pipe-based I/O relay via WebSocket, caffeinate."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

from config import TERMINAL_IDLE_TIMEOUT


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
# WebSocket handler — tmux pipe-pane + send-keys (no pty, thread-safe)
# ---------------------------------------------------------------------------


def handle_terminal_ws(ws, session_name: str, session_tokens=None) -> None:
    """WebSocket handler: relay I/O to a tmux session using pipe-pane + send-keys.

    This avoids pty entirely (which crashes in Flask's threaded server).
    Instead:
    - Output: `tmux pipe-pane` pipes pane output to a FIFO we read
    - Input: `tmux send-keys` injects keystrokes
    - Resize: `tmux resize-window`

    Protocol:
    - Client sends JSON: {"type": "auth", "token": "..."} first
    - After auth, client sends JSON: {"type": "input", "data": "..."} for keystrokes
    - Client sends JSON: {"type": "resize", "cols": N, "rows": N} for resize
    - Client sends JSON: {"type": "ping"} for keepalive
    - Server sends JSON: {"type": "output", "data": "..."} for terminal output
    - Server sends JSON: {"type": "error", "message": "..."} on errors
    """

    # --- Auth handshake ---
    try:
        raw = ws.receive(timeout=10)
        if raw is None:
            return
        msg = json.loads(raw)
        token = msg.get("token", "")
        if msg.get("type") != "auth" or not session_tokens or not session_tokens.validate(token):
            ws.send(json.dumps({"type": "error", "message": "unauthorized"}))
            return
    except Exception:
        return

    # --- Verify session exists ---
    sessions = list_tmux_sessions()
    if not any(s.name == session_name for s in sessions):
        ws.send(json.dumps({"type": "error", "message": f"session '{session_name}' not found"}))
        return

    ws.send(json.dumps({"type": "connected", "session": session_name}))
    caffeinate.acquire()

    # Use tmux capture-pane polling approach (simple, no pty, no FIFO)
    print(f"[Terminal] Connected to tmux session '{session_name}'", file=sys.stderr)

    stop = threading.Event()
    last_content = ""

    def _poll_pane():
        """Poll tmux pane content and send diffs to WebSocket."""
        nonlocal last_content
        try:
            while not stop.is_set():
                time.sleep(0.1)  # 100ms polling
                try:
                    result = subprocess.run(
                        ["tmux", "capture-pane", "-t", session_name, "-p", "-e"],
                        capture_output=True, text=True, timeout=2,
                    )
                    if result.returncode != 0:
                        break
                    content = result.stdout
                    if content != last_content:
                        # Send full screen refresh (clear + new content)
                        ws.send(json.dumps({
                            "type": "output",
                            "data": "\x1b[2J\x1b[H" + content,
                        }))
                        last_content = content
                except subprocess.TimeoutExpired:
                    continue
                except Exception:
                    break
        except Exception as e:
            print(f"[Terminal] pane poller error: {e}", file=sys.stderr)
        finally:
            stop.set()

    poller = threading.Thread(target=_poll_pane, daemon=True)
    poller.start()

    try:
        while not stop.is_set():
            raw = ws.receive(timeout=2)
            if raw is None:
                print("[Terminal] WebSocket closed by client", file=sys.stderr)
                break
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            msg_type = msg.get("type")

            if msg_type == "ping":
                continue

            elif msg_type == "input":
                data = msg.get("data", "")
                if data:
                    # send-keys -l sends literal characters
                    subprocess.run(
                        ["tmux", "send-keys", "-t", session_name, "-l", data],
                        capture_output=True, timeout=2,
                    )

            elif msg_type == "resize":
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                subprocess.run(
                    ["tmux", "resize-window", "-t", session_name, "-x", str(cols), "-y", str(rows)],
                    capture_output=True, timeout=2,
                )

    except Exception as e:
        print(f"[Terminal] WebSocket error: {e}", file=sys.stderr)
    finally:
        stop.set()
        caffeinate.release()
        print(f"[Terminal] Disconnected from '{session_name}'", file=sys.stderr)
