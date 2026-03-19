"""Session-token authentication for the web terminal.

mTLS handles device authentication at the TLS layer. Once a client passes
mTLS, the server issues a short-lived session token that the client uses
for WebSocket authentication (since browsers don't reliably pass client
certificates on WebSocket upgrades).

Flow:
  1. Client loads /terminal (mTLS required — only registered devices pass)
  2. Page calls GET /terminal/session-token → server issues a random token
  3. Token is stored in-memory with TTL (not persisted to disk)
  4. Client sends token in WebSocket auth handshake
  5. Server validates token and attaches to tmux session
"""

import hmac
import secrets
import sys
import threading
import time


class SessionTokenStore:
    """In-memory store for short-lived session tokens with automatic expiry."""

    def __init__(self, ttl: int = 3600):
        self._tokens: dict[str, float] = {}  # token → expiry timestamp
        self._lock = threading.Lock()
        self._ttl = ttl

    def issue(self) -> str:
        """Issue a new session token."""
        token = secrets.token_hex(32)
        with self._lock:
            self._tokens[token] = time.time() + self._ttl
            self._sweep()
        return token

    def validate(self, candidate: str) -> bool:
        """Validate a session token (constant-time comparison, checks expiry)."""
        if not candidate:
            return False
        with self._lock:
            self._sweep()
            for stored_token, expiry in self._tokens.items():
                if hmac.compare_digest(candidate, stored_token):
                    return time.time() < expiry
        return False

    def revoke(self, token: str) -> None:
        """Revoke a specific token."""
        with self._lock:
            self._tokens.pop(token, None)

    def revoke_all(self) -> None:
        """Revoke all tokens (e.g., on server restart or security event)."""
        with self._lock:
            self._tokens.clear()

    def _sweep(self) -> None:
        """Remove expired tokens. Must be called with lock held."""
        now = time.time()
        expired = [t for t, exp in self._tokens.items() if now >= exp]
        for t in expired:
            del self._tokens[t]

    @property
    def active_count(self) -> int:
        with self._lock:
            self._sweep()
            return len(self._tokens)
