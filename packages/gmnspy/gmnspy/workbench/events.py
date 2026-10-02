"""Fan-out of session events to Server-Sent-Events subscribers.

``publish`` is called from whatever thread ran the action (FastAPI's threadpool,
a notebook thread); each subscriber is an ``asyncio.Queue`` owned by the event
loop serving its SSE response, so delivery hops loops via ``call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

__all__ = ["EventBus", "sse_format"]


class EventBus:
    """Thread-safe publish → per-subscriber asyncio queues."""

    def __init__(self) -> None:
        """Start with no subscribers."""
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> asyncio.Queue:
        """Return a new queue fed by :meth:`publish`. Must be called inside a running event loop."""
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Stop delivering to ``queue`` (no-op if already gone)."""
        with self._lock:
            self._subs = [(loop, q) for loop, q in self._subs if q is not queue]

    @property
    def subscriber_count(self) -> int:
        """Number of live subscribers."""
        with self._lock:
            return len(self._subs)

    def publish(self, event: dict[str, Any]) -> None:
        """Deliver ``event`` to every subscriber; subscribers whose loop has closed are dropped."""
        with self._lock:
            subs = list(self._subs)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # loop closed: the client went away without unsubscribing
                self.unsubscribe(queue)


def sse_format(event: dict[str, Any]) -> str:
    """Encode ``event`` as one SSE frame named by its ``type``."""
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
