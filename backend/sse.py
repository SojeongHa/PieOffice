"""SSE MessageAnnouncer — queue-per-client fan-out broadcaster."""

import json
import queue
import sys
import threading
import time
from typing import Iterator

from config import MAX_CONNECTION_AGE, MAX_LISTENERS, SLEEP_DETECTION_THRESHOLD


def _format_sse(data: str, event: str | None = None) -> str:
    """Format a payload as an SSE message string."""
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {data}")
    lines.append("")
    lines.append("")  # double newline terminates the message
    return "\n".join(lines)


class _Listener:
    """A single SSE listener with its queue and metadata."""

    __slots__ = ("queue", "created_at")

    def __init__(self):
        self.queue: queue.Queue = queue.Queue(maxsize=20)
        self.created_at: float = time.time()


class MessageAnnouncer:
    """Fan-out broadcaster: each listener gets its own bounded queue."""

    def __init__(self):
        self._listeners: list[_Listener] = []
        self._lock = threading.Lock()
        self._last_sweep_time: float = time.time()

    @property
    def listener_count(self) -> int:
        with self._lock:
            return len(self._listeners)

    def listen(self) -> _Listener:
        listener = _Listener()
        with self._lock:
            # Evict oldest listeners if at capacity
            while len(self._listeners) >= MAX_LISTENERS:
                evicted = self._listeners.pop(0)
                # Signal the evicted listener to stop
                try:
                    evicted.queue.put_nowait(None)
                except queue.Full:
                    pass
                print(
                    f"[SSE] Evicted oldest listener (created {time.time() - evicted.created_at:.0f}s ago), "
                    f"now {len(self._listeners)} listeners",
                    file=sys.stderr,
                )
            self._listeners.append(listener)
        return listener

    def announce(self, data: dict, event: str | None = None) -> None:
        """Serialize *data* as JSON and push to every listener.

        Listeners whose queue is full are silently dropped (client too slow).
        """
        msg = _format_sse(json.dumps(data), event=event)
        dead: list[_Listener] = []
        with self._lock:
            for listener in self._listeners:
                try:
                    listener.queue.put_nowait(msg)
                except queue.Full:
                    dead.append(listener)
            for listener in dead:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass

    def sweep_stale_listeners(self) -> int:
        """Remove listeners older than MAX_CONNECTION_AGE. Returns count removed.

        Also detects system sleep (time gap > 30s between sweeps) and
        force-closes ALL listeners to prevent FD leaks from zombie connections.
        """
        now = time.time()
        elapsed_since_last = now - self._last_sweep_time
        self._last_sweep_time = now

        # Detect sleep: if time gap exceeds threshold (normally sweeps every 5s),
        # the system likely slept — kill all connections, clients will auto-reconnect
        force_all = elapsed_since_last > SLEEP_DETECTION_THRESHOLD

        stale: list[_Listener] = []
        with self._lock:
            if force_all:
                stale = list(self._listeners)
                self._listeners.clear()
            else:
                for listener in self._listeners:
                    if now - listener.created_at > MAX_CONNECTION_AGE:
                        stale.append(listener)
                for listener in stale:
                    try:
                        self._listeners.remove(listener)
                    except ValueError:
                        pass
        # Signal stale listeners to stop their generators
        for listener in stale:
            try:
                listener.queue.put_nowait(None)
            except queue.Full:
                pass
        if stale:
            reason = "sleep detected" if force_all else "age limit"
            print(f"[SSE] Swept {len(stale)} listener(s) ({reason})", file=sys.stderr)
        return len(stale)

    def stream(self, listener: _Listener) -> Iterator[str]:
        """Yield SSE messages from listener forever (blocking get with keepalive)."""
        try:
            while True:
                try:
                    msg = listener.queue.get(timeout=15)
                    # None is a poison pill — stop this stream
                    if msg is None:
                        return
                    yield msg
                except queue.Empty:
                    # Check if this connection is too old
                    if time.time() - listener.created_at > MAX_CONNECTION_AGE:
                        return
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        except Exception:
            pass
        finally:
            # Always remove listener to prevent FD leaks on broken connections
            self._remove(listener)

    def _remove(self, listener: _Listener) -> None:
        with self._lock:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass
