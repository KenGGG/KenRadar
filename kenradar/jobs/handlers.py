from __future__ import annotations

from typing import Any


async def execute_task_run(
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
        return await workflow.run_once(push=bool(payload.get("push", True)))
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
    if task_type == "summarize_existing":
        return await workflow.summarize_existing(limit=int(payload.get("limit") or 0))
    if task_type == "backfill":
        return await workflow.backfill_blogger(
            target_index=int(payload.get("target_index") or 0),
            limit=int(payload.get("limit") or 0),
        )
    if task_type == "refresh_old_notes":
        return await workflow.refresh_old_notes_with_ollama(
            limit=int(payload.get("limit") or 0),
            dry_run=bool(payload.get("dry_run", False)),
        )
    raise ValueError(f"不支持的持久任务类型: {task_type}")
