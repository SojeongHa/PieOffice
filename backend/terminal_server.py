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


@terminal_app.route("/session-token", methods=["POST"])
def terminal_session_token():
    """Issue a session token after mTLS handshake."""
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
        ctx.verify_mode = ssl.CERT_REQUIRED
        print("[Terminal] mTLS enabled — client certificate required", file=sys.stderr)
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
