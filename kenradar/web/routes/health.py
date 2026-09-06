"""
Health check route handlers.

Registers GET routes for:
    /health/live, /health/ready, /health/dependencies,
"""

from __future__ import annotations

from typing import Any

from kenradar.web.router import register_handler
from kenradar.web.responses import json_response


def register(handler_class: type) -> None:
    """Bind health handlers to the request handler class and register routes."""
    handler_class._handle_health_live = _handle_health_live
    handler_class._handle_health_ready = _handle_health_ready
    handler_class._handle_health_dependencies = _handle_health_dependencies

    # Register route mappings
    register_handler("/health/live", handler_class._handle_health_live, [])
    register_handler("/health/ready", handler_class._handle_health_ready, ["config_path"])
    register_handler("/health/dependencies", handler_class._handle_health_dependencies, ["config_path"])


def _handle_health_live(self: Any) -> None:
    json_response(self, {"ok": True, "status": "live"})


def _handle_health_ready(self: Any, config_path: str) -> None:
    from kenradar.web.helpers import _readiness_status
    json_response(self, _readiness_status(config_path))


def _handle_health_dependencies(self: Any, config_path: str) -> None:
    from kenradar.core.config import load_config
    from kenradar.web.dependency_health import dependency_status
    import time

    t0 = time.time()
    result = dependency_status(load_config(config_path))
    result["elapsed_ms"] = round((time.time() - t0) * 1000, 1)
    json_response(self, result)
