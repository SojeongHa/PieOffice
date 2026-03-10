"""SSE MessageAnnouncer — queue-per-client fan-out broadcaster."""

import json
import queue
import threading
from typing import Iterator


def _format_sse(data: str, event: str | None = None) -> str:
    """Format a payload as an SSE message string."""
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {data}")
    lines.append("")
    lines.append("")  # double newline terminates the message
    return "\n".join(lines)


class MessageAnnouncer:
    """Fan-out broadcaster: each listener gets its own bounded queue."""

    def __init__(self):
        self._listeners: list[queue.Queue] = []
        self._lock = threading.Lock()

    def listen(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=20)
        with self._lock:
            self._listeners.append(q)
        return q

    def announce(self, data: dict, event: str | None = None) -> None:
        """Serialize *data* as JSON and push to every listener.

        Listeners whose queue is full are silently dropped (client too slow).
        """
        msg = _format_sse(json.dumps(data), event=event)
        dead: list[queue.Queue] = []
        with self._lock:
            for q in self._listeners:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                try:
                    self._listeners.remove(q)
                except ValueError:
                    pass

    def stream(self, q: queue.Queue) -> Iterator[str]:
        """Yield SSE messages from *q* forever (blocking get with keepalive)."""
        try:
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield msg
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            self._remove(q)
        except Exception:
            self._remove(q)

    def _remove(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._listeners.remove(q)
            except ValueError:
                pass
