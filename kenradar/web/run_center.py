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
    labels = {"process_url": "链接处理", "execute_backfill_item": "历史内容处理",
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
    result = func.json_extract(t.c.stats_json, "$.status")
    failed = cast(func.coalesce(func.json_extract(t.c.stats_json, "$.failed"), 0), String)
    retired = ("company_financial_analysis", "company_research_batch", "company_research_cleanup_notebooks", "refresh_old_notes")
    display = case(
        (and_(t.c.status == "failed", t.c.error_code == "RESOLVED"), "resolved"),
        (and_(t.c.status.in_(("success", "failed", "cancelled")), t.c.task_type.in_(retired)), "retired"),
        (and_(t.c.status == "running", or_(t.c.lease_expires_at.is_(None), t.c.lease_expires_at < utc_now())), "interrupted"),
        (and_(t.c.status == "success", result == "cancelled"), "cancelled"),
        (and_(t.c.status == "success", result.in_(("failed", "error"))), "failed"),
        (and_(t.c.status == "success", or_(result == "partial_failed", and_(~failed.op("GLOB")("*[^0-9]*"), cast(failed, Integer) > 0))), "partial_failed"),
        else_=t.c.status).label("display_status")
    fields = [t.c[key] for key in ("id", "task_type", "status", "message", "priority", "attempt", "max_attempts", "error_code", "last_error", "created_at", "updated_at", "started_at", "finished_at", "available_at", "heartbeat_at", "lease_expires_at", "progress_json", "config_revision")]
    projected = select(*fields, t.c.pause_requested_at.is_not(None).label("pause_requested"), t.c.cancel_requested_at.is_not(None).label("cancel_requested"), display).subquery()
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
