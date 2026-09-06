"""Generic V2 content detail endpoint."""

from __future__ import annotations

from typing import Any

from kenradar.web.responses import error_response, json_response


def load_content_detail(config: Any, content_item_id: int) -> dict[str, Any] | None:
    from kenradar.storage import create_database

    database = create_database(config)
    bundle = database.get_current_bundle(content_item_id)
    if bundle is None:
        return None
    content = bundle.get("content") or {}
    return {
        "content": {
            "id": content.get("id"),
            "external_content_id": content.get("content_id"),
            "title": content.get("content_title"),
            "status": content.get("content_status"),
            "review_status": content.get("review_status"),
        },
        "current_result": {
            "transcript": bundle.get("transcript") or {},
            "analysis": bundle.get("analysis") or {},
            "note": bundle.get("note") or {},
        },
    }


def load_content_operations(config: Any, content_item_id: int) -> list[dict[str, Any]] | None:
    from kenradar.storage import create_database

    database = create_database(config)
    if database.get_current_bundle(content_item_id) is None:
        return None
    return database.publications.list_operations(content_item_id)


def _handle_content_detail(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config

    try:
        content_item_id = int((query_params.get("id") or ["0"])[0])
    except (TypeError, ValueError):
        content_item_id = 0
    if content_item_id <= 0:
        error_response(self, "需要有效的 content id", status=400)
        return
    payload = load_content_detail(load_config(config_path), content_item_id)
    if payload is None:
        error_response(self, "内容不存在", status=404)
        return
    json_response(self, payload)


def _handle_content_operations(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config

    try:
        content_item_id = int((query_params.get("id") or ["0"])[0])
    except (TypeError, ValueError):
        content_item_id = 0
    if content_item_id <= 0:
        error_response(self, "需要有效的 content id", status=400)
        return
    operations = load_content_operations(load_config(config_path), content_item_id)
    if operations is None:
        error_response(self, "内容不存在", status=404)
        return
    json_response(self, {"content_item_id": content_item_id, "operations": operations})


def register(handler_class: type) -> None:
    from kenradar.web.router import register_handler

    handler_class._handle_content_detail = _handle_content_detail
    handler_class._handle_content_operations = _handle_content_operations
    register_handler("/api/content", _handle_content_detail, ["config_path", "query_params"], method="GET")
    register_handler("/api/content/operations", _handle_content_operations, ["config_path", "query_params"], method="GET")
