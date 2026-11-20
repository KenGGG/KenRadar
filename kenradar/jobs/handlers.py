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
    if task_type in ('process_url', 'retry_summary', 'retry_transcribe', 'retry_download', 'podcast_codex', 'podcast_organize'):
        _queue_daily_publication(workflow, payload, result)
    return normalize_task_result(result)


def _queue_daily_publication(workflow: Any, payload: dict, result: dict) -> None:
    """Make legacy successful local notes enter the existing durable delivery owner."""
    config = getattr(workflow, 'config', None)
    if config is None or config.get('schedule.mode') != 'subscription_daily' or not payload.get('subscription_id'):
        return
    from pathlib import Path
    import hashlib
    from kenradar.integrations.privacy import require_deliverable
    database = getattr(workflow, 'delivery_database', workflow.database)
    identity = str(payload.get('external_content_id') or payload.get('aweme_id') or result.get('aweme_id') or '')
    platform = str(payload.get('platform') or 'douyin')
    content = database.find_content_item(platform, identity) if identity else None
    bundle = database.get_current_bundle(content['id']) if content else None
    if not bundle or (bundle.get('analysis') or {}).get('status') != 'success':
        return
    require_deliverable(bundle)
    note = bundle.get('note') or {}
    path = Path(note.get('note_path') or '')
    if not path.is_file():
        return
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if note.get('content_sha256') != source_hash:
        note['content_sha256'] = source_hash
        database.replace_analysis_and_note(content['id'], bundle['analysis'], note)
    receipt = database.publications.find_success(content['id'], source_hash)
    if receipt and ':html:' in str(receipt.get('idempotency_key') or ''):
        return
    database.enqueue_task_run('publish_content',
        {**{key: payload[key] for key in ('subscription_id', 'day') if key in payload},
         'platform': platform, 'aweme_id': identity, 'external_content_id': identity,
         'content_item_id': content['id'], 'trigger': 'monitor_recovery', 'push': False, 'force': False},
        message=f'订阅笔记独立发布：{identity}', requested_by='monitor', priority=80,
        idempotency_key=f'monitor-recovery:{platform}:{identity}:publish_content:{source_hash}', max_attempts=3)


async def _execute_task_run_raw(
    workflow: Any,
    task_type: str,
    payload: dict[str, Any],
    *,
    progress_callback: Any = None,
) -> dict[str, Any]:
    task_type = str(task_type or "").strip()
    payload = payload if isinstance(payload, dict) else {}
    if task_type == "hermes_content_v1":
        from kenradar.integrations.hermes_v1 import execute
        return await execute(workflow, payload)
    if task_type == "system_health_check":
        return {"ok": True, "check": "task_engine"}
    if task_type == 'daily_summary':
        import asyncio
        from kenradar.notification.daily import DailySummaryService
        return await asyncio.to_thread(DailySummaryService(workflow.database, workflow.config).send,
            str(payload.get('day') or ''), task_ids=payload.get('task_ids'), acceptance=bool(payload.get('acceptance',False)),
            due_time=str(payload.get('due_time') or ''))
    if task_type == 'scan_sources':
        from kenradar.core.source_monitor import SourceMonitorService
        config = getattr(workflow, 'config', None)
        budget = int(config.get('schedule.source_radar_max_pending_tasks', 25) or 0) if config else 25
        monitor = SourceMonitorService(workflow.database, max_pending_tasks=budget)
        monitor.business_day = str(payload.get('day') or '')
        stats = await monitor.scan_due_subscriptions(scan_scope='full')
        # Respect backoff without allowing another due source to mask a
        # rejected, skipped, or not-yet-observed required subscription.
        from kenradar.notification.daily import source_day_coverage
        coverage = source_day_coverage(workflow.database, config, str(payload.get('day') or ''))
        stats['source_coverage'] = coverage
        stats['deferred_failed_sources'] = len(coverage['failed_source_ids'])
        stats['failed'] = max(stats['failed'], len(coverage['failed_source_ids']))
        if stats['failed']:
            details = stats.get('errors') or []
            stats['error'] = '; '.join(f"source #{entry['subscription_id']}: {entry['error']}" for entry in details) or (
                'SOURCE_BACKOFF: unresolved sources ' + ','.join(map(str, coverage['failed_source_ids'])))
        stats['source_verified'] = coverage['verified']
        stats['day'] = str(payload.get('day') or '')
        stats['due_time'] = str(payload.get('due_time') or '')
        stats['listing_observations'] = {platform: connector.last_listing_observation
            for platform, connector in monitor.connectors.items() if hasattr(connector, 'last_listing_observation')}
        return stats
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
        if 'content_ids' in payload:
            return await workflow.summarize_existing(limit=int(payload.get('limit') or 0), content_ids=payload['content_ids'])
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
    if task_type in {"podcast_transcribe", "podcast_codex", "podcast_organize"}:
        from kenradar.jobs.podcast_stages import execute_podcast_stage
        return await execute_podcast_stage(workflow, task_type, payload)
    if task_type == "process_url":
        if payload.get('platform') == 'xiaoyuzhou' and isinstance(payload.get('item'), dict):
            from kenradar.jobs.podcast_stages import execute_podcast_stage
            return await execute_podcast_stage(workflow, 'podcast_process', payload)
        config = getattr(workflow, 'config', None)
        delivery_options = {}
        if config is not None and config.get('schedule.mode') == 'subscription_daily' and payload.get('subscription_id'):
            delivery_options['publish'] = False
        return await workflow.process_single_url(
            url=str(payload.get("url") or ""),
            push=bool(payload.get("push", True)),
            force=bool(payload.get("force", False)),
            requested_by=str(payload.get("requested_by") or ""),
            **delivery_options,
        )
    raise ValueError(f"不支持的持久任务类型: {task_type}")
