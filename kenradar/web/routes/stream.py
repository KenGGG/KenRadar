"""
SSE stream route handler.

Registers GET route for:
    /api/stream?channels=research-jobs
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _handle_stream(self: Any, query_params: dict) -> None:
    """Serve an SSE stream for research-job events.

    This is a synchronous handler (BaseHTTPRequestHandler context),
    so we run the async generator in a thread to avoid blocking.
    """
    channels = query_params.get("channels", ["research-jobs"])
    if "research-jobs" not in channels:
        from kenradar.web.responses import json_response
        json_response(self, {"error": "unsupported channel"}, status=400)
        return

    # Set SSE headers
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-cache")
    self.send_header("Connection", "keep-alive")
    self.send_header("X-Accel-Buffering", "no")
    self.send_header("Access-Control-Allow-Origin", "*")
    self.end_headers()

    # Run async SSE generator in executor to avoid blocking the request thread
    loop = asyncio.new_event_loop()
    try:
        write_coro = _write_sse_stream(self, channels)
        loop.run_until_complete(write_coro)
    finally:
        loop.close()


async def _write_sse_stream(self: Any, channels: list[str]) -> None:
    """Core SSE streaming logic (async)."""
    from kenradar.web.sse import get_broadcaster, format_sse_event, heartbeat_frame

    broadcaster = get_broadcaster()
    client = await broadcaster.subscribe()

    try:
        event_id = 1
        # Send initial connection event
        self.wfile.write(
            format_sse_event(
                {"type": "connected", "clientId": client.id},
                event_id=event_id,
            ).encode("utf-8")
        )
        self.wfile.flush()
        event_id += 1

        # Drain any buffered events the client missed while connecting
        while client.queue:
            evt = client.queue.popleft()
            payload = format_sse_event(evt, event_id=event_id)
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
            event_id += 1

        # Heartbeat loop
        hb_interval = 30
        last_hb = 0
        # Listen for new events
        while True:
            if client.queue:
                evt = client.queue.popleft()
                payload = format_sse_event(evt, event_id=event_id)
                self.wfile.write(payload.encode("utf-8"))
                self.wfile.flush()
                event_id += 1
                last_hb = 0
            else:
                await asyncio.sleep(1)

            now = asyncio.get_event_loop().time()
            if now - last_hb >= hb_interval:
                self.wfile.write(heartbeat_frame().encode("utf-8"))
                self.wfile.flush()
                last_hb = now

    except (BrokenPipeError, ConnectionResetError, OSError):
        logger.info("SSE client disconnected")
    finally:
        await broadcaster.unsubscribe(client)
        logger.info("SSE cleanup complete for client %s", client.id)


def register(handler_class: type) -> None:
    """Register the SSE stream handler."""
    from kenradar.web.router import register_handler

    handler_class._handle_stream = _handle_stream
    register_handler("/api/stream", _handle_stream, ["query_params"])
