"""Source subscription route handlers (V2 M6): history scan trigger + review."""
from __future__ import annotations

import json
from typing import Any

from kenradar.web.responses import json_response, error_response


def _parse_body(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if not isinstance(data, (bytes, bytearray)):
        return {}
    try:
        decoded = json.loads(bytes(data).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _handle_scan_history_post(self: Any, config_path: str, data: Any) -> None:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database
    from kenradar.core.source_monitor import SourceMonitorService

    body = _parse_body(data)
    subscription_id = int(body.get("subscription_id") or 0)
    scope = str(body.get("scope") or "full")
    if scope not in ("recent", "full"):
        error_response(self, "scope 必须为 recent 或 full")
        return
    config = load_config(config_path)
    database = create_database(config)
    try:
        if subscription_id <= 0:
            platform = str(body.get("platform") or "")
            source_key = str(body.get("source_key") or body.get("name") or "")
            if not platform or not source_key:
                error_response(self, "需要 subscription_id 或 platform+source_key")
                return
            sub = database.find_subscription(platform, source_key)
            if sub is None:
                error_response(self, "未找到订阅记录", status=404)
                return
            subscription_id = int(sub["id"])
        import asyncio

        stats = asyncio.run(SourceMonitorService(database).scan_subscription_history(
            subscription_id=subscription_id, scan_scope=scope
        ))
    finally:
        database.close()
    json_response(self, {"ok": True, "stats": stats}, status=200)


def _handle_research_job_confirm_post(self: Any, config_path: str, data: Any) -> None:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    body = _parse_body(data)
    job_id = int(body.get("job_id") or 0)
    approved = bool(body.get("approve", False))
    confirmed_by = str(body.get("confirmed_by") or "web")
    if job_id <= 0:
        error_response(self, "job_id 必填")
        return
    config = load_config(config_path)
    database = create_database(config)
    try:
        if approved:
            database.research_jobs.set_item_review(
                job_id, str(body.get("external_content_id") or ""), "approved"
            )
        else:
            database.research_jobs.set_item_review(
                job_id, str(body.get("external_content_id") or ""), "rejected"
            )
    finally:
        database.close()
    json_response(self, {"ok": True}, status=200)


def _handle_research_job_execute_post(self: Any, config_path: str, data: Any) -> None:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    body = _parse_body(data)
    job_id = int(body.get("job_id") or 0)
    if job_id <= 0:
        error_response(self, "job_id 必填")
        return
    database = create_database(load_config(config_path))
    try:
        job = database.research_jobs.get_job(job_id)
        if job is None:
            error_response(self, "未找到历史批次", status=404)
            return
        database.research_jobs.confirm_job(job_id, confirmed_by=str(body.get("confirmed_by") or "web"), approve=True)
        database.research_jobs.mark_executed(job_id)
        task = database.enqueue_task_run(
            "execute_backfill_item",
            {"job_id": job_id},
            message=f"处理历史批次 #{job_id}",
            requested_by="web",
            priority=20,
            idempotency_key=f"backfill:{job_id}:start",
        )
    finally:
        database.close()
    json_response(self, {"ok": True, "job_id": job_id, "task_id": int(task["id"])}, status=202)


def register(handler_class: type) -> None:
    from kenradar.web.router import register_handler

    handler_class._handle_scan_history_post = _handle_scan_history_post
    handler_class._handle_research_job_confirm_post = _handle_research_job_confirm_post
    handler_class._handle_research_job_execute_post = _handle_research_job_execute_post
    register_handler(
        "/api/source-subscriptions/scan-history", _handle_scan_history_post, ["config_path", "data"], method="POST"
    )
    register_handler(
        "/api/research/job/item-review", _handle_research_job_confirm_post, ["config_path", "data"], method="POST"
    )
    register_handler(
        "/api/research/job/confirm", _handle_research_job_execute_post, ["config_path", "data"], method="POST"
    )
