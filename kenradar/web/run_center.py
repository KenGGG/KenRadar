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
                        WHEN display_status IN ('running', 'queued', 'retry_wait') THEN 'active'
                        WHEN display_status IN ('success', 'cancelled', 'retired') THEN 'history'
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
