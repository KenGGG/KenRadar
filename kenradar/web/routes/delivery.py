"""Queue isolated publication and notification retries by content ID."""

from __future__ import annotations

from typing import Any

from kenradar.web.responses import error_response, json_response


def _content_id(data: Any) -> int:
    if not isinstance(data, dict):
        return 0
    try:
        return int(data.get("content_item_id") or data.get("id") or 0)
    except (TypeError, ValueError):
        return 0


def _queue_delivery(self: Any, config_path: str, data: Any, task_type: str) -> None:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    content_item_id = _content_id(data)
    if content_item_id <= 0:
        error_response(self, "需要有效的 content_item_id", status=400)
        return
    database = create_database(load_config(config_path))
    try:
        if database.get_current_bundle(content_item_id) is None:
            error_response(self, "内容不存在", status=404)
            return
        task = database.enqueue_task_run(
            task_type,
            {"content_item_id": content_item_id},
            message=f"{'发布' if task_type == 'publish_content' else '通知'}内容 #{content_item_id}",
            requested_by="web",
            priority=60,
            idempotency_key=f"{task_type}:{content_item_id}",
        )
    finally:
        database.close()
    json_response(self, {"ok": True, "task_id": int(task["id"]), "content_item_id": content_item_id}, status=202)


def _handle_publish_content(self: Any, config_path: str, data: Any) -> None:
    _queue_delivery(self, config_path, data, "publish_content")


def _handle_notify_content(self: Any, config_path: str, data: Any) -> None:
    _queue_delivery(self, config_path, data, "notify_content")


def register(handler_class: type) -> None:
    from kenradar.web.router import register_handler

    handler_class._handle_publish_content = _handle_publish_content
    handler_class._handle_notify_content = _handle_notify_content
    register_handler("/api/content/publish", _handle_publish_content, ["config_path", "data"], method="POST")
    register_handler("/api/content/notify", _handle_notify_content, ["config_path", "data"], method="POST")
