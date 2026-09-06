from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _integer_count(stats: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = stats.get(key)
        if isinstance(value, bool) or value in (None, ""):
            continue
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            continue
    return 0


def normalize_task_result(stats: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize heterogeneous workflow counters without losing legacy fields."""
    result = dict(stats)
    explicit_status = str(result.get("status") or "").strip().lower()
    failed = _integer_count(result, "failed", "failed_items", "failure_count")
    skipped = _integer_count(result, "skipped", "skipped_items", "skip_count")
    success = _integer_count(
        result,
        "success",
        "processed",
        "completed",
        "summarized",
        "transcribed",
        "downloaded",
    )
    total = _integer_count(result, "total", "found", "fetched", "queued")
    total = max(total, success + failed + skipped)

    if bool(result.get("cancelled")) or explicit_status == "cancelled":
        status = "cancelled"
    elif explicit_status == "paused":
        # A cooperative stop keeps its checkpoint and waits for the operator.
        status = "paused"
    elif explicit_status in {"failed", "error"}:
        status = "failed"
    elif explicit_status == "partial_failed" or (failed > 0 and success + skipped > 0):
        status = "partial_failed"
    elif failed > 0:
        status = "failed"
    else:
        status = "success"

    result.update(
        {
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "status": status,
        }
    )
    return result


async def execute_task_run(
    workflow: Any,
    task_type: str,
    payload: dict[str, Any],
    *,
    progress_callback: Any = None,
) -> dict[str, Any]:
    result = await _execute_task_run_raw(
        workflow,
        task_type,
        payload,
        progress_callback=progress_callback,
    )
    return normalize_task_result(result)


async def _execute_task_run_raw(
    workflow: Any,
    task_type: str,
    payload: dict[str, Any],
    *,
    progress_callback: Any = None,
) -> dict[str, Any]:
    task_type = str(task_type or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    if task_type == "system_health_check":
        return {"ok": True, "check": "task_engine"}
    if task_type == "run_once":
        return await workflow.run_once(push=bool(payload.get("push", True)), on_progress=progress_callback)
    if task_type == "test_latest":
        return await workflow.test_latest(
            limit_per_target=int(payload.get("limit_per_target", 1) or 1),
            push=bool(payload.get("push", True)),
        )
    if task_type == "retry_summary":
        return await workflow.retry_summary(str(payload.get("aweme_id") or ""))
    if task_type == "retry_download":
        return await workflow.retry_download(str(payload.get("aweme_id") or ""))
    if task_type == "retry_transcribe":
        return await workflow.retry_transcribe(str(payload.get("aweme_id") or ""))
    if task_type == "retry_full":
        return await workflow.retry_full_pipeline(str(payload.get("aweme_id") or ""))
    if task_type == "retry_batch":
        aweme_ids = [str(item).strip() for item in (payload.get("aweme_ids") or []) if str(item).strip()]
        return await workflow.retry_batch(
            aweme_ids,
            retry_from=str(payload.get("retry_from") or "auto"),
            on_progress=progress_callback,
        )
    if task_type == "retry_research_failed":
        return await workflow.retry_research_failed(int(payload.get("job_id") or 0))
    if task_type == "restart_research_job":
        return await workflow.restart_research_job(int(payload.get("job_id") or 0))
    if task_type == "research_blogger":
        return await workflow.research_blogger(
            blogger=str(payload.get("blogger") or ""),
            limit=int(payload.get("limit") or 0),
            push=bool(payload.get("push", False)),
            force=bool(payload.get("force", False)),
            since=str(payload.get("since") or ""),
            until=str(payload.get("until") or ""),
        )
    if task_type == "research_video":
        return await workflow.research_video(
            video=str(payload.get("video") or ""),
            aweme_id=str(payload.get("aweme_id") or ""),
            push=bool(payload.get("push", False)),
            force=bool(payload.get("force", False)),
        )
    if task_type == "monitor_xiaoyuzhou_sources":
        return await workflow.monitor_xiaoyuzhou_sources(
            subscription_id=int(payload.get("subscription_id") or 0),
            limit=int(payload.get("limit") or 0),
            publish=bool(payload.get("publish", False)),
            push=bool(payload.get("push", False)),
        )
    if task_type == "summarize_existing":
        return await workflow.summarize_existing(limit=int(payload.get("limit") or 0))
    if task_type == "backfill":
        return await workflow.backfill_blogger(
            target_index=int(payload.get("target_index") or 0),
            limit=int(payload.get("limit") or 0),
        )
    if task_type == "execute_backfill_item":
        return await workflow.execute_backfill_item(int(payload.get("job_id") or 0))
    if task_type == "publish_content":
        return workflow.publication_service.publish_content(int(payload.get("content_item_id") or 0))
    if task_type == "publish_batch":
        return workflow.publication_service.publish_batch(int(payload.get("research_job_id") or 0))
    if task_type == "notify_content":
        return workflow.notification_service.notify_content(int(payload.get("content_item_id") or 0))
    if task_type == "notify_batch":
        return workflow.notification_service.notify_batch(int(payload.get("research_job_id") or 0))
    if task_type == "process_url":
        return await workflow.process_single_url(
            url=str(payload.get("url") or ""),
            push=bool(payload.get("push", True)),
            force=bool(payload.get("force", False)),
            requested_by=str(payload.get("requested_by") or ""),
        )
    raise ValueError(f"不支持的持久任务类型: {task_type}")
