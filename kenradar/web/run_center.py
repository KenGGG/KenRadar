"""Read-only V2 task projection. Counts and pages share one database snapshot."""
from typing import Any

from kenradar.storage import create_database
from kenradar.web.queries import _task_run_type_label


def load_run_center(config: Any, *, section: str = "active", status: str = "", limit: int = 25, offset: int = 0) -> dict:
    if section not in {"active", "attention", "history"}:
        raise ValueError("无效的任务分组")
    limit = max(1, min(100, int(limit)))
    offset = max(0, int(offset))
    database = create_database(config)
    try:
        with database.connect() as conn:
            if config.database_type == "sqlite":
                row = _sqlite_projection(database, conn, section, status, limit, offset)
            else:
                row = conn.execute(
                """
                WITH projected AS (
                    SELECT id, task_type, status, message, priority, attempt, max_attempts,
                           error_code, last_error, created_at, updated_at, started_at, finished_at,
                           available_at, heartbeat_at, lease_expires_at, progress_json,
                           pause_requested_at IS NOT NULL AS pause_requested,
                           cancel_requested_at IS NOT NULL AS cancel_requested,
                           CASE
                             WHEN status IN ('success', 'failed', 'cancelled') AND task_type IN
                               ('company_financial_analysis', 'company_research_batch',
                                'company_research_cleanup_notebooks', 'refresh_old_notes') THEN 'retired'
                             WHEN status='running' AND (lease_expires_at IS NULL OR lease_expires_at < NOW()) THEN 'interrupted'
                             WHEN status='success' AND stats_json->>'status'='cancelled' THEN 'cancelled'
                             WHEN status='success' AND stats_json->>'status' IN ('failed', 'error') THEN 'failed'
                             WHEN status='success' AND (stats_json->>'status'='partial_failed'
                               OR COALESCE(stats_json->>'failed', '0') ~ '^[1-9][0-9]*$') THEN 'partial_failed'
                             ELSE status
                           END AS display_status
                    FROM task_run
                ), classified AS (
                    SELECT *, CASE
                        WHEN status IN ('success', 'cancelled') OR display_status='retired' THEN 'history'
                        WHEN display_status IN ('running', 'queued', 'retry_wait') THEN 'active'
                        ELSE 'attention' END AS section
                    FROM projected
                ), filtered AS (
                    SELECT * FROM classified WHERE section=%s AND (%s='' OR display_status=%s)
                ), page AS (
                    SELECT * FROM filtered
                    ORDER BY CASE display_status WHEN 'running' THEN 0 WHEN 'interrupted' THEN 1 ELSE 2 END,
                             CASE WHEN section='active' THEN priority END DESC,
                             CASE WHEN section='active' THEN available_at END ASC,
                             CASE WHEN section<>'active' THEN updated_at END DESC,
                             CASE WHEN section='active' THEN id END ASC, id DESC
                    LIMIT %s OFFSET %s
                )
                SELECT (SELECT count(*) FROM classified WHERE section='active') AS active,
                       (SELECT count(*) FROM classified WHERE section='attention') AS attention,
                       (SELECT count(*) FROM classified WHERE section='history') AS history,
                       (SELECT count(*) FROM filtered) AS total,
                       COALESCE((SELECT jsonb_agg(to_jsonb(page)) FROM page), '[]'::jsonb) AS items
                """, (section, status, status, limit, offset),
            ).fetchone()
    finally:
        database.close()
    items = row["items"]
    labels = {"podcast_transcribe": "播客 GPU 转录", "podcast_codex": "播客 Terra 整理", "podcast_organize": "播客 AI 整理",
              "process_url": "链接处理", "execute_backfill_item": "历史内容处理",
              "publish_content": "发布内容", "publish_batch": "批次发布",
              "notify_content": "内容通知", "notify_batch": "批次通知",
              "monitor_xiaoyuzhou_sources": "播客订阅检测"}
    for item in items:
        item["task_label"] = labels.get(item["task_type"]) or _task_run_type_label(item["task_type"])
    return {"ok": True, "items": items, "counts": {k: int(row[k]) for k in ("active", "attention", "history")},
            "total": int(row["total"]), "limit": limit, "offset": offset}


def _sqlite_projection(db, conn, section, status, limit, offset):
    from sqlalchemy import and_, case, cast, Integer, String, func, or_, select
    from kenradar.storage.sqlite_database import utc_now
    t = db.table("task_run")
    content, platform, analysis = [db.table(name) for name in ('content_item', 'platform', 'ai_analysis')]
    note, publication = db.table('content_note'), db.table('publication_log')
    external = func.coalesce(func.json_extract(t.c.payload_json, '$.external_content_id'),
                             func.json_extract(t.c.payload_json, '$.aweme_id'),
                             func.json_extract(t.c.progress_json, '$.failed_result.external_content_id'),
                             func.json_extract(t.c.progress_json, '$.failed_result.aweme_id'))
    platform_code = func.coalesce(func.json_extract(t.c.payload_json, '$.platform'),
                                  func.json_extract(t.c.progress_json, '$.failed_result.platform'), 'douyin')
    diagnostic = (select(analysis.c.error_message).select_from(analysis.join(content, analysis.c.content_item_id == content.c.id)
                  .join(platform, content.c.platform_id == platform.c.id))
                  .where(platform.c.code == platform_code, content.c.content_id == external,
                         analysis.c.analysis_type == 'summary', analysis.c.status == 'failed')
                  .limit(1).correlate(t).scalar_subquery().label('diagnostic_error'))
    result = func.json_extract(t.c.stats_json, "$.status")
    failed = cast(func.coalesce(func.json_extract(t.c.stats_json, "$.failed"), 0), String)
    retired = ("company_financial_analysis", "company_research_batch", "company_research_cleanup_notebooks", "refresh_old_notes")
    later_content_success = (select(analysis.c.id).select_from(
        analysis.join(content, analysis.c.content_item_id == content.c.id)
        .join(platform, content.c.platform_id == platform.c.id)
        .join(note, note.c.content_item_id == content.c.id))
        .where(platform.c.code == platform_code, content.c.content_id == external,
               analysis.c.analysis_type == 'summary', analysis.c.status == 'success',
               func.coalesce(analysis.c.completed_at, analysis.c.updated_at) > func.coalesce(t.c.finished_at, t.c.updated_at),
               note.c.note_path.is_not(None), note.c.note_path != '')
        .correlate(t).exists())
    published_current_note = (select(publication.c.id).select_from(
        publication.join(note, publication.c.content_item_id == note.c.content_item_id))
        .where(publication.c.content_item_id == cast(func.json_extract(t.c.payload_json, '$.content_item_id'), Integer),
               publication.c.source_hash == note.c.content_sha256, publication.c.status == 'success')
        .correlate(t).exists())
    content_task_types = ('process_url', 'retry_summary', 'retry_transcribe', 'retry_download',
                          'podcast_codex', 'podcast_transcribe', 'podcast_organize')
    later_scan = t.alias('later_scan')
    recovered_scan = (select(later_scan.c.id).where(
        later_scan.c.task_type == 'scan_sources', later_scan.c.status == 'success',
        func.json_extract(later_scan.c.stats_json, '$.source_verified') == 1,
        func.json_extract(later_scan.c.payload_json, '$.day') == func.json_extract(t.c.payload_json, '$.day'),
        later_scan.c.finished_at > func.coalesce(t.c.finished_at, t.c.updated_at)
    ).correlate(t).exists())
    subscriptions = db.table("source_subscription")
    failed_ids = func.json_each(
        t.c.progress_json, "$.failed_result.source_coverage.failed_source_ids"
    ).table_valued("value").alias("failed_source")
    unresolved_source = (
        select(failed_ids.c.value).select_from(failed_ids.outerjoin(
            subscriptions, subscriptions.c.id == cast(failed_ids.c.value, Integer)
        )).where(or_(
            subscriptions.c.last_success_at.is_(None),
            subscriptions.c.last_success_at <= func.coalesce(t.c.finished_at, t.c.updated_at),
        )).correlate(t).exists()
    )
    recovered_sources = and_(
        func.json_array_length(t.c.progress_json, "$.failed_result.source_coverage.failed_source_ids") > 0,
        ~unresolved_source,
    )
    display = case(
        (and_(t.c.status == "failed", t.c.error_code == "RESOLVED"), "resolved"),
        (and_(t.c.status == 'failed', t.c.task_type.in_(content_task_types), later_content_success), 'resolved'),
        (and_(t.c.status == 'failed', t.c.task_type == 'scan_sources', or_(recovered_scan, recovered_sources)), 'resolved'),
        (and_(t.c.task_type == 'publish_content', t.c.status.in_(('queued', 'retry_wait', 'failed')),
              published_current_note), 'resolved'),
        (and_(t.c.status.in_(("success", "failed", "cancelled")), t.c.task_type.in_(retired)), "retired"),
        (and_(t.c.status == "running", or_(t.c.lease_expires_at.is_(None), t.c.lease_expires_at < utc_now())), "interrupted"),
        (and_(t.c.status == "success", result == "cancelled"), "cancelled"),
        (and_(t.c.status == "success", result.in_(("failed", "error"))), "failed"),
        (and_(t.c.status == "success", or_(result == "partial_failed", and_(~failed.op("GLOB")("*[^0-9]*"), cast(failed, Integer) > 0))), "partial_failed"),
        else_=t.c.status).label("display_status")
    fields = [t.c[key] for key in ("id", "task_type", "status", "message", "priority", "attempt", "max_attempts", "error_code", "last_error", "created_at", "updated_at", "started_at", "finished_at", "available_at", "heartbeat_at", "lease_expires_at", "progress_json", "config_revision")]
    projected = select(*fields, diagnostic, t.c.pause_requested_at.is_not(None).label("pause_requested"), t.c.cancel_requested_at.is_not(None).label("cancel_requested"), display).subquery()
    category = case((or_(projected.c.status.in_(("success", "cancelled")), projected.c.display_status.in_(("retired", "resolved"))), "history"),
        (projected.c.display_status.in_(("running", "queued", "retry_wait")), "active"), else_="attention")
    classified = select(projected, category.label("section")).subquery()
    counts = dict(conn.execute(select(*(func.count().filter(classified.c.section == key).label(key) for key in ("active", "attention", "history")))).fetchone())
    predicates = [classified.c.section == section]
    if status:
        predicates.append(classified.c.display_status == status)
    counts["total"] = conn.execute(select(func.count()).select_from(classified).where(*predicates)).fetchone()[0]
    rank = case((classified.c.display_status == "running", 0), (classified.c.display_status == "interrupted", 1), else_=2)
    order = [rank, classified.c.priority.desc(), classified.c.available_at, classified.c.id] if section == "active" else [rank, classified.c.updated_at.desc(), classified.c.id.desc()]
    counts["items"] = [dict(row) for row in conn.execute(select(classified).where(*predicates).order_by(*order).limit(limit).offset(offset)).fetchall()]
    return counts
