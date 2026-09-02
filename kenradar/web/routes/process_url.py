"""Unified single-link processing endpoint (V2 M4)."""

from __future__ import annotations

from typing import Any

from kenradar.web.responses import error_response, json_response


def _handle_process_url_get(self: Any, config_path: str, query_params: dict) -> None:
    """Accepted redirect/GET: return 405 so callers use POST."""
    error_response(self, "请使用 POST 提交待处理链接", status=405)


def _handle_process_url_post(self: Any, config_path: str, query_params: dict, form: dict, data: bytes) -> None:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    payload = _parse_body(self, form, data)
    url = str(payload.get("url") or "").strip()
    if not url:
        error_response(self, "缺少待处理链接 (url)", status=400)
        return

    from kenradar.sources.registry import connector_for_url

    if connector_for_url(url) is None:
        error_response(self, f"不支持的链接来源: {url}", status=400)
        return

    config = load_config(config_path)
    database = create_database(config)
    try:
        task = database.enqueue_task_run(
            "process_url",
            {
                "url": url,
                "push": bool(payload.get("push", True)),
                "force": bool(payload.get("force", False)),
                "requested_by": "web",
            },
            message=f"处理链接 {url}",
            requested_by="web",
            priority=100,
            idempotency_key=f"process-url:{url}",
        )
    finally:
        database.close()

    json_response(
        self,
        {
            "ok": True,
            "task_id": int(task["id"]),
            "message": f"已加入处理队列: {url}",
            "url": url,
        },
        status=202,
    )


def _parse_body(self: Any, form: dict, data: Any) -> dict[str, Any]:
    """Read the url from a JSON body, falling back to a form-encoded body.

    The request handler parses the raw body as both form and JSON; for a JSON
    request ``parse_qs`` produces a junk single-key mapping, so the decoded
    JSON dict wins whenever it is present.
    """
    if isinstance(data, dict) and data:
        return dict(data)
    if isinstance(data, (bytes, bytearray)) and data:
        try:
            import json

            decoded = json.loads(bytes(data).decode("utf-8"))
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}
    if form:
        flattened: dict[str, Any] = {}
        for key, value in form.items():
            flattened[key] = value[0] if isinstance(value, list) and value else value
        return flattened
    return {}


def register(handler_class: type) -> None:
    """Bind the process-url handlers and register routes."""
    from kenradar.web.router import register_handler

    handler_class._handle_process_url_get = _handle_process_url_get
    handler_class._handle_process_url_post = _handle_process_url_post
    register_handler(
        "/api/content/process-url",
        _handle_process_url_get,
        ["config_path", "query_params"],
        method="GET",
    )
    register_handler(
        "/api/content/process-url",
        _handle_process_url_post,
        ["config_path", "query_params", "form", "data"],
        method="POST",
    )
