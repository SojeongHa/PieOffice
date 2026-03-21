# Web Terminal for Pie Office — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web-based terminal to Pie Office that shares tmux sessions, enabling phone access to running Claude Code sessions over LAN with TLS + token auth.

**Architecture:** A new `/terminal` page serves an xterm.js frontend that connects via WebSocket to a Python backend (Flask + simple-websocket). The backend attaches to existing tmux sessions and relays I/O. A tmux wrapper script (`claude`) ensures Claude Code always runs inside tmux. Auth uses a one-time-generated bearer token stored in `~/.pieoffice-terminal-token`. TLS uses a self-signed cert. `caffeinate` keeps Mac awake during active terminal sessions.

**Tech Stack:** Flask, simple-websocket (flask-sock), xterm.js (CDN), tmux, caffeinate, OpenSSL (self-signed cert generation)

---

## File Structure

```
PieOffice/
  backend/
    app.py              # MODIFY — add LAN bind option, terminal routes, CORS for LAN
    terminal.py         # CREATE — WebSocket handler, tmux attach, caffeinate mgmt
    terminal_auth.py    # CREATE — token generation, validation, middleware
    config.py           # MODIFY — add terminal config constants
    requirements.txt    # MODIFY — add flask-sock
  frontend/
    terminal.html       # CREATE — xterm.js terminal page (standalone, no Phaser)
    js/
      terminal-client.js # CREATE — WebSocket client, xterm.js init, reconnect logic
  scripts/
    setup-terminal.sh   # CREATE — generate TLS cert, auth token, install tmux wrapper
    claude              # CREATE — tmux wrapper for claude command
```

---

## Task 1: Backend Dependencies + Config

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/config.py`

- [ ] **Step 1: Add flask-sock to requirements**

```
flask>=3.0
flask-cors>=4.0
flask-sock>=0.7
```

- [ ] **Step 2: Add terminal config constants to config.py**

Add at the end of `config.py`:

```python
# ---------------------------------------------------------------------------
# Terminal (terminal.py)
# ---------------------------------------------------------------------------
# Path to the bearer token file for terminal authentication.
TERMINAL_TOKEN_PATH: str = os.environ.get(
    "PIE_TERMINAL_TOKEN_PATH",
    os.path.expanduser("~/.pieoffice-terminal-token"),
)

# Enable LAN binding (0.0.0.0) instead of localhost-only.
# When True, the server listens on all interfaces (required for phone access).
TERMINAL_LAN_MODE: bool = os.environ.get("PIE_TERMINAL_LAN", "").lower() in ("1", "true")

# TLS certificate and key paths for HTTPS (required in LAN mode).
TERMINAL_TLS_CERT: str = os.environ.get(
    "PIE_TERMINAL_TLS_CERT",
    os.path.expanduser("~/.pieoffice-tls/cert.pem"),
)
TERMINAL_TLS_KEY: str = os.environ.get(
    "PIE_TERMINAL_TLS_KEY",
    os.path.expanduser("~/.pieoffice-tls/key.pem"),
)

# Seconds of inactivity before caffeinate is released (Mac can sleep again).
TERMINAL_IDLE_TIMEOUT: int = int(os.environ.get("PIE_TERMINAL_IDLE_TIMEOUT", 300))
```

- [ ] **Step 3: Install dependency**

Run: `cd ~/Documents/workspace/PieOffice && source venv/bin/activate && pip install flask-sock`
Expected: Successfully installed flask-sock and simple-websocket

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt backend/config.py
git commit -m "feat: add terminal config constants and flask-sock dependency"
```

---

## Task 2: Token Auth Module

**Files:**
- Create: `backend/terminal_auth.py`
- Test: `tests/test_terminal_auth.py`

- [ ] **Step 1: Create test directory and write failing test**

```bash
mkdir -p ~/Documents/workspace/PieOffice/tests
```

```python
# tests/test_terminal_auth.py
"""Tests for terminal token authentication."""

import os
import tempfile

import pytest

from terminal_auth import generate_token, load_token, validate_token


class TestTokenGeneration:
    def test_generate_token_creates_file(self, tmp_path):
        token_path = str(tmp_path / "token")
        token = generate_token(token_path)
        assert os.path.isfile(token_path)
        assert len(token) == 64  # 32 bytes hex

    def test_generate_token_file_permissions(self, tmp_path):
        token_path = str(tmp_path / "token")
        generate_token(token_path)
        mode = oct(os.stat(token_path).st_mode & 0o777)
        assert mode == "0o600"

    def test_generate_token_does_not_overwrite(self, tmp_path):
        token_path = str(tmp_path / "token")
        token1 = generate_token(token_path)
        token2 = generate_token(token_path)
        assert token1 == token2  # same file, not regenerated


class TestTokenValidation:
    def test_load_token_reads_file(self, tmp_path):
        token_path = str(tmp_path / "token")
        generated = generate_token(token_path)
        loaded = load_token(token_path)
        assert loaded == generated

    def test_load_token_missing_file(self, tmp_path):
        loaded = load_token(str(tmp_path / "nonexistent"))
        assert loaded is None

    def test_validate_token_correct(self, tmp_path):
        token_path = str(tmp_path / "token")
        token = generate_token(token_path)
        assert validate_token(token, token_path) is True

    def test_validate_token_wrong(self, tmp_path):
        token_path = str(tmp_path / "token")
        generate_token(token_path)
        assert validate_token("wrong-token", token_path) is False

    def test_validate_token_empty(self, tmp_path):
        token_path = str(tmp_path / "token")
        generate_token(token_path)
        assert validate_token("", token_path) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Documents/workspace/PieOffice && source venv/bin/activate && PYTHONPATH=backend pytest tests/test_terminal_auth.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'terminal_auth'"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/terminal_auth.py
"""Token-based authentication for the web terminal.

Generates a random bearer token on first run, stores it in a file
with 0600 permissions.  The token is shown once during setup so the
user can save it on their phone.
"""

import hmac
import os
import secrets
import sys


def generate_token(token_path: str) -> str:
    """Generate a new token and write to *token_path*, or return existing."""
    if os.path.isfile(token_path):
        with open(token_path) as f:
            return f.read().strip()

    token = secrets.token_hex(32)  # 64-char hex string

    # Ensure parent directory exists
    parent = os.path.dirname(token_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    # Write with restricted permissions (owner-only read/write)
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, token.encode())
    finally:
        os.close(fd)

    print(f"[Terminal] Auth token generated: {token_path}", file=sys.stderr)
    return token


def load_token(token_path: str) -> str | None:
    """Load an existing token from file, or return None if missing."""
    if not os.path.isfile(token_path):
        return None
    with open(token_path) as f:
        return f.read().strip()


def validate_token(candidate: str, token_path: str) -> bool:
    """Constant-time comparison of *candidate* against the stored token."""
    if not candidate:
        return False
    stored = load_token(token_path)
    if stored is None:
        return False
    return hmac.compare_digest(candidate, stored)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Documents/workspace/PieOffice && PYTHONPATH=backend pytest tests/test_terminal_auth.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/terminal_auth.py tests/test_terminal_auth.py
git commit -m "feat: add token-based auth for web terminal"
```

---

## Task 3: Terminal WebSocket Handler

**Files:**
- Create: `backend/terminal.py`
- Test: `tests/test_terminal.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_terminal.py
"""Tests for terminal session management."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from terminal import (
    TmuxSession,
    list_tmux_sessions,
    parse_tmux_list,
)


class TestParseTmuxList:
    def test_parse_single_session(self):
        raw = "claude-abc123:1:0:/Users/temple/workspace/mcp-giboo"
        sessions = parse_tmux_list(raw)
        assert len(sessions) == 1
        assert sessions[0].name == "claude-abc123"
        assert sessions[0].windows == 1
        assert sessions[0].attached == 0
        assert sessions[0].cwd == "/Users/temple/workspace/mcp-giboo"

    def test_parse_multiple_sessions(self):
        raw = (
            "claude-abc:2:1:/Users/temple/a\n"
            "claude-def:1:0:/Users/temple/b"
        )
        sessions = parse_tmux_list(raw)
        assert len(sessions) == 2

    def test_parse_empty(self):
        assert parse_tmux_list("") == []
        assert parse_tmux_list("\n") == []

    def test_parse_attached_session(self):
        raw = "claude-abc:1:1:/Users/temple/a"
        sessions = parse_tmux_list(raw)
        assert sessions[0].attached == 1


class TestListTmuxSessions:
    @patch("terminal.subprocess.run")
    def test_list_filters_claude_sessions(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="claude-abc:1:0:/tmp\nother-session:1:0:/tmp\nclaude-def:1:0:/tmp",
        )
        sessions = list_tmux_sessions()
        assert len(sessions) == 2
        assert all(s.name.startswith("claude-") for s in sessions)

    @patch("terminal.subprocess.run")
    def test_list_empty_when_no_tmux(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        sessions = list_tmux_sessions()
        assert sessions == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Documents/workspace/PieOffice && PYTHONPATH=backend pytest tests/test_terminal.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'terminal'"

- [ ] **Step 3: Write implementation**

```python
# backend/terminal.py
"""Web terminal: tmux session listing, pty attach via WebSocket, caffeinate."""

import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from config import TERMINAL_IDLE_TIMEOUT, TERMINAL_TOKEN_PATH
from terminal_auth import validate_token


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
        ["tmux", "list-sessions", "-F", "#{session_name}:#{session_windows}:#{session_attached}:#{pane_current_path}"],
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


def handle_terminal_ws(ws, session_name: str) -> None:
    """WebSocket handler: attach to a tmux session and relay I/O.

    Protocol:
    - Client sends JSON: {"type": "auth", "token": "..."} first
    - After auth, client sends JSON: {"type": "input", "data": "..."} for keystrokes
    - Client sends JSON: {"type": "resize", "cols": N, "rows": N} for resize
    - Server sends JSON: {"type": "output", "data": "..."} for terminal output
    - Server sends JSON: {"type": "error", "message": "..."} on errors
    """

    # --- Auth handshake ---
    try:
        raw = ws.receive(timeout=10)
        if raw is None:
            return
        msg = json.loads(raw)
        if msg.get("type") != "auth" or not validate_token(msg.get("token", ""), TERMINAL_TOKEN_PATH):
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

    # Spawn tmux attach in a pty
    pid, fd = pty.openpty()
    proc = subprocess.Popen(
        ["tmux", "attach-session", "-t", session_name],
        stdin=fd,
        stdout=fd,
        stderr=fd,
        close_fds=True,
        preexec_fn=os.setsid,
    )
    os.close(fd)  # parent doesn't need the slave side

    # --- I/O relay ---
    stop = threading.Event()

    def _read_pty():
        """Read from pty master (pid) and send to WebSocket."""
        try:
            while not stop.is_set():
                r, _, _ = select.select([pid], [], [], 1.0)
                if r:
                    try:
                        data = os.read(pid, 4096)
                        if not data:
                            break
                        ws.send(json.dumps({"type": "output", "data": data.decode("utf-8", errors="replace")}))
                    except OSError:
                        break
        except Exception:
            pass
        finally:
            stop.set()

    reader = threading.Thread(target=_read_pty, daemon=True)
    reader.start()

    try:
        while not stop.is_set():
            raw = ws.receive(timeout=2)
            if raw is None:
                break
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue

            if msg.get("type") == "input":
                data = msg.get("data", "")
                if data:
                    os.write(pid, data.encode("utf-8"))

            elif msg.get("type") == "resize":
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                import struct
                import fcntl
                import termios
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(pid, termios.TIOCSWINSZ, winsize)

    except Exception as e:
        print(f"[Terminal] WebSocket error: {e}", file=sys.stderr)
    finally:
        stop.set()
        caffeinate.release()
        try:
            os.close(pid)
        except OSError:
            pass
        proc.terminate()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Documents/workspace/PieOffice && PYTHONPATH=backend pytest tests/test_terminal.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/terminal.py tests/test_terminal.py
git commit -m "feat: add terminal WebSocket handler with tmux attach + caffeinate"
```

---

## Task 4: Integrate Terminal Routes into Flask App

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add imports to app.py**

After the existing imports at the top of `app.py`, add:

```python
from flask_sock import Sock
from terminal import handle_terminal_ws, list_tmux_sessions, caffeinate
from terminal_auth import generate_token, validate_token
from config import TERMINAL_LAN_MODE, TERMINAL_TOKEN_PATH, TERMINAL_TLS_CERT, TERMINAL_TLS_KEY
```

- [ ] **Step 2: Initialize flask-sock**

After `announcer = MessageAnnouncer()` (line 102), add:

```python
sock = Sock(app)
```

- [ ] **Step 3: Add terminal routes**

Before the `# Stale agent sweep` section, add:

```python
# ---------------------------------------------------------------------------
# Terminal routes
# ---------------------------------------------------------------------------


@app.route("/terminal")
def terminal_page():
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), "terminal.html")


@app.route("/terminal/sessions")
def terminal_sessions():
    """List available Claude tmux sessions (requires token in Authorization header)."""
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not validate_token(token, TERMINAL_TOKEN_PATH):
        return jsonify({"error": "unauthorized"}), 401
    sessions = list_tmux_sessions()
    return jsonify({
        "sessions": [
            {"name": s.name, "windows": s.windows, "attached": s.attached, "cwd": s.cwd}
            for s in sessions
        ]
    })


@sock.route("/terminal/ws/<session_name>")
def terminal_ws(ws, session_name):
    """WebSocket endpoint for terminal I/O relay to a tmux session."""
    handle_terminal_ws(ws, session_name)
```

- [ ] **Step 4: Update CORS for LAN mode**

Replace the CORS line (line 101) with:

```python
if TERMINAL_LAN_MODE:
    # LAN mode: accept any origin (network is trusted, token auth protects terminal)
    CORS(app)
else:
    CORS(app, origins=[
        "http://localhost:10317", "http://localhost:10318",
        "http://127.0.0.1:10317", "http://127.0.0.1:10318",
    ])
```

- [ ] **Step 5: Update main block for LAN + TLS**

Replace the `if __name__ == "__main__":` block with:

```python
if __name__ == "__main__":
    print(f"Pie Office backend starting on :{PORT} (theme={THEME})")
    import socketserver

    from config import SOCKET_TIMEOUT
    from werkzeug.serving import WSGIRequestHandler

    socketserver.TCPServer.timeout = SOCKET_TIMEOUT
    WSGIRequestHandler.timeout = SOCKET_TIMEOUT

    host = "0.0.0.0" if TERMINAL_LAN_MODE else "127.0.0.1"
    ssl_ctx = None
    if TERMINAL_LAN_MODE:
        # Generate token on startup if not exists
        token = generate_token(TERMINAL_TOKEN_PATH)
        print(f"[Terminal] LAN mode enabled — host={host}", file=sys.stderr)
        print(f"[Terminal] Auth token: {token}", file=sys.stderr)
        # TLS
        if os.path.isfile(TERMINAL_TLS_CERT) and os.path.isfile(TERMINAL_TLS_KEY):
            ssl_ctx = (TERMINAL_TLS_CERT, TERMINAL_TLS_KEY)
            print(f"[Terminal] TLS enabled", file=sys.stderr)
        else:
            print(f"[Terminal] WARNING: No TLS cert found. Run setup-terminal.sh first.", file=sys.stderr)

    app.run(host=host, port=PORT, threaded=True, debug=False, ssl_context=ssl_ctx)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app.py
git commit -m "feat: integrate terminal WebSocket routes into Flask app"
```

---

## Task 5: Frontend Terminal Page (Slack-style UI + Auto-sync)

**Files:**
- Create: `frontend/terminal.html`
- Create: `frontend/js/terminal-client.js`

**Design:** Slack-inspired layout — left sidebar with session list (like DM channels), right panel with terminal. On mobile (phone), sidebar collapses into a slide-out drawer. Session list auto-syncs every 5 seconds so new/closed sessions appear without manual refresh.

- [ ] **Step 1: Create terminal.html**

```html
<!-- frontend/terminal.html -->
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
  <title>Pie Office Terminal</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css" />
  <style>
    *, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }

    :root {
      --sidebar-w: 260px;
      --bg-primary: #1a1a2e;
      --bg-sidebar: #19171D;
      --bg-sidebar-hover: #27242C;
      --bg-sidebar-active: #1164A3;
      --bg-header: #212529;
      --text-primary: #D1D2D3;
      --text-secondary: #ABABAD;
      --text-muted: #696969;
      --accent: #E8D44D;
      --green: #2BAC76;
      --red: #E01E5A;
      --border: #383538;
    }

    body {
      background: var(--bg-primary);
      color: var(--text-primary);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      height: 100vh; height: 100dvh;
      width: 100vw;
      overflow: hidden;
    }

    /* ── Auth Screen ───────────────────────────────────── */
    #auth-screen {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      gap: 16px;
    }
    #auth-screen h1 { font-size: 20px; color: var(--accent); font-weight: 700; }
    #auth-screen input {
      background: var(--bg-sidebar);
      color: var(--text-primary);
      border: 1px solid var(--border);
      padding: 12px 16px;
      font-size: 16px;
      width: min(320px, 80vw);
      border-radius: 8px;
      outline: none;
    }
    #auth-screen input:focus { border-color: var(--bg-sidebar-active); }
    #auth-screen button {
      background: var(--bg-sidebar-active);
      color: #fff;
      border: none;
      padding: 12px 32px;
      font-size: 15px;
      border-radius: 8px;
      cursor: pointer;
      font-weight: 600;
    }
    #auth-error { color: var(--red); font-size: 13px; }

    /* ── Main Layout (Slack-style) ─────────────────────── */
    #main-layout {
      display: none;
      height: 100%;
      flex-direction: row;
    }

    /* ── Sidebar ───────────────────────────────────────── */
    #sidebar {
      width: var(--sidebar-w);
      min-width: var(--sidebar-w);
      background: var(--bg-sidebar);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    #sidebar-header {
      padding: 16px 16px 12px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    #sidebar-header h2 {
      font-size: 15px;
      font-weight: 700;
      color: var(--text-primary);
    }
    #sidebar-header .sync-indicator {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--green);
      display: inline-block;
      margin-left: 8px;
    }
    #sidebar-header .sync-indicator.syncing {
      animation: pulse 1s infinite;
    }
    @keyframes pulse { 50% { opacity: 0.3; } }

    .section-label {
      padding: 12px 16px 4px;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    #session-list {
      flex: 1;
      overflow-y: auto;
      padding: 4px 8px;
    }

    .session-item {
      display: flex;
      align-items: center;
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      gap: 10px;
      margin-bottom: 2px;
      transition: background 0.1s;
    }
    .session-item:hover { background: var(--bg-sidebar-hover); }
    .session-item.active { background: var(--bg-sidebar-active); }
    .session-item.active .session-name { color: #fff; font-weight: 700; }
    .session-item.active .session-cwd { color: rgba(255,255,255,0.7); }

    .session-status {
      width: 9px; height: 9px;
      border-radius: 50%;
      flex-shrink: 0;
    }
    .session-status.attached { background: var(--green); }
    .session-status.detached { background: var(--text-muted); border: 1.5px solid var(--text-muted); background: transparent; }

    .session-info { overflow: hidden; }
    .session-name {
      font-size: 14px;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .session-cwd {
      font-size: 11px;
      color: var(--text-muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .no-sessions {
      padding: 16px;
      font-size: 13px;
      color: var(--text-muted);
      text-align: center;
      line-height: 1.5;
    }

    /* ── Right Panel ───────────────────────────────────── */
    #right-panel {
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    #terminal-header {
      padding: 8px 16px;
      background: var(--bg-header);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 44px;
    }
    #terminal-header .session-title {
      font-size: 14px;
      font-weight: 700;
    }
    #terminal-header .status {
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    #terminal-header .status-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
    }
    .status-dot.connected { background: var(--green); }
    .status-dot.disconnected { background: var(--red); }
    .status-dot.connecting { background: var(--accent); animation: pulse 1s infinite; }

    #terminal-container {
      flex: 1;
      overflow: hidden;
    }

    #empty-state {
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-muted);
      font-size: 15px;
    }

    /* ── Mobile: sidebar as slide-out drawer ────────────── */
    #sidebar-toggle {
      display: none;
      position: fixed;
      top: 8px;
      left: 8px;
      z-index: 100;
      background: var(--bg-sidebar);
      border: 1px solid var(--border);
      color: var(--text-primary);
      width: 36px; height: 36px;
      border-radius: 8px;
      font-size: 18px;
      cursor: pointer;
      align-items: center;
      justify-content: center;
    }
    #sidebar-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.5);
      z-index: 49;
    }

    @media (max-width: 600px) {
      #sidebar {
        position: fixed;
        left: calc(-1 * var(--sidebar-w));
        top: 0; bottom: 0;
        z-index: 50;
        transition: left 0.25s ease;
      }
      #sidebar.open { left: 0; }
      #sidebar-overlay.open { display: block; }
      #sidebar-toggle { display: flex; }
      #terminal-header { padding-left: 52px; }
    }
  </style>
</head>
<body>
  <!-- Auth Screen -->
  <div id="auth-screen">
    <h1>Pie Office Terminal</h1>
    <input type="password" id="token-input" placeholder="Enter access token" autocomplete="off" />
    <button onclick="authenticate()">Connect</button>
    <div id="auth-error"></div>
  </div>

  <!-- Main Layout (shown after auth) -->
  <div id="main-layout">
    <!-- Mobile sidebar toggle -->
    <button id="sidebar-toggle" onclick="toggleSidebar()">&#9776;</button>
    <div id="sidebar-overlay" onclick="toggleSidebar()"></div>

    <!-- Sidebar (Slack channel list style) -->
    <div id="sidebar">
      <div id="sidebar-header">
        <h2>Claude Sessions <span id="sync-dot" class="sync-indicator"></span></h2>
      </div>
      <div class="section-label">Active</div>
      <div id="session-list"></div>
    </div>

    <!-- Right panel -->
    <div id="right-panel">
      <div id="terminal-header" style="display:none;">
        <span class="session-title" id="session-title"></span>
        <span class="status">
          <span class="status-dot" id="status-dot"></span>
          <span id="status-text"></span>
        </span>
      </div>
      <div id="empty-state">Select a session from the sidebar</div>
      <div id="terminal-container"></div>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/lib/addon-web-links.min.js"></script>
  <script src="/static/js/terminal-client.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create terminal-client.js**

```javascript
// frontend/js/terminal-client.js
// Slack-style terminal client with auto-sync session list

(function () {
  "use strict";

  const SYNC_INTERVAL = 5000; // Auto-sync session list every 5s

  let token = localStorage.getItem("pie-terminal-token") || "";
  let ws = null;
  let term = null;
  let fitAddon = null;
  let currentSession = null;
  let reconnectTimeout = null;
  let syncTimer = null;
  let lastSessionsJson = "";

  // ── Auth ──────────────────────────────────────────────

  window.authenticate = function () {
    const input = document.getElementById("token-input");
    token = input.value.trim();
    if (!token) return;
    localStorage.setItem("pie-terminal-token", token);
    fetchSessionsAndShow();
  };

  // Auto-auth if token saved
  if (token) {
    fetchSessionsAndShow();
  }

  // ── Session List (auto-sync) ──────────────────────────

  function fetchSessions() {
    return fetch(`${location.origin}/terminal/sessions`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then((r) => {
      if (r.status === 401) {
        localStorage.removeItem("pie-terminal-token");
        location.reload();
        return null;
      }
      return r.json();
    });
  }

  function fetchSessionsAndShow() {
    const dot = document.getElementById("sync-dot");
    if (dot) dot.classList.add("syncing");

    fetchSessions()
      .then((data) => {
        if (!data) return;
        showMainLayout();
        renderSessionList(data.sessions);
        startAutoSync();
      })
      .catch(() => {
        document.getElementById("auth-error").textContent = "Connection failed";
      })
      .finally(() => {
        if (dot) dot.classList.remove("syncing");
      });
  }

  function startAutoSync() {
    if (syncTimer) return;
    syncTimer = setInterval(() => {
      const dot = document.getElementById("sync-dot");
      if (dot) dot.classList.add("syncing");

      fetchSessions()
        .then((data) => {
          if (!data) return;
          // Only re-render if sessions changed (avoid flicker)
          const json = JSON.stringify(data.sessions);
          if (json !== lastSessionsJson) {
            renderSessionList(data.sessions);
          }
        })
        .finally(() => {
          if (dot) dot.classList.remove("syncing");
        });
    }, SYNC_INTERVAL);
  }

  function showMainLayout() {
    document.getElementById("auth-screen").style.display = "none";
    document.getElementById("main-layout").style.display = "flex";
  }

  function renderSessionList(sessions) {
    lastSessionsJson = JSON.stringify(sessions);
    const list = document.getElementById("session-list");
    list.innerHTML = "";

    if (sessions.length === 0) {
      list.innerHTML = '<div class="no-sessions">No active sessions.<br>Start Claude with the tmux wrapper.</div>';
      return;
    }

    sessions.forEach((s) => {
      const item = document.createElement("div");
      item.className = "session-item" + (s.name === currentSession ? " active" : "");
      item.onclick = () => {
        connectSession(s.name);
        closeSidebarOnMobile();
      };

      const statusClass = s.attached > 0 ? "attached" : "detached";
      const shortCwd = s.cwd.replace(/^\/Users\/[^/]+\//, "~/");
      // Extract project name from session name: claude-<hash> → show cwd basename
      const projectName = shortCwd.split("/").pop() || s.name;

      item.innerHTML = `
        <span class="session-status ${statusClass}"></span>
        <div class="session-info">
          <div class="session-name">${projectName}</div>
          <div class="session-cwd">${shortCwd}</div>
        </div>
      `;
      list.appendChild(item);
    });
  }

  // ── Sidebar toggle (mobile) ───────────────────────────

  window.toggleSidebar = function () {
    document.getElementById("sidebar").classList.toggle("open");
    document.getElementById("sidebar-overlay").classList.toggle("open");
  };

  function closeSidebarOnMobile() {
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("sidebar-overlay").classList.remove("open");
  }

  // ── Terminal Connection ────────────────────────────────

  function connectSession(sessionName) {
    if (ws) ws.close();
    if (reconnectTimeout) { clearTimeout(reconnectTimeout); reconnectTimeout = null; }
    currentSession = sessionName;

    // Update sidebar active state
    document.querySelectorAll(".session-item").forEach((el) => {
      el.classList.toggle("active", el.querySelector(".session-name").textContent ===
        (el.querySelector(".session-name").textContent)); // re-render handles this
    });
    // Re-render to update active state cleanly
    if (lastSessionsJson) {
      renderSessionList(JSON.parse(lastSessionsJson));
    }

    // Show terminal header
    const header = document.getElementById("terminal-header");
    header.style.display = "flex";
    document.getElementById("session-title").textContent = sessionName;
    setStatus("connecting", "Connecting...");

    // Hide empty state, show terminal
    document.getElementById("empty-state").style.display = "none";
    const termContainer = document.getElementById("terminal-container");
    termContainer.style.display = "block";
    termContainer.innerHTML = "";

    // Init xterm.js
    term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: '"Menlo", "Courier New", monospace',
      theme: {
        background: "#1a1a2e",
        foreground: "#D1D2D3",
        cursor: "#E8D44D",
        selectionBackground: "rgba(81,54,131,0.5)",
        black: "#1a1a2e",
        brightBlack: "#696969",
      },
      allowProposedApi: true,
    });

    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon.WebLinksAddon());
    term.open(termContainer);

    // Delay fit to ensure container has dimensions
    requestAnimationFrame(() => fitAddon.fit());

    // WebSocket
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${wsProto}://${location.host}/terminal/ws/${sessionName}`);

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token: token }));
    };

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "connected") {
        setStatus("connected", "Connected");
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      } else if (msg.type === "output") {
        term.write(msg.data);
      } else if (msg.type === "error") {
        setStatus("disconnected", msg.message);
        term.write(`\r\n\x1b[31m${msg.message}\x1b[0m\r\n`);
      }
    };

    ws.onclose = () => {
      setStatus("disconnected", "Disconnected");
      scheduleReconnect(sessionName);
    };

    ws.onerror = () => setStatus("disconnected", "Error");

    // Input relay
    term.onData((data) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "input", data: data }));
      }
    });

    // Resize handling
    const onResize = () => { if (fitAddon) fitAddon.fit(); };
    window.removeEventListener("resize", onResize); // prevent duplicates
    window.addEventListener("resize", onResize);

    term.onResize(({ cols, rows }) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "resize", cols, rows }));
      }
    });
  }

  function setStatus(state, text) {
    const dot = document.getElementById("status-dot");
    const label = document.getElementById("status-text");
    if (dot) dot.className = "status-dot " + state;
    if (label) label.textContent = text;
  }

  function scheduleReconnect(sessionName) {
    if (reconnectTimeout) clearTimeout(reconnectTimeout);
    reconnectTimeout = setTimeout(() => {
      if (currentSession === sessionName) connectSession(sessionName);
    }, 3000);
  }
})();
```

- [ ] **Step 3: Test manually in browser**

Run: `cd ~/Documents/workspace/PieOffice && source venv/bin/activate && PIE_TERMINAL_LAN=1 PORT=10318 python3 backend/app.py`
Open: `https://<mac-ip>:10318/terminal` on phone browser

Verify:
- Auth screen → enter token → Slack-style sidebar appears
- Sessions auto-refresh every 5s (green dot pulses during sync)
- On mobile: hamburger menu toggles sidebar drawer
- Tapping session connects terminal in right panel
- Start a new `claude` session in another terminal → appears in sidebar within 5s
- Close a claude session → disappears from sidebar within 5s

- [ ] **Step 4: Commit**

```bash
git add frontend/terminal.html frontend/js/terminal-client.js
git commit -m "feat: add Slack-style terminal frontend with auto-sync session list"
```

---

## Task 6: Setup Script (TLS + Token + Tmux Wrapper)

**Files:**
- Create: `scripts/setup-terminal.sh`
- Create: `scripts/claude`

- [ ] **Step 1: Create setup-terminal.sh**

```bash
#!/bin/bash
# setup-terminal.sh — Generate TLS cert, auth token, install tmux wrapper
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TLS_DIR="$HOME/.pieoffice-tls"
TOKEN_PATH="$HOME/.pieoffice-terminal-token"
WRAPPER_DIR="$HOME/.local/bin"

echo "=== Pie Office Terminal Setup ==="
echo ""

# 1. TLS cert
echo "[1/3] TLS certificate..."
mkdir -p "$TLS_DIR"
if [ -f "$TLS_DIR/cert.pem" ]; then
    echo "  Already exists: $TLS_DIR/cert.pem"
else
    # Get Mac's LAN IP
    LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || echo "192.168.1.1")
    echo "  LAN IP detected: $LAN_IP"

    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$TLS_DIR/key.pem" \
        -out "$TLS_DIR/cert.pem" \
        -days 365 \
        -subj "/CN=PieOffice" \
        -addext "subjectAltName=IP:$LAN_IP,IP:127.0.0.1,DNS:localhost" \
        2>/dev/null
    chmod 600 "$TLS_DIR/key.pem"
    echo "  Generated: $TLS_DIR/cert.pem (valid 365 days)"
fi

# 2. Auth token
echo "[2/3] Auth token..."
if [ -f "$TOKEN_PATH" ]; then
    echo "  Already exists: $TOKEN_PATH"
    echo "  Token: $(cat "$TOKEN_PATH")"
else
    TOKEN=$(openssl rand -hex 32)
    echo -n "$TOKEN" > "$TOKEN_PATH"
    chmod 600 "$TOKEN_PATH"
    echo "  Generated: $TOKEN_PATH"
    echo ""
    echo "  ┌──────────────────────────────────────────────────────────────────┐"
    echo "  │  SAVE THIS TOKEN ON YOUR PHONE:                                 │"
    echo "  │  $TOKEN  │"
    echo "  └──────────────────────────────────────────────────────────────────┘"
    echo ""
fi

# 3. Tmux wrapper
echo "[3/3] Claude tmux wrapper..."
mkdir -p "$WRAPPER_DIR"
cp "$DIR/claude" "$WRAPPER_DIR/claude"
chmod +x "$WRAPPER_DIR/claude"
echo "  Installed: $WRAPPER_DIR/claude"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$WRAPPER_DIR:"* ]]; then
    echo ""
    echo "  Add to your ~/.zshrc:"
    echo "    export PATH=\"$WRAPPER_DIR:\$PATH\""
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Usage:"
echo "  1. Start Pie Office in LAN mode:"
echo "     PIE_TERMINAL_LAN=1 ./dev.sh 10317"
echo ""
echo "  2. Start Claude via tmux wrapper:"
echo "     claude              # uses 'claude' under the hood"
echo ""
echo "  3. On your phone, open:"
echo "     https://$(ipconfig getifaddr en0 2>/dev/null || echo '<mac-ip>'):10317/terminal"
```

- [ ] **Step 2: Create claude tmux wrapper**

```bash
#!/bin/bash
# claude — tmux wrapper for claude code
# Ensures each claude session runs inside tmux for web terminal sharing.

# Generate a short session name from the working directory
DIR_HASH=$(echo -n "$(pwd)" | md5 -q | head -c 8)
SESSION_NAME="claude-${DIR_HASH}"

# If already inside tmux, just run claude directly
if [ -n "$TMUX" ]; then
    exec claude "$@"
fi

# If session already exists, attach to it
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    exec tmux attach-session -t "$SESSION_NAME"
fi

# Create new tmux session running claude
exec tmux new-session -s "$SESSION_NAME" -- claude "$@"
```

- [ ] **Step 3: Make executable and test**

Run:
```bash
chmod +x ~/Documents/workspace/PieOffice/scripts/setup-terminal.sh
chmod +x ~/Documents/workspace/PieOffice/scripts/claude
```

- [ ] **Step 4: Commit**

```bash
git add scripts/setup-terminal.sh scripts/claude
git commit -m "feat: add terminal setup script and claude tmux wrapper"
```

---

## Task 7: iOS Shortcut Documentation

**Files:**
- Create: `docs/ios-shortcut-setup.md`

- [ ] **Step 1: Write iOS shortcut guide**

```markdown
# iOS Shortcut: Wake Mac + Open Terminal

## Prerequisites

- Mac and iPhone on the same WiFi network
- Mac "Wake for network access" enabled:
  System Settings → Battery → Options → "Wake for network access"
- Mac's MAC address (run `ifconfig en0 | grep ether` on Mac)
- Pie Office terminal set up (`./scripts/setup-terminal.sh`)

## Create the Shortcut

1. Open **Shortcuts** app on iPhone
2. Tap **+** to create new shortcut
3. Name it: "Mac Terminal"

### Actions:

**Action 1: Wake on LAN**
- Search for "Wake on LAN" or "Send WoL"
- If not available natively, use "Get contents of URL":
  - This sends a magic packet via a free WoL service
  - Alternative: search "WoL" in Shortcuts Gallery

**Action 2: Wait**
- Add "Wait" action → set to **90 seconds**

**Action 3: Open URL**
- Add "Open URLs" action
- URL: `https://<mac-ip>:10317/terminal`
  - Replace `<mac-ip>` with your Mac's LAN IP

### Add to Home Screen:
- Tap share icon → "Add to Home Screen"
- One tap: wake Mac → wait → open terminal

## Tips

- Save the auth token in iPhone Notes or iCloud Keychain
- On first HTTPS visit, Safari will warn about self-signed cert → tap "Advanced" → "Proceed"
- Token is saved in browser localStorage after first login
```

- [ ] **Step 2: Commit**

```bash
git add docs/ios-shortcut-setup.md
git commit -m "docs: add iOS shortcut setup guide for WoL + terminal"
```

---

## Task 8: Update CLAUDE.md and dev.sh

**Files:**
- Modify: `CLAUDE.md`
- Modify: `dev.sh`

- [ ] **Step 1: Add terminal section to CLAUDE.md**

Add after the "Instance alerts" bullet in the Key Conventions section:

```markdown
- Web terminal: `/terminal` page serves xterm.js UI that connects to Claude tmux sessions via WebSocket (`flask-sock`). Auth via bearer token (`~/.pieoffice-terminal-token`). LAN mode (`PIE_TERMINAL_LAN=1`) enables `0.0.0.0` binding + TLS. `caffeinate` keeps Mac awake during active terminal sessions.
```

- [ ] **Step 2: Update dev.sh for LAN mode option**

```bash
#!/bin/bash
# Pie Office dev server launcher
# Usage: ./dev.sh [port] [--lan]
PORT=${1:-10317}
LAN_MODE=""
for arg in "$@"; do
    if [ "$arg" = "--lan" ]; then
        LAN_MODE=1
    fi
done
DIR="$(cd "$(dirname "$0")" && pwd)"

# Kill existing process on port
lsof -ti:"$PORT" 2>/dev/null | xargs kill -9 2>/dev/null

# Activate venv and start server
cd "$DIR"
source venv/bin/activate
echo "Starting Pie Office on :$PORT ..."
PIE_TERMINAL_LAN=$LAN_MODE PORT=$PORT python3 backend/app.py
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md dev.sh
git commit -m "docs: add terminal conventions to CLAUDE.md, add --lan flag to dev.sh"
```

---

## Task 9: Integration Test

**Files:**
- Create: `tests/test_terminal_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/test_terminal_integration.py
"""Integration tests for terminal routes."""

import os
import sys
import tempfile

import pytest

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from terminal_auth import generate_token


@pytest.fixture
def token_path(tmp_path):
    path = str(tmp_path / "token")
    generate_token(path)
    return path


@pytest.fixture
def app_client(token_path, monkeypatch):
    monkeypatch.setenv("PIE_TERMINAL_TOKEN_PATH", token_path)
    # Re-import config to pick up new env
    import importlib
    import config
    importlib.reload(config)

    # Import app after config reload
    import app as flask_app
    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


class TestTerminalRoutes:
    def test_terminal_page_returns_html(self, app_client):
        resp = app_client.get("/terminal")
        assert resp.status_code == 200

    def test_sessions_requires_auth(self, app_client):
        resp = app_client.get("/terminal/sessions")
        assert resp.status_code == 401

    def test_sessions_with_valid_token(self, app_client, token_path):
        with open(token_path) as f:
            token = f.read().strip()
        resp = app_client.get(
            "/terminal/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "sessions" in data

    def test_sessions_with_invalid_token(self, app_client):
        resp = app_client.get(
            "/terminal/sessions",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
```

- [ ] **Step 2: Run integration tests**

Run: `cd ~/Documents/workspace/PieOffice && PYTHONPATH=backend pytest tests/test_terminal_integration.py -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_terminal_integration.py
git commit -m "test: add terminal route integration tests"
```

---

## Task 10: End-to-End Manual Verification

- [ ] **Step 1: Run setup script**

```bash
cd ~/Documents/workspace/PieOffice && ./scripts/setup-terminal.sh
```
Expected: TLS cert generated, token shown, claude wrapper installed

- [ ] **Step 2: Start Pie Office in LAN mode**

```bash
./dev.sh 10318 --lan
```
Expected: Server starts on 0.0.0.0:10318 with TLS

- [ ] **Step 3: Start a Claude session via wrapper**

```bash
claude
```
Expected: tmux session created with name `claude-<hash>`

- [ ] **Step 4: Open terminal from phone**

Open: `https://<mac-ip>:10318/terminal`
Enter token → select session → verify terminal works

- [ ] **Step 5: Verify shared session**

Type in phone terminal → see output on laptop tmux
Type in laptop tmux → see output in phone terminal

- [ ] **Step 6: Verify caffeinate**

```bash
pgrep caffeinate
```
Expected: caffeinate process running while terminal is connected

- [ ] **Step 7: Disconnect and verify sleep**

Close phone browser tab → wait 5 minutes → verify caffeinate stopped:
```bash
pgrep caffeinate  # should return nothing
```
