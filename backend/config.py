"""Centralized configuration constants for Pie Office backend.

All tunable thresholds and limits live here so they can be found
in one place and optionally overridden via environment variables.
"""

import os

# ---------------------------------------------------------------------------
# SSE (sse.py)
# ---------------------------------------------------------------------------
# Maximum age (seconds) for an SSE connection before forced reconnect.
MAX_CONNECTION_AGE: int = int(os.environ.get("PIE_SSE_MAX_AGE", 600))

# Maximum concurrent SSE listeners allowed.
MAX_LISTENERS: int = int(os.environ.get("PIE_SSE_MAX_LISTENERS", 20))

# Socket timeout (seconds) for werkzeug to detect broken connections faster
# (e.g., zombie SSE connections after system sleep).
SOCKET_TIMEOUT: int = int(os.environ.get("PIE_SOCKET_TIMEOUT", 30))

# Time gap threshold (seconds) between sweeps to detect system sleep.
# If more than this elapses between sweep cycles (normally 5s), all SSE
# listeners are force-closed to prevent FD leaks. Clients auto-reconnect.
SLEEP_DETECTION_THRESHOLD: int = int(os.environ.get("PIE_SLEEP_DETECTION_THRESHOLD", 30))

# ---------------------------------------------------------------------------
# Agent lifecycle (state.py)
# ---------------------------------------------------------------------------
# Seconds without updates before an agent transitions to "lingering".
STALE_THRESHOLD: int = int(os.environ.get("PIE_STALE_THRESHOLD", 15))

# Seconds in "lingering" before transitioning to "idle" (back to break room).
LINGER_THRESHOLD: int = int(os.environ.get("PIE_LINGER_THRESHOLD", 30))

# Seconds idle before a non-resident agent is auto-removed.
IDLE_REMOVE_THRESHOLD: int = int(os.environ.get("PIE_IDLE_REMOVE_THRESHOLD", 60))

# States exempt from the stale sweep (already at rest).
STALE_EXEMPT_STATES: frozenset[str] = frozenset({"idle", "lingering", "reporting", "permission"})

# Maximum hook log entries kept in the ring buffer.
HOOK_LOG_MAX: int = int(os.environ.get("PIE_HOOK_LOG_MAX", 50))

# ---------------------------------------------------------------------------
# Agent leave (app.py)
# ---------------------------------------------------------------------------
# Minimum seconds an agent stays before the leave animation fires.
LEAVE_DELAY: int = int(os.environ.get("PIE_LEAVE_DELAY", 5))

# ---------------------------------------------------------------------------
# Instance slots (state.py)
# ---------------------------------------------------------------------------
# Seconds without events before an instance slot is released.
INSTANCE_SLOT_TIMEOUT: int = int(os.environ.get("PIE_INSTANCE_SLOT_TIMEOUT", 600))

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
