"""Standalone asyncio terminal server — mTLS + WebSocket + pty.

Runs as a separate process (not Flask thread) so pty.fork() is safe.
Serves session list, auth, and terminal WebSocket on a single port.

Started by app.py via subprocess when TERMINAL_LAN_MODE is enabled,
or run standalone:
    python3 terminal_server.py
"""

import asyncio
import fcntl
import json
import mimetypes
import os
import pty
import re
import select
import signal
import ssl
import struct
import sys
import termios

import urllib.request
import urllib.error

import websockets
from websockets.http11 import Response

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as terminal_config
from rate_limiter import RateLimiter
from terminal import list_tmux_sessions, caffeinate
from terminal_auth import SessionTokenStore

TERMINAL_PORT = int(os.environ.get("TERMINAL_PORT", 10316))
PIE_OFFICE_PORT = int(os.environ.get("PORT", 10317))
PIE_OFFICE_ALERTS_URL = f"http://127.0.0.1:{PIE_OFFICE_PORT}/alerts"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_ROOT = os.path.realpath(os.path.join(PROJECT_ROOT, "frontend"))

# Regex for valid tmux session names (alphanumeric, hyphens, underscores)
SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")

session_tokens = SessionTokenStore(ttl=terminal_config.TERMINAL_SESSION_TOKEN_TTL)

# Rate limiters: separate limits for different endpoints
http_limiter = RateLimiter(max_requests=30, window_seconds=60)   # 30 req/min for HTTP
ws_limiter = RateLimiter(max_requests=10, window_seconds=60)     # 10 WS connects/min

# Security headers for all HTML/JS responses
SECURITY_HEADERS = [
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
     "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; connect-src 'self' wss:"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Strict-Transport-Security", "max-age=31536000"),
]

# HTTP reason phrases
HTTP_REASONS = {200: "OK", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 429: "Too Many Requests", 503: "Service Unavailable"}


def _reason(status: int) -> str:
    return HTTP_REASONS.get(status, "Unknown")


# ---------------------------------------------------------------------------
# Pie Office alert proxy — fetch instance alerts from backend (localhost)
# ---------------------------------------------------------------------------

def _fetch_pie_office_alerts() -> dict[str, dict]:
    """Fetch pending alerts from Pie Office backend, keyed by cwd.

    Returns {cwd: {"type": ..., "message": ...}} for instances with active alerts.
    Falls back to empty dict on any error (Pie Office down, etc.).
    """
    try:
        req = urllib.request.Request(PIE_OFFICE_ALERTS_URL)
        resp = urllib.request.urlopen(req, timeout=0.5)
        data = json.loads(resp.read())
        alerts = {}
        for _sid, inst in data.items():
            cwd = inst.get("cwd", "")
            if cwd:
                alerts[cwd] = {
                    "type": inst["alert_type"],
                    "message": inst.get("alert_message", ""),
                }
        return alerts
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# HTTP handler (session list, token, static files)
# ---------------------------------------------------------------------------

async def handle_http(path, headers, *, has_client_cert: bool = False):
    """Handle HTTP requests (non-WebSocket)."""
    auth = headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()

    # Strip query string for path matching
    clean_path = path.split("?")[0]

    if clean_path == "/" or clean_path == "":
        html_path = os.path.join(PROJECT_ROOT, "frontend", "terminal.html")
        try:
            with open(html_path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            return 404, [], b"terminal.html not found"
        return 200, [("Content-Type", "text/html")] + SECURITY_HEADERS, body

    if clean_path.startswith("/static/"):
        # Path traversal protection: resolve and validate within FRONTEND_ROOT
        relative = clean_path[len("/static/"):]
        resolved = os.path.realpath(os.path.join(FRONTEND_ROOT, relative))
        if not resolved.startswith(FRONTEND_ROOT + os.sep):
            return 403, [], b"Forbidden"
        if os.path.isfile(resolved):
            ct, _ = mimetypes.guess_type(resolved)
            ct = ct or "application/octet-stream"
            with open(resolved, "rb") as f:
                body = f.read()
            return 200, [("Content-Type", ct)] + SECURITY_HEADERS, body
        return 404, [], b"Not found"

    if clean_path == "/session-token":
        # Require valid client certificate for token issuance
        if not has_client_cert:
            return 403, [("Content-Type", "application/json")], b'{"error":"client certificate required"}'
        tok = session_tokens.issue()
        if tok is None:
            return 503, [("Content-Type", "application/json")], b'{"error":"token store full"}'
        return 200, [("Content-Type", "application/json")], json.dumps({"token": tok}).encode()

    if clean_path == "/sessions":
        if not session_tokens.validate(token):
            return 401, [("Content-Type", "application/json")], b'{"error":"unauthorized"}'
        sessions = list_tmux_sessions()
        alerts_by_cwd = await asyncio.to_thread(_fetch_pie_office_alerts)
        session_list = []
        for s in sessions:
            entry = {"name": s.name, "windows": s.windows, "attached": s.attached, "cwd": s.cwd}
            alert = alerts_by_cwd.get(s.cwd)
            if alert:
                entry["alert_type"] = alert["type"]
                entry["alert_message"] = alert["message"]
            session_list.append(entry)
        data = {"sessions": session_list}
        return 200, [("Content-Type", "application/json")], json.dumps(data).encode()

    if clean_path == "/health":
        data = {"status": "ok"}
        return 200, [("Content-Type", "application/json")], json.dumps(data).encode()

    return 404, [], b"Not found"


# ---------------------------------------------------------------------------
# WebSocket terminal handler (pty.fork — safe in asyncio, no Flask threads)
# ---------------------------------------------------------------------------

async def handle_terminal(websocket, session_name):
    """Handle a terminal WebSocket connection using pty.fork()."""

    # Validate session name format (prevent tmux target syntax injection)
    if not SESSION_NAME_RE.match(session_name):
        await websocket.send(json.dumps({"type": "error", "message": "invalid session name"}))
        return

    # Auth handshake
    try:
        raw = await asyncio.wait_for(websocket.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") != "auth" or not session_tokens.validate(msg.get("token", "")):
            await websocket.send(json.dumps({"type": "error", "message": "unauthorized"}))
            return
    except (asyncio.TimeoutError, json.JSONDecodeError, TypeError):
        return
    except Exception as e:
        print(f"[Terminal] Unexpected auth error: {e}", file=sys.stderr)
        return

    # Revoke token after successful auth (single-use)
    session_tokens.revoke(msg.get("token", ""))

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
        # Child: set UTF-8 locale for Korean input, then exec tmux attach
        os.environ["LANG"] = "en_US.UTF-8"
        os.environ["LC_ALL"] = "en_US.UTF-8"
        os.execlp("tmux", "tmux", "attach-session", "-t", session_name)
        os._exit(1)

    print(f"[Terminal] Connected to '{session_name}' (child={child_pid})", file=sys.stderr)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()

    # Read from pty master → send to WebSocket
    async def read_pty():
        try:
            while not stop.is_set():
                # Use executor for blocking select/read
                data = await loop.run_in_executor(None, _read_master, master_fd)
                if data is None:
                    break
                if data:  # skip empty timeout reads
                    await websocket.send(json.dumps({
                        "type": "output",
                        "data": data.decode("utf-8", errors="replace"),
                    }))
        except Exception as e:
            if not stop.is_set():
                print(f"[Terminal] pty reader error: {e}", file=sys.stderr)
        finally:
            stop.set()

    reader_task = asyncio.create_task(read_pty())

    # Read from WebSocket → write to pty master
    try:
        async for raw in websocket:
            if stop.is_set():
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
                if data and len(data) <= 1024:
                    os.write(master_fd, data.encode("utf-8"))

            elif msg_type == "resize":
                cols = max(1, min(500, msg.get("cols", 80)))
                rows = max(1, min(200, msg.get("rows", 24)))
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

    except Exception as e:
        print(f"[Terminal] WebSocket error: {e}", file=sys.stderr)
    finally:
        stop.set()
        reader_task.cancel()
        caffeinate.release()
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            os.kill(child_pid, signal.SIGTERM)
            await loop.run_in_executor(None, os.waitpid, child_pid, 0)
        except OSError:
            pass
        print(f"[Terminal] Disconnected from '{session_name}'", file=sys.stderr)


def _read_master(master_fd):
    """Blocking read from pty master. Returns None on EOF, b'' on timeout."""
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
    """Create SSL context with mTLS (CERT_REQUIRED when CA is available)."""
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
        ctx.verify_mode = ssl.CERT_REQUIRED
        print("[Terminal] mTLS enabled (CERT_REQUIRED)", file=sys.stderr)
    else:
        print("[Terminal] TLS only (no mTLS — CA not found)", file=sys.stderr)

    return ctx


async def handler(websocket):
    """Route incoming connections — HTTP or WebSocket."""
    path = websocket.request.path if hasattr(websocket.request, 'path') else "/"

    if path.startswith("/ws/"):
        session_name = path[4:]
        await handle_terminal(websocket, session_name)
        return


def _get_client_ip(connection):
    """Extract client IP from websockets connection."""
    try:
        return connection.remote_address[0]
    except (AttributeError, TypeError, IndexError):
        return "unknown"


def _has_client_cert(connection):
    """Check if the client presented a valid TLS certificate."""
    try:
        transport = connection.transport
        ssl_obj = transport.get_extra_info("ssl_object")
        return ssl_obj is not None and ssl_obj.getpeercert() is not None
    except (AttributeError, TypeError):
        return False


async def process_request(connection, request):
    """Handle plain HTTP requests (non-WebSocket upgrade).
    websockets v16 signature: process_request(connection, request)."""
    path = request.path
    client_ip = _get_client_ip(connection)
    print(f"[Terminal] HTTP {request.method if hasattr(request, 'method') else '?'} {path} from {client_ip}", file=sys.stderr)

    if path.startswith("/ws/"):
        if not ws_limiter.allow(client_ip):
            print(f"[Terminal] Rate limited WS: {client_ip}", file=sys.stderr)
            return Response(429, "Too Many Requests", websockets.Headers([]), b"rate limited")
        return None  # let WebSocket handler take over

    # Health endpoint is exempt from rate limiting
    if path.split("?")[0] != "/health" and not http_limiter.allow(client_ip):
        print(f"[Terminal] Rate limited HTTP: {client_ip}", file=sys.stderr)
        return Response(429, "Too Many Requests", websockets.Headers([]), b"rate limited")

    has_cert = _has_client_cert(connection)
    status, headers_list, body = await handle_http(path, request.headers, has_client_cert=has_cert)
    return Response(status, _reason(status), websockets.Headers(headers_list), body)


async def main():
    ssl_ctx = create_ssl_context()
    if ssl_ctx is None:
        print("[Terminal] Cannot start without TLS certificates", file=sys.stderr)
        sys.exit(1)

    print(f"[Terminal] Starting on https://0.0.0.0:{TERMINAL_PORT}", file=sys.stderr)

    sweep_task = None
    async with websockets.serve(
        handler,
        "0.0.0.0",
        TERMINAL_PORT,
        ssl=ssl_ctx,
        process_request=process_request,
        max_size=2**20,
        ping_interval=20,
        ping_timeout=30,
    ):
        sweep_task = asyncio.create_task(_periodic_sweep())
        try:
            await asyncio.Future()  # run forever
        finally:
            sweep_task.cancel()
            await asyncio.gather(sweep_task, return_exceptions=True)


async def _periodic_sweep():
    """Periodically clean stale entries from rate limiters to prevent memory leaks."""
    while True:
        await asyncio.sleep(120)  # every 2 minutes
        http_limiter.sweep()
        ws_limiter.sweep()


if __name__ == "__main__":
    asyncio.run(main())
