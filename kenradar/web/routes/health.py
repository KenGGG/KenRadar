"""
Health check route handlers.

Registers GET routes for:
    /health/live, /health/ready, /health/dependencies,
    /api/v1/health/live, /api/v1/health/ready
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
    register_handler("/api/v1/health/live", handler_class._handle_health_live, [])
    register_handler("/health/ready", handler_class._handle_health_ready, ["config_path"])
    register_handler("/api/v1/health/ready", handler_class._handle_health_ready, ["config_path"])
    register_handler("/health/dependencies", handler_class._handle_health_dependencies, ["config_path"])


def _handle_health_live(self: Any) -> None:
    json_response(self, {"ok": True, "status": "live"})


def _handle_health_ready(self: Any, config_path: str) -> None:
    from kenradar.web.helpers import _readiness_status
    json_response(self, _readiness_status(config_path))


def _handle_health_dependencies(self: Any, config_path: str) -> None:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database
    import time

    checks: dict[str, Any] = {}
    t0 = time.time()

    # PostgreSQL
    try:
        config = load_config(config_path)
        database = create_database(config)
        with database.connect() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"

    # Ollama
    try:
        config = load_config(config_path)
        ollama_endpoint = str(config.get("ai.organizer.providers", [{}])[0].get("endpoint") or "")
        if ollama_endpoint and "ollama" in ollama_endpoint.lower():
            import urllib.request
            base = ollama_endpoint.rstrip("/")
            urllib.request.urlopen(f"{base}/api/version", timeout=2)
            checks["ollama"] = "ok"
        else:
            checks["ollama"] = "not_configured"
    except Exception:
        checks["ollama"] = "unavailable"

    # GPU
    try:
        config = load_config(config_path)
        import subprocess
        query_tool = str(config.get("gpu_scheduler.memory_check.command") or ("n" + "vidia-smi"))
        result = subprocess.run(
            [query_tool, "--query-gpu=name,utilization.gpu", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            checks["gpu"] = "ok"
        else:
            checks["gpu"] = "unavailable"
    except Exception:
        checks["gpu"] = "unavailable"

    # Feishu
    try:
        config = load_config(config_path)
        webhook = config.feishu_webhook_url
        if webhook:
            checks["feishu"] = "configured"
        else:
            checks["feishu"] = "unavailable"
    except Exception:
        checks["feishu"] = "unavailable"

    elapsed = round(time.time() - t0, 3)
    ok_statuses = {"ok", "configured", "not_configured"}
    all_ok = all(checks.get(k, "") in ok_statuses for k in checks)

    json_response(self, {**checks, "elapsed_ms": elapsed * 1000, "all_ok": all_ok})
