"""Standalone asyncio terminal server — mTLS + WebSocket + pty.

Runs as a separate process (not Flask thread) so pty.fork() is safe.
Serves session list, auth, and terminal WebSocket on a single port.

Started by app.py via subprocess when TERMINAL_LAN_MODE is enabled,
or run standalone:
    python3 terminal_server.py
"""

import asyncio
import json
import os
import pty
import select
import signal
import ssl
import struct
import subprocess
import sys
import fcntl
import termios

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as terminal_config
from terminal import list_tmux_sessions, caffeinate
from terminal_auth import SessionTokenStore

TERMINAL_PORT = int(os.environ.get("TERMINAL_PORT", 10316))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

session_tokens = SessionTokenStore(ttl=terminal_config.TERMINAL_SESSION_TOKEN_TTL)


# ---------------------------------------------------------------------------
# HTTP handler (session list, token, static files)
# ---------------------------------------------------------------------------

async def handle_http(path, headers):
    """Handle HTTP requests (non-WebSocket)."""
    auth = headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()

    if path == "/" or path == "":
        html_path = os.path.join(PROJECT_ROOT, "frontend", "terminal.html")
        with open(html_path, "rb") as f:
            body = f.read()
        return 200, [("Content-Type", "text/html")], body

    if path.startswith("/static/"):
        file_path = os.path.join(PROJECT_ROOT, "frontend", path[len("/static/"):])
        if os.path.isfile(file_path):
            ct = "application/javascript" if file_path.endswith(".js") else "text/css"
            with open(file_path, "rb") as f:
                body = f.read()
            return 200, [("Content-Type", ct)], body
        return 404, [], b"Not found"

    if path == "/session-token":
        tok = session_tokens.issue()
        return 200, [("Content-Type", "application/json")], json.dumps({"token": tok}).encode()

    if path == "/sessions":
        if not session_tokens.validate(token):
            return 401, [("Content-Type", "application/json")], b'{"error":"unauthorized"}'
        sessions = list_tmux_sessions()
        data = {
            "sessions": [
                {"name": s.name, "windows": s.windows, "attached": s.attached, "cwd": s.cwd}
                for s in sessions
            ]
        }
        return 200, [("Content-Type", "application/json")], json.dumps(data).encode()

    if path == "/health":
        data = {"status": "ok", "active_tokens": session_tokens.active_count}
        return 200, [("Content-Type", "application/json")], json.dumps(data).encode()

    return 404, [], b"Not found"


# ---------------------------------------------------------------------------
# WebSocket terminal handler (pty.fork — safe in asyncio, no Flask threads)
# ---------------------------------------------------------------------------

async def handle_terminal(websocket, session_name):
    """Handle a terminal WebSocket connection using pty.fork()."""

    # Auth handshake
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") != "auth" or not session_tokens.validate(msg.get("token", "")):
            await websocket.send(json.dumps({"type": "error", "message": "unauthorized"}))
            return
    except Exception:
        return

    # Verify session exists
    sessions = list_tmux_sessions()
    if not any(s.name == session_name for s in sessions):
        await websocket.send(json.dumps({"type": "error", "message": "session not found"}))
        return

    await websocket.send(json.dumps({"type": "connected", "session": session_name}))
    caffeinate.acquire()

    # Fork a child process with a pty — safe here because we're in asyncio, not Flask threads
    child_pid, master_fd = pty.fork()

    if child_pid == 0:
        # Child: exec tmux attach
        os.execlp("tmux", "tmux", "attach-session", "-t", session_name)
        os._exit(1)

    print(f"[Terminal] Connected to '{session_name}' (child={child_pid})", file=sys.stderr)

    loop = asyncio.get_event_loop()
    stop = False

    # Read from pty master → send to WebSocket
    async def read_pty():
        nonlocal stop
        try:
            while not stop:
                # Use executor for blocking select/read
                data = await loop.run_in_executor(None, _read_master, master_fd)
                if data is None:
                    break
                await websocket.send(json.dumps({
                    "type": "output",
                    "data": data.decode("utf-8", errors="replace"),
                }))
        except Exception as e:
            if not stop:
                print(f"[Terminal] pty reader error: {e}", file=sys.stderr)
        finally:
            stop = True

    reader_task = asyncio.create_task(read_pty())

    # Read from WebSocket → write to pty master
    try:
        async for raw in websocket:
            if stop:
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
                    os.write(master_fd, data.encode("utf-8"))

            elif msg_type == "resize":
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

    except Exception as e:
        print(f"[Terminal] WebSocket error: {e}", file=sys.stderr)
    finally:
        stop = True
        reader_task.cancel()
        caffeinate.release()
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.kill(child_pid, signal.SIGTERM)
            os.waitpid(child_pid, 0)
        except OSError:
            pass
        print(f"[Terminal] Disconnected from '{session_name}'", file=sys.stderr)


def _read_master(master_fd):
    """Blocking read from pty master. Returns None on EOF/error."""
    try:
        r, _, _ = select.select([master_fd], [], [], 1.0)
        if r:
            data = os.read(master_fd, 4096)
            return data if data else None
        return b""  # timeout, not EOF
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Server setup with mTLS
# ---------------------------------------------------------------------------

def create_ssl_context():
    """Create SSL context with optional mTLS."""
    cert = terminal_config.TERMINAL_TLS_CERT
    key = terminal_config.TERMINAL_TLS_KEY
    ca = terminal_config.TERMINAL_TLS_CA

    if not (os.path.isfile(cert) and os.path.isfile(key)):
        print("[Terminal] ERROR: TLS cert/key not found. Run setup-terminal.sh first.",
              file=sys.stderr)
        return None

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)

    if os.path.isfile(ca):
        ctx.load_verify_locations(ca)
        ctx.verify_mode = ssl.CERT_OPTIONAL
        print("[Terminal] mTLS enabled", file=sys.stderr)
    else:
        print("[Terminal] TLS only (no mTLS — CA not found)", file=sys.stderr)

    return ctx


async def handler(websocket):
    """Route incoming connections — HTTP or WebSocket."""
    path = websocket.request.path if hasattr(websocket, 'request') else "/"

    # WebSocket paths: /ws/<session_name>
    if path.startswith("/ws/"):
        session_name = path[4:]
        await handle_terminal(websocket, session_name)
        return

    # For non-WebSocket HTTP, websockets library handles this via process_request


async def process_request(path, request_headers):
    """Handle plain HTTP requests (non-WebSocket upgrade)."""
    if path.startswith("/ws/"):
        return None  # let WebSocket handler take over

    status, headers, body = await handle_http(path, request_headers)
    return status, headers, body


async def main():
    ssl_ctx = create_ssl_context()
    if ssl_ctx is None:
        print("[Terminal] Cannot start without TLS certificates", file=sys.stderr)
        sys.exit(1)

    try:
        import websockets
    except ImportError:
        print("[Terminal] ERROR: pip install websockets", file=sys.stderr)
        sys.exit(1)

    print(f"[Terminal] Starting on https://0.0.0.0:{TERMINAL_PORT}", file=sys.stderr)

    async with websockets.serve(
        handler,
        "0.0.0.0",
        TERMINAL_PORT,
        ssl=ssl_ctx,
        process_request=process_request,
        max_size=2**20,
        ping_interval=20,
        ping_timeout=60,
    ):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())
