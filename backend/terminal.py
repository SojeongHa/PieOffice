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
# WebSocket handler — uses `script` to wrap tmux in a pty safely
# ---------------------------------------------------------------------------


# Map xterm.js escape sequences to tmux key names
_SPECIAL_KEYS = {
    "\r": "Enter",
    "\x7f": "BSpace",
    "\x1b[A": "Up",
    "\x1b[B": "Down",
    "\x1b[C": "Right",
    "\x1b[D": "Left",
    "\x1b[H": "Home",
    "\x1b[F": "End",
    "\x1b[2~": "IC",      # Insert
    "\x1b[3~": "DC",      # Delete
    "\x1b[5~": "PPage",   # PageUp
    "\x1b[6~": "NPage",   # PageDown
    "\x09": "Tab",
    "\x1b": "Escape",
}


def _send_tmux_keys(session_name: str, data: str) -> None:
    """Send keystrokes to tmux, handling special keys correctly."""
    i = 0
    while i < len(data):
        matched = False
        # Try matching longest special key sequences first
        for seq, key_name in sorted(_SPECIAL_KEYS.items(), key=lambda x: -len(x[0])):
            if data[i:].startswith(seq):
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, key_name],
                    capture_output=True, timeout=2,
                )
                i += len(seq)
                matched = True
                break
        if not matched:
            ch = data[i]
            if ord(ch) < 32 and ch not in ("\r", "\n", "\t", "\x1b"):
                # Control character: Ctrl+A = C-a, etc.
                ctrl_char = chr(ord(ch) + 64)
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, f"C-{ctrl_char.lower()}"],
                    capture_output=True, timeout=2,
                )
            else:
                # Regular character — send literal
                subprocess.run(
                    ["tmux", "send-keys", "-t", session_name, "-l", ch],
                    capture_output=True, timeout=2,
                )
            i += 1


def handle_terminal_ws(ws, session_name: str, session_tokens=None) -> None:
    """WebSocket handler: relay I/O to tmux via pipe-pane + send-keys.

    No extra tmux client is created — the laptop remains the only client,
    so tmux auto-resize works perfectly. Output is streamed via pipe-pane
    to a FIFO that we read. Input is sent via tmux send-keys.

    Protocol:
    - Client sends JSON: {"type": "auth", "token": "..."} first
    - Client sends JSON: {"type": "input", "data": "..."} for keystrokes
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

    # Send current visible pane content first (not full scrollback)
    # -J joins wrapped lines, -e includes escape sequences for colors
    r = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p", "-e", "-J"],
        capture_output=True, text=True,
    )
    if r.returncode == 0 and r.stdout:
        clean = _STATUS_LINE_RE.sub("", r.stdout)
        ws.send(json.dumps({"type": "output", "data": clean}))

    # Create a FIFO for pipe-pane output (new output only, going forward)
    fifo_dir = tempfile.mkdtemp(prefix="pieterm-")
    fifo_path = os.path.join(fifo_dir, "pane.fifo")
    os.mkfifo(fifo_path)

    # Start pipe-pane: tmux streams pane output to our FIFO
    subprocess.run(
        ["tmux", "pipe-pane", "-t", session_name, f"cat > {fifo_path}"],
        capture_output=True,
    )

    print(f"[Terminal] pipe-pane connected to '{session_name}'", file=sys.stderr)

    stop = threading.Event()

    def _read_fifo():
        """Read pane output from FIFO and send to WebSocket."""
        try:
            fd = os.open(fifo_path, os.O_RDONLY | os.O_NONBLOCK)
            while not stop.is_set():
                r, _, _ = select.select([fd], [], [], 1.0)
                if r:
                    data = os.read(fd, 4096)
                    if data:
                        text = data.decode("utf-8", errors="replace")
                        clean = _STATUS_LINE_RE.sub("", text)
                        if clean:
                            ws.send(json.dumps({
                                "type": "output",
                                "data": clean,
                            }))
        except Exception as e:
            if not stop.is_set():
                print(f"[Terminal] fifo reader error: {e}", file=sys.stderr)
        finally:
            try:
                os.close(fd)
            except Exception:
                pass
            stop.set()

    reader = threading.Thread(target=_read_fifo, daemon=True)
    reader.start()

    try:
        while not stop.is_set():
            raw = ws.receive(timeout=5)
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
                    _send_tmux_keys(session_name, data)

            elif msg_type == "resize":
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                # Resize tmux window to phone size (laptop shrinks temporarily)
                subprocess.run(
                    ["tmux", "resize-window", "-t", session_name,
                     "-x", str(cols), "-y", str(rows)],
                    capture_output=True, timeout=2,
                )

    except Exception as e:
        print(f"[Terminal] WebSocket error: {e}", file=sys.stderr)
    finally:
        stop.set()
        caffeinate.release()
        # Stop pipe-pane
        subprocess.run(
            ["tmux", "pipe-pane", "-t", session_name],
            capture_output=True,
        )
        # Clean up FIFO
        try:
            os.unlink(fifo_path)
            os.rmdir(fifo_dir)
        except OSError:
            pass
        # Restore laptop size:
        # 1. resize-window -A to fit to current client
        # 2. Re-set window-size to 'smallest' to re-enable auto-resize
        subprocess.run(
            ["tmux", "resize-window", "-A", "-t", session_name],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "set-option", "-g", "window-size", "smallest"],
            capture_output=True,
        )
        print(f"[Terminal] Disconnected from '{session_name}'", file=sys.stderr)
