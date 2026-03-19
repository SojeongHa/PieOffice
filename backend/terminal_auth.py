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
