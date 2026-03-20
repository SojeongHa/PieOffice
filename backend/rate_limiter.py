"""IP-based rate limiter using a sliding window counter.

Defense-in-depth: even behind Tailscale + mTLS, limit request rates per IP
to mitigate abuse from compromised devices or misconfigurations.
"""

import threading
import time
from collections import defaultdict


class RateLimiter:
    """Sliding window rate limiter keyed by IP address."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self._max = max_requests
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, ip: str) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.time()
        cutoff = now - self._window

        with self._lock:
            timestamps = self._hits[ip]
            # Trim old entries
            self._hits[ip] = [t for t in timestamps if t > cutoff]

            if len(self._hits[ip]) >= self._max:
                return False

            self._hits[ip].append(now)
            return True

    def sweep(self) -> None:
        """Remove stale entries for IPs with no recent activity."""
        now = time.time()
        cutoff = now - self._window

        with self._lock:
            empty_ips = [
                ip for ip, timestamps in self._hits.items()
                if not timestamps or timestamps[-1] <= cutoff
            ]
            for ip in empty_ips:
                del self._hits[ip]
