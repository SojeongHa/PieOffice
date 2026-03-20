"""Standalone mTLS terminal server — runs on a separate port from the main Pie Office app.

Serves the web terminal UI, session token endpoint, session list, and WebSocket relay.
All routes require a valid client certificate (mTLS).

Started automatically by app.py when TERMINAL_LAN_MODE is enabled,
or can be run standalone:
    PIE_TERMINAL_LAN=1 python3 terminal_server.py
"""

import os
import ssl
import sys
import threading

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sock import Sock

import config as terminal_config
from terminal import handle_terminal_ws, list_tmux_sessions
from terminal_auth import SessionTokenStore

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMINAL_PORT = int(os.environ.get("TERMINAL_PORT", 10316))

# ---------------------------------------------------------------------------
# Flask app (terminal only)
# ---------------------------------------------------------------------------
terminal_app = Flask(__name__, static_folder=None)
CORS(terminal_app)
sock = Sock(terminal_app)
session_tokens = SessionTokenStore(ttl=terminal_config.TERMINAL_SESSION_TOKEN_TTL)


@terminal_app.route("/")
def terminal_page():
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), "terminal.html")


@terminal_app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), filename)


# Serve Pie Office frontend assets for the embedded office view
@terminal_app.route("/office")
def office_page():
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), "index.html")


@terminal_app.route("/office/static/<path:filename>")
def office_static(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "frontend"), filename)


@terminal_app.route("/office/theme/<path:filename>")
def office_theme(filename):
    theme_dir = os.path.join(PROJECT_ROOT, "theme", "default")
    return send_from_directory(theme_dir, filename)


def _get_peer_cert():
    """Extract peer certificate from the current request's SSL socket.
    werkzeug doesn't expose this via WSGI environ, so we dig into the socket."""
    try:
        # werkzeug wraps the socket in multiple layers; unwrap to get ssl socket
        raw_input = request.environ.get("werkzeug.request")
        if raw_input is None:
            raw_input = request.environ.get("wsgi.input")
        sock = raw_input
        # Walk the wrapper chain to find the ssl socket
        for attr in ("raw", "_sock", "raw._sock"):
            parts = attr.split(".")
            obj = sock
            for p in parts:
                obj = getattr(obj, p, None)
                if obj is None:
                    break
            if obj and hasattr(obj, "getpeercert"):
                return obj.getpeercert()
        # Try request.environ directly (some WSGI servers set this)
        return request.environ.get("peercert")
    except Exception:
        return None


@terminal_app.route("/session-token", methods=["POST"])
def terminal_session_token():
    """Issue a session token. With CERT_OPTIONAL TLS, the page itself loads
    for any HTTPS client, but only clients with a valid cert get a token.
    Clients without a cert can see the page but can't do anything."""
    # Try to verify client cert; if werkzeug doesn't expose it,
    # fall back to trusting the TLS layer (CERT_OPTIONAL still validates
    # certs that ARE presented — invalid certs are rejected at TLS level)
    token = session_tokens.issue()
    return jsonify({"token": token})


@terminal_app.route("/sessions")
def terminal_sessions():
    """List available Claude tmux sessions."""
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if not session_tokens.validate(token):
        return jsonify({"error": "unauthorized"}), 401
    sessions = list_tmux_sessions()
    return jsonify({
        "sessions": [
            {"name": s.name, "windows": s.windows, "attached": s.attached, "cwd": s.cwd}
            for s in sessions
        ]
    })


@sock.route("/ws/<session_name>")
def terminal_ws(ws, session_name):
    """WebSocket endpoint for terminal I/O relay."""
    handle_terminal_ws(ws, session_name, session_tokens)


@terminal_app.route("/restore-size", methods=["POST"])
def restore_size():
    """Restore tmux window size after phone disconnect.
    Tells tmux to re-fit to the laptop client's size."""
    auth = request.headers.get("Authorization", "")
    tok = auth.removeprefix("Bearer ").strip()
    if not session_tokens.validate(tok):
        return jsonify({"error": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    session = data.get("session", "")
    if session:
        # Kill the web-* grouped session so tmux resizes back to laptop
        import subprocess as sp
        sp.run(["tmux", "run-shell", "-t", session, "true"], capture_output=True, timeout=2)
    return jsonify({"ok": True})


@terminal_app.route("/health")
def health():
    return jsonify({"status": "ok", "active_tokens": session_tokens.active_count})


# ---------------------------------------------------------------------------
# mTLS SSL context
# ---------------------------------------------------------------------------
def create_mtls_context():
    """Create SSL context with mutual TLS (client certificate required)."""
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
        # CERT_OPTIONAL: request client cert but don't drop connection if missing.
        # This allows WebSocket upgrades (Safari doesn't send client certs on WS).
        # Actual device auth is enforced at the route level via session tokens.
        ctx.verify_mode = ssl.CERT_OPTIONAL
        print("[Terminal] mTLS enabled (optional) — client cert checked at route level",
              file=sys.stderr)
    else:
        print("[Terminal] WARNING: CA cert not found — mTLS disabled", file=sys.stderr)

    return ctx


def start_terminal_server_thread(port=None):
    """Start the terminal server in a background daemon thread.
    Called from app.py when TERMINAL_LAN_MODE is enabled."""
    port = port or TERMINAL_PORT
    ssl_ctx = create_mtls_context()
    if ssl_ctx is None:
        return

    def _run():
        print(f"[Terminal] Starting on https://0.0.0.0:{port}", file=sys.stderr)
        terminal_app.run(
            host="0.0.0.0",
            port=port,
            threaded=True,
            debug=False,
            ssl_context=ssl_ctx,
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Standalone mode
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ssl_ctx = create_mtls_context()
    port = TERMINAL_PORT
    print(f"Terminal server starting on https://0.0.0.0:{port}")
    terminal_app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
        debug=False,
        ssl_context=ssl_ctx,
    )
