"""
Unified JSON response helpers for KenRadar web API.

All handlers should use these instead of directly calling send_response/send_header.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def json_response(handler: Any, data: Any, status: int = 200) -> None:
    """Send a JSON response with proper headers."""
    payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def error_response(handler: Any, message: str, status: int = 400) -> None:
    """Send a standardized error response."""
    json_response(handler, {"ok": False, "message": message}, status)


def not_found_response(handler: Any, message: str = "未找到请求资源") -> None:
    """Send a 404 response."""
    json_response(handler, {"ok": False, "message": message}, 404)


def server_error_response(handler: Any, message: str = "内部服务器错误") -> None:
    """Send a 500 response."""
    json_response(handler, {"ok": False, "message": message}, 500)
