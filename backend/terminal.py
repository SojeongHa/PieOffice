"""Web terminal: tmux session listing, pty attach via WebSocket, caffeinate."""

import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import termios
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
# WebSocket handler — attach to tmux session via pty
# ---------------------------------------------------------------------------


def handle_terminal_ws(ws, session_name: str, session_tokens=None) -> None:
    """WebSocket handler: attach to a tmux session and relay I/O.

    Protocol:
    - Client sends JSON: {"type": "auth", "token": "..."} first
    - After auth, client sends JSON: {"type": "input", "data": "..."} for keystrokes
    - Client sends JSON: {"type": "resize", "cols": N, "rows": N} for resize
    - Server sends JSON: {"type": "output", "data": "..."} for terminal output
    - Server sends JSON: {"type": "error", "message": "..."} on errors
    """

    # --- Auth handshake (session token issued after mTLS) ---
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
        ws.send(
            json.dumps({"type": "error", "message": f"session '{session_name}' not found"})
        )
        return

    ws.send(json.dumps({"type": "connected", "session": session_name}))
    caffeinate.acquire()

    # Create a pty pair and spawn tmux as a subprocess.
    # new-session -t creates a shared client (allows laptop + phone simultaneously).
    master_fd, slave_fd = pty.openpty()
    web_session = f"web-{threading.current_thread().ident}"
    proc = subprocess.Popen(
        ["tmux", "new-session", "-t", session_name, "-s", web_session],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)  # parent only needs master

    print(f"[Terminal] Attached to tmux session '{session_name}' (pid={proc.pid})",
          file=sys.stderr)

    stop = threading.Event()

    def _read_pty():
        """Read from pty master and send to WebSocket."""
        try:
            while not stop.is_set():
                r, _, _ = select.select([master_fd], [], [], 1.0)
                if r:
                    try:
                        data = os.read(master_fd, 4096)
                        if not data:
                            print(f"[Terminal] pty read returned empty — child exited",
                                  file=sys.stderr)
                            break
                        ws.send(
                            json.dumps(
                                {"type": "output", "data": data.decode("utf-8", errors="replace")}
                            )
                        )
                    except OSError as e:
                        print(f"[Terminal] pty read OSError: {e}", file=sys.stderr)
                        break
        except Exception as e:
            print(f"[Terminal] pty reader exception: {e}", file=sys.stderr)
        finally:
            # Check child process status
            ret = proc.poll()
            if ret is not None:
                print(f"[Terminal] tmux process exited with code {ret}",
                      file=sys.stderr)
            stop.set()

    reader = threading.Thread(target=_read_pty, daemon=True)
    reader.start()

    try:
        while not stop.is_set():
            raw = ws.receive(timeout=2)
            if raw is None:
                print("[Terminal] WebSocket received None — client disconnected",
                      file=sys.stderr)
                break
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            if msg.get("type") == "ping":
                continue  # keepalive — ignore

            elif msg.get("type") == "input":
                data = msg.get("data", "")
                if data:
                    os.write(master_fd, data.encode("utf-8"))

            elif msg.get("type") == "resize":
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

    except Exception as e:
        print(f"[Terminal] WebSocket error: {e}", file=sys.stderr)
    finally:
        stop.set()
        caffeinate.release()
        try:
            os.close(master_fd)
        except OSError:
            pass
        proc.terminate()
        proc.wait()
        # Clean up the ephemeral web session
        subprocess.run(["tmux", "kill-session", "-t", web_session],
                       capture_output=True)
        print(f"[Terminal] Disconnected from '{session_name}'", file=sys.stderr)
