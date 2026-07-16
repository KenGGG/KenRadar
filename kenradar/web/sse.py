"""
SSE broadcaster for KenRadar real-time event streaming.

Provides a singleton SSEBroadcaster that manages client connections,
heartbeat messages, and bounded per-client event queues.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

# Event types pushed over SSE
EVENT_TYPES = ("research_job.updated", "research_job.completed", "research_job.failed")

# Heartbeat interval in seconds
HEARTBEAT_INTERVAL = 30

# Max events kept per client queue
MAX_QUEUE_SIZE = 64

# Max seconds a client can fall behind before degrading to polling
MAX_LAG_SECONDS = 120


@dataclass
class _Client:
    """Internal representation of an SSE client."""
    queue: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_QUEUE_SIZE))
    last_seen: float = field(default_factory=time.monotonic)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class SSEBroadcaster:
    """Publishes events to subscribed SSE clients.

    Thread-safe for synchronous push; async-safe for iteration.
    """

    def __init__(self) -> None:
        self._clients: dict[str, _Client] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def subscribe(self) -> _Client:
        """Register a new client and return its state object."""
        async with self._lock:
            client = _Client()
            self._clients[client.id] = client
            logger.info("SSE client subscribed (%d total)", len(self._clients))
            return client

    async def unsubscribe(self, client: _Client) -> None:
        """Remove a client and drain its queue."""
        async with self._lock:
            self._clients.pop(client.id, None)
            client.queue.clear()
            logger.info("SSE client unsubscribed (%d total)", len(self._clients))

    async def publish(self, event: dict[str, Any]) -> None:
        """Broadcast an event to all subscribed clients."""
        async with self._lock:
            if not self._clients:
                return
            # Mark lagging clients
            now_mono = time.monotonic()
            for c in self._clients.values():
                c.last_seen = now_mono
                if len(c.queue) >= c.queue.maxlen:
                    c.queue.popleft()
                c.queue.append(event)

    async def count(self) -> int:
        async with self._lock:
            return len(self._clients)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_stale(self, timeout: float = MAX_LAG_SECONDS) -> int:
        """Remove clients that haven't been seen (via heartbeat ack) within timeout.

        Returns number of clients removed.
        """
        removed = 0
        async with self._lock:
            stale = [
                cid for cid, c in self._clients.items()
                if (time.monotonic() - c.last_seen) > timeout
            ]
            for cid in stale:
                c = self._clients.pop(cid)
                c.queue.clear()
                removed += 1
        if removed:
            logger.info("Cleaned up %d stale SSE clients", removed)
        return removed


# Global singleton — initialised at app startup
_broadcaster: SSEBroadcaster | None = None


def get_broadcaster() -> SSEBroadcaster:
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = SSEBroadcaster()
    return _broadcaster


def reset_broadcaster_for_testing() -> None:
    """Reset the singleton (testing only)."""
    global _broadcaster
    _broadcaster = None


# ------------------------------------------------------------------
# Event formatting helpers
# ------------------------------------------------------------------

def format_sse_event(data: dict[str, Any], event_type: str = "message", event_id: int | None = None) -> str:
    """Format a dict into an SSE message frame."""
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event_type}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")  # trailing blank line
    return "\n".join(lines) + "\n"


def heartbeat_frame() -> str:
    """Return a minimal heartbeat SSE frame."""
    return format_sse_event({"type": "heartbeat", "ts": time.time()}, event_type="heartbeat")
