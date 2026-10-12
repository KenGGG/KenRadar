"""
Shared frontend helper functions extracted from app.py.

These utilities are used by multiple route files (dashboard, research, health)
and the bootstrap/status endpoints. Keeping them here eliminates circular
imports and the reverse-dependency pattern where route files imported
directly from kenradar.web.app.

Functions in this module are pure presentation/formatting helpers — they
do NOT contain route dispatch logic or HTTP handling.
"""

from __future__ import annotations

import logging
import subprocess
import re
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.config import AppConfig, load_config
from kenradar.storage import create_database
from kenradar.web import task_state
from kenradar.web.queries import (
    load_content_rows,
    load_bloggers,
    load_failures,
    load_health,
    load_library_counts,
    load_log_lines,
    load_brief_files,
    load_note_files,
    load_push_logs,
    load_recent_alerts,
    load_research_jobs,
    load_source_quality,
    load_task_runs,
    read_text,
)

logger = logging.getLogger(__name__)

FRONTEND_LIBRARY_LIMIT = 5000
FRONTEND_BOOTSTRAP_LIMIT = 30

_TASK_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_TASK_DISPATCHER_STARTED = False
_WEB_CONFIG_PATH = ""


# ---------------------------------------------------------------------------
# Query safety
# ---------------------------------------------------------------------------

def _safe_query(factory: Any, default: Any) -> Any:
    try:
        return factory()
    except Exception:
        logger.exception("Frontend bootstrap query failed")
        return default


# ---------------------------------------------------------------------------
# Runtime timeline
# ---------------------------------------------------------------------------

def _runtime_stage_label(status: str) -> str:
    status = str(status or "").lower()
    labels = {
        "checking": "检测来源",
        "pending": "等待下载",
        "running": "准备处理",
        "downloading": "下载视频",
        "downloaded": "等待转录",
        "transcribing": "转录中",
        "transcribed_waiting_summary": "等待 AI 整理",
        "summarizing": "AI 整理中",
        "noting": "生成笔记",
        "publishing": "发布 HTML",
        "pushing": "推送简报",
        "success": "已完成",
        "skipped": "已跳过",
        "failed": "失败",
        "cancelled": "已取消",
    }
    return labels.get(status, status or "运行中")


def _runtime_resource_for_stage(status: str) -> str:
    status = str(status or "").lower()
    if status in {"transcribing"}:
        return "transcribe"
    if status in {"summarizing"}:
        return "ai"
    return ""


def _frontend_runtime_timeline(config: AppConfig) -> dict[str, Any]:
    queue = task_state.public_queue()
    active_task = task_state.current()
    active_job: dict[str, Any] | None = None
    lane_counts: dict[str, int] = {}
    try:
        database = create_database(config)
        if config.database_type == "sqlite":
            from kenradar.web.sqlite_queries import runtime_timeline
            active_job, lane_counts = runtime_timeline(database)
        else:
            with database.connect() as conn:
                row = conn.execute(
                    """
                    SELECT j.id, j.blogger_name, j.status, j.total_count, j.pending_count,
                           j.success_count, j.failed_count, j.skipped_count, j.updated_at,
                           i.aweme_id, i.status AS item_status, i.error_message AS item_error,
                           i.updated_at AS item_updated_at,
                           COALESCE(ci.title, i.aweme_id, '') AS item_title,
                           COALESCE(c.nickname, j.blogger_name, '') AS creator_name
                    FROM research_job j
                    LEFT JOIN LATERAL (
                        SELECT id, content_item_id, aweme_id, status, error_message, updated_at
                        FROM research_job_item
                        WHERE job_id = j.id
                          AND status IN (
                            'pending', 'running', 'downloading', 'downloaded', 'transcribing',
                            'transcribed_waiting_summary', 'summarizing', 'noting'
                          )
                        ORDER BY CASE status
                            WHEN 'transcribing' THEN 0
                            WHEN 'summarizing' THEN 0
                            WHEN 'noting' THEN 1
                            WHEN 'downloading' THEN 2
                            WHEN 'downloaded' THEN 3
                            ELSE 4
                        END, updated_at DESC NULLS LAST, id DESC
                        LIMIT 1
                    ) i ON TRUE
                    LEFT JOIN content_item ci ON ci.id=i.content_item_id
                    LEFT JOIN creator c ON c.id=ci.creator_id
                    WHERE j.status IN ('running', 'paused')
                    ORDER BY CASE j.status WHEN 'running' THEN 0 ELSE 1 END,
                             j.updated_at DESC NULLS LAST, j.id DESC
                    LIMIT 1
                    """
                ).fetchone()
                active_job = dict(row) if row else None
                if active_job:
                    counts = conn.execute(
                        """
                        SELECT
                          COUNT(*) FILTER (
                            WHERE i.status IN ('pending', 'running', 'downloading')
                              AND NOT COALESCE(t.status = 'success', FALSE)
                          ) AS download_waiting,
                          COUNT(*) FILTER (WHERE i.status = 'downloading') AS download_active,
                          COUNT(*) FILTER (
                            WHERE i.status = 'downloaded'
                              AND NOT COALESCE(t.status = 'success', FALSE)
                          ) AS transcribe_waiting,
                          COUNT(*) FILTER (
                            WHERE i.status = 'transcribing'
                              AND NOT COALESCE(t.status = 'success', FALSE)
                          ) AS transcribe_active,
                          COUNT(*) FILTER (
                            WHERE COALESCE(t.status = 'success', FALSE)
                              AND NOT COALESCE(s.status = 'success', FALSE)
                              AND i.status NOT IN ('summarizing', 'noting', 'success', 'skipped', 'failed', 'cancelled')
                          ) AS ai_waiting,
                          COUNT(*) FILTER (WHERE i.status IN ('summarizing', 'noting')) AS ai_active,
                          COUNT(*) FILTER (
                            WHERE i.status IN ('success', 'skipped')
                              OR COALESCE(s.status = 'success', FALSE)
                          ) AS done,
                          COUNT(*) FILTER (WHERE i.status IN ('failed', 'cancelled')) AS failed
                        FROM research_job_item i
                        LEFT JOIN transcript t ON t.content_item_id=i.content_item_id
                        LEFT JOIN ai_analysis s ON s.content_item_id=i.content_item_id AND s.analysis_type='summary'
                        WHERE i.job_id = %s
                        """,
                        (int(active_job.get("id") or 0),),
                    ).fetchone()
                    lane_counts = {key: int(counts[key] or 0) for key in counts.keys()} if counts else {}
    except Exception:
        logger.exception("读取运行时间线失败")

    item_status = str((active_job or {}).get("item_status") or "")
    progress = active_task.get("progress") if isinstance(active_task.get("progress"), dict) else {}
    progress_stage = str(progress.get("stage") or "")
    resource = _runtime_resource_for_stage(item_status) or _runtime_resource_for_stage(progress_stage)

    total = int((active_job or {}).get("total_count") or progress.get("total") or 0)
    done = int((active_job or {}).get("success_count") or 0) + int((active_job or {}).get("failed_count") or 0) + int((active_job or {}).get("skipped_count") or 0)
    current = int(progress.get("current") or done or 0)
    progress_percent = round(done / total * 100) if total else 0
    if progress.get("total") and not progress_percent:
        progress_percent = round(current / max(1, int(progress.get("total") or 1)) * 100)

    entries: list[dict[str, Any]] = []
    if active_task.get("running") or active_job:
        item_title = str((active_job or {}).get("item_title") or progress.get("message") or "")
        creator_name = str((active_job or {}).get("creator_name") or (active_job or {}).get("blogger_name") or "")
        stage_label = _runtime_stage_label(item_status or progress_stage or str(active_task.get("status") or ""))
        entries.append(
            {
                "id": f"active-{active_task.get('run_id') or (active_job or {}).get('id') or 'task'}",
                "time": str((active_job or {}).get("item_updated_at") or active_task.get("started_at") or ""),
                "type": "active",
                "status": "running",
                "title": f"正在处理：{creator_name or item_title or active_task.get('message') or '后台任务'}",
                "subtitle": item_title or str(active_task.get("message") or ""),
                "detail": str((active_job or {}).get("aweme_id") or progress.get("aweme_id") or ""),
                "stage": stage_label,
                "progress": progress_percent,
                "resource": resource,
                "run_id": active_task.get("run_id"),
                "job_id": (active_job or {}).get("id"),
                "aweme_id": str((active_job or {}).get("aweme_id") or progress.get("aweme_id") or ""),
            }
        )

    for item in queue[:8]:
        message = str(item.get("message") or item.get("task_id") or "等待任务")
        is_resume = str(item.get("task_id") or "") == "restart_research_job" or "接续研究" in message or "暂缓" in message
        entries.append(
            {
                "id": f"queue-{item.get('run_id') or item.get('position')}",
                "time": str(item.get("queued_at") or ""),
                "type": "queued",
                "status": "paused" if is_resume else "waiting",
                "title": "研究任务暂缓" if is_resume else message,
                "subtitle": message,
                "detail": "插队任务完成后自动接续" if is_resume else f"队列位置 {item.get('position')}",
                "stage": "暂缓" if is_resume else "排队中",
                "progress": None,
                "resource": "",
                "run_id": item.get("run_id"),
            }
        )

    transcribe_workers = max(1, int(config.get("transcribe.workers", config.get("gpu_scheduler.batch.transcription_workers", 1)) or 1))
    ai_rpm_limit = int(config.get("ai.organizer.rpm_limit", 0) or 0)
    try:
        providers = config.get("ai.organizer.providers", []) or []
        if providers:
            ai_rpm_limit = int((providers[0] or {}).get("rpm_limit", ai_rpm_limit) or ai_rpm_limit)
    except Exception:
        pass
    lanes = [
        {
            "key": "download",
            "label": "下载",
            "active": lane_counts.get("download_active", 0),
            "waiting": lane_counts.get("download_waiting", 0),
            "done": lane_counts.get("transcribe_waiting", 0) + lane_counts.get("transcribe_active", 0) + lane_counts.get("ai_waiting", 0) + lane_counts.get("ai_active", 0) + lane_counts.get("done", 0),
            "capacity": max(1, int(config.get("download.max_workers", 1) or 1)),
            "status": "busy" if lane_counts.get("download_active", 0) else ("waiting" if lane_counts.get("download_waiting", 0) else "idle"),
            "detail": "并发下载，不受 AI 限速影响",
        },
        {
            "key": "transcribe",
            "label": "转录",
            "active": lane_counts.get("transcribe_active", 0),
            "waiting": lane_counts.get("transcribe_waiting", 0),
            "done": lane_counts.get("ai_waiting", 0) + lane_counts.get("ai_active", 0) + lane_counts.get("done", 0),
            "capacity": transcribe_workers,
            "status": "busy" if lane_counts.get("transcribe_active", 0) else ("waiting" if lane_counts.get("transcribe_waiting", 0) else "idle"),
            "detail": f"{transcribe_workers} 个转录 worker，下载完成后进入本队列",
        },
        {
            "key": "ai",
            "label": "AI 整理",
            "active": lane_counts.get("ai_active", 0),
            "waiting": lane_counts.get("ai_waiting", 0),
            "done": lane_counts.get("done", 0),
            "capacity": 1,
            "status": "busy" if lane_counts.get("ai_active", 0) else ("waiting" if lane_counts.get("ai_waiting", 0) else "idle"),
            "detail": f"单 worker 串行处理" + (f"，{ai_rpm_limit} RPM 限速" if ai_rpm_limit > 0 else ""),
        },
    ]
    if active_task.get("running") and resource:
        for lane in lanes:
            if lane.get("key") == resource and int(lane.get("active") or 0) <= 0:
                lane["active"] = 1
                lane["status"] = "busy"
                if resource == "ai":
                    lane["detail"] = f"Agnes 主引擎整理中" + (f"，{ai_rpm_limit} RPM 限速" if ai_rpm_limit > 0 else "")
                elif resource == "transcribe":
                    lane["detail"] = f"{transcribe_workers} 个转录 worker，当前正在转录"
                break

    locks = []
    for key, label in (("transcribe", "转录"), ("ai", "AI 整理")):
        lane = next((item for item in lanes if item["key"] == key), {})
        if lane.get("active", 0):
            status = "busy"
            detail = str(lane.get("detail") or "运行中")
        elif lane.get("waiting", 0):
            status = "blocked"
            detail = f"{lane.get('waiting')} 条等待进入本阶段"
        else:
            status = "available"
            detail = "空闲"
        locks.append(
            {
                "key": key,
                "label": label,
                "status": status,
                "holder": entries[0]["title"] if entries and status == "busy" else "",
                "detail": detail,
            }
        )

    return {
        "entries": entries,
        "locks": locks,
        "lanes": lanes,
        "progress_percent": progress_percent,
        "stage_label": entries[0]["stage"] if entries else "空闲",
        "active_resource": resource,
    }


# ---------------------------------------------------------------------------
# Readiness / health
# ---------------------------------------------------------------------------

def _readiness_status(config_path: str) -> dict[str, Any]:
    from kenradar.storage.migrate import schema_status

    checks: dict[str, Any] = {}
    try:
        config = load_config(config_path)
        database = create_database(config)
        with database.connect() as conn:
            conn.execute("SELECT 1").fetchone()
            task_table = conn.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name='task_run'").fetchone() if config.database_type == "sqlite" else conn.execute("SELECT to_regclass('public.task_run')").fetchone()[0]
        checks["database"] = "ok"
        checks["task_run"] = "ok" if task_table else "missing"
        schema = schema_status(config_path)
        if schema.get("up_to_date"):
            checks["schema"] = "ok"
        else:
            checks["schema"] = f"stale: {schema.get('current') or 'none'} -> {schema.get('head') or 'unknown'}"
        ready = bool(task_table) and bool(schema.get("up_to_date"))
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        ready = False
    return {"ok": ready, "status": "ready" if ready else "not_ready", "checks": checks}


# ---------------------------------------------------------------------------
# Content video formatting helpers
# ---------------------------------------------------------------------------

def _frontend_content_status(row: dict[str, Any], failure: dict[str, Any] | None) -> str:
    if str(row.get("summary_status") or "") == "success":
        return "completed"
    if failure:
        return "failed"
    if str(row.get("download_status") or "") == "failed" or str(row.get("transcript_status") or "") == "failed" or str(row.get("summary_status") or "") == "failed":
        return "failed"
    if str(row.get("download_status") or "") in {"done", "success"} or str(row.get("transcript_status") or "") == "success":
        return "processing"
    return "queued"


def _frontend_content_updated_at(row: dict[str, Any], failure: dict[str, Any] | None) -> str:
    return str(
        (failure or {}).get("failed_at")
        or row.get("summary_updated_at")
        or row.get("transcript_updated_at")
        or row.get("transcript_created_at")
        or row.get("aweme_created_at")
        or row.get("create_time")
        or ""
    )


def _frontend_stage_state(raw_status: Any, *, success: bool = False, failed: bool = False) -> str:
    if failed:
        return "failed"
    if success:
        return "success"
    status = str(raw_status or "pending").lower()
    if status in {"done", "success", "completed", "ok"}:
        return "success"
    if status in {"failed", "error", "fail"}:
        return "failed"
    if status in {"running", "processing", "downloading", "transcribing", "summarizing", "noting"}:
        return "processing"
    if status in {"pending", "queued", "waiting"}:
        return "queued"
    return "unknown"


def _frontend_pipeline_steps(row: dict[str, Any]) -> list[dict[str, str]]:
    download_status = str(row.get("download_status") or "pending")
    transcript_status = str(row.get("transcript_status") or "pending")
    summary_status = str(row.get("summary_status") or "pending")
    push_status = str(row.get("push_status") or "pending")
    summary_path = str(row.get("summary_path") or "")
    return [
        {"key": "download", "label": "下载", "state": _frontend_stage_state(download_status, success=bool(row.get("local_path")))},
        {"key": "transcribe", "label": "转录", "state": _frontend_stage_state(transcript_status)},
        {"key": "ai", "label": "AI", "state": _frontend_stage_state(summary_status)},
        {"key": "note", "label": "笔记", "state": _frontend_stage_state(summary_status, success=bool(summary_path) and summary_status == "success")},
        {"key": "push", "label": "推送", "state": _frontend_stage_state(push_status)},
    ]


def _frontend_current_stage(row: dict[str, Any], failure: dict[str, Any] | None) -> str:
    stage = str((failure or {}).get("stage") or "")
    if stage == "whisper":
        return "transcribe"
    if stage in {"download", "transcribe", "ai", "push"}:
        return stage
    for step in _frontend_pipeline_steps(row):
        if step["state"] in {"failed", "processing", "queued"}:
            return step["key"]
    return "done"


def _frontend_transcript(row: dict[str, Any]) -> str:
    text_content = str(row.get("text_content") or "")
    if text_content.strip():
        return text_content
    text_path = Path(str(row.get("text_path") or "")) if row.get("text_path") else None
    if text_path and text_path.exists():
        return read_text(text_path)
    return ""


def _format_aweme_time(value: Any) -> str:
    try:
        timestamp = int(float(value or 0))
    except (TypeError, ValueError):
        timestamp = 0
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    return str(value or "")


def _format_datetime_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value or "").replace("T", " ")[:16]


def _format_duration(value: Any) -> str:
    try:
        seconds = int(float(value or 0))
    except (TypeError, ValueError):
        return str(value or "")
    if seconds <= 0:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"


def _frontend_content(
    config: AppConfig,
    row: dict[str, Any],
    failure: dict[str, Any] | None = None,
    *,
    include_content: bool = False,
) -> dict[str, Any]:
    content_id = str(row.get("content_id") or row.get("aweme_id") or "")
    summary_path = Path(str(row.get("summary_path") or "")) if row.get("summary_path") else None
    summary_markdown = ""
    if include_content:
        if summary_path and summary_path.exists():
            summary_markdown = read_text(summary_path)
        elif row.get("summary_text"):
            summary_markdown = str(row.get("summary_text") or "")
    status = _frontend_content_status(row, failure)
    stage = str((failure or {}).get("stage") or "")
    failure_stage = "transcribe" if stage == "whisper" else stage
    updated_at = _frontend_content_updated_at(row, failure)
    return {
        "id": content_id,
        "content_item_id": int(row.get("content_item_id") or row.get("id") or 0),
        "platform": str(row.get("platform") or "douyin"),
        "title": str(row.get("brief_title") or row.get("title") or "无标题"),
        "brief_summary": str(row.get("brief_summary") or ""),
        "blogger": str(row.get("nickname") or "未知博主"),
        "rating": round(float(row.get("value_score") or 0) * 2, 1),
        "recommend_action": str(row.get("recommended_action") or ""),
        "status": status,
        "failed_at_step": failure_stage,
        "failure_stage": failure_stage,
        "failed_at": str((failure or {}).get("failed_at") or ""),
        "error_message": str((failure or {}).get("error_message") or row.get("summary_error") or ""),
        "created_at": _format_aweme_time(row.get("create_time")),
        "published_at": _format_aweme_time(row.get("create_time")),
        "collected_at": _format_datetime_value(row.get("aweme_created_at")),
        "updated_at": updated_at,
        "duration": _format_duration(row.get("duration")),
        "original_url": str(row.get("source_url") or row.get("video_url") or ""),
        "download_status": str(row.get("download_status") or "pending"),
        "transcript_status": str(row.get("transcript_status") or "pending"),
        "summary_status": str(row.get("summary_status") or "pending"),
        "push_status": str(row.get("push_status") or "pending"),
        "summary_path": str(row.get("summary_path") or ""),
        "current_stage": _frontend_current_stage(row, failure),
        "pipeline_steps": _frontend_pipeline_steps(row),
        "tags": row.get("tags") or [],
        "whisper_text": _frontend_transcript(row) if include_content else "",
        "summary_markdown": summary_markdown,
        "one_sentence_conclusion": str(row.get("one_sentence_conclusion") or ""),
        "importance_score": round(float(row.get("importance_score") or 0) * 2, 1),
        "novelty_score": round(float(row.get("novelty_score") or 0) * 2, 1),
        "information_density": round(float(row.get("information_density") or 0) * 2, 1),
        "business_relevance": round(float(row.get("business_relevance") or 0) * 2, 1),
        "recommendation_reason": str(row.get("recommendation_reason") or ""),
    }


# ---------------------------------------------------------------------------
# Research task formatting
# ---------------------------------------------------------------------------

def _map_task_status(value: str) -> str:
    if value == "paused":
        return "paused"
    if value in {"success", "completed", "transcribe_only_completed"}:
        return "completed"
    if value in {"failed", "cancelled", "partial_failed", "transcribe_only_partial_failed"}:
        return "failed"
    if value in {"pending", "queued"}:
        return "queued"
    return "processing"


def _map_task_stage(value: str) -> str:
    if value in {"downloading", "downloaded", "pending"}:
        return "downloading"
    if value in {"transcribing", "transcribed_waiting_summary"}:
        return "transcribing"
    if value in {"summarizing", "noting"}:
        return "summarizing"
    if value in {"success", "skipped", "completed"}:
        return "completed"
    if value in {"failed", "cancelled"}:
        return "failed"
    return "downloading"


def _frontend_task(row: dict[str, Any]) -> dict[str, Any]:
    total = int(row.get("total_count") or 0)
    done = int(row.get("success_count") or 0) + int(row.get("failed_count") or 0) + int(row.get("skipped_count") or 0)
    status = _map_task_status(str(row.get("status") or "queued"))
    progress = 100 if status == "completed" else (round(done / total * 100) if total else (15 if status in {"queued", "processing"} else 0))
    stage_counts: dict[str, int] = {
        "downloading": int(row.get("stage_downloading") or 0),
        "transcribing": int(row.get("stage_transcribing") or 0),
        "ai": int(row.get("stage_ai") or 0),
        "done": int(row.get("stage_done") or 0),
        "failed": int(row.get("stage_failed") or 0),
    }
    return {
        "id": str(row.get("id") or ""),
        "type": "blogger",
        "target": str(row.get("blogger_name") or row.get("creator_name") or row.get("current_title") or "研究任务"),
        "status": status,
        "total_items": total,
        "completed_items": int(row.get("success_count") or 0),
        "failed_items": int(row.get("failed_count") or 0),
        "skipped_items": int(row.get("skipped_count") or 0),
        "created_at": str(row.get("created_at") or ""),
        "pipeline_stage": "completed" if status == "completed" else _map_task_stage(str(row.get("current_item_status") or row.get("status") or "")),
        "pipeline_progress": progress,
        "pipeline_stages": stage_counts,
        "force_retry": bool(row.get("force_enabled")),
    }


# ---------------------------------------------------------------------------
# Source formatting
# ---------------------------------------------------------------------------

def _frontend_sources(config: AppConfig) -> list[dict[str, Any]]:
    quality_by_name = {str(row.get("nickname") or ""): row for row in _safe_query(lambda: load_source_quality(config), [])}
    sources = []
    database = _safe_query(lambda: create_database(config), None)
    if database is None:
        return []
    for row in _safe_query(database.list_source_subscriptions, []):
        source_id = f"sub:{row.get('id')}"
        enabled = bool(row.get("enabled"))
        last_error = str(row.get("last_error") or "")
        platform = str(row.get("platform") or "")
        name = str(row.get("display_name") or "未命名来源")
        quality = quality_by_name.get(name, {})
        item_count = int(quality.get("total_count") or row.get("item_count") or 0)
        rate = quality.get("summary_success_rate")
        success_rate = float(rate) if rate is not None else 0.0
        average_score = float(quality.get("average_score") or 0)
        sources.append(
            {
                "id": source_id,
                "name": name,
                "url": str(row.get("feed_url") or row.get("source_url") or ""),
                "category": str(row.get("category") or ""),
                "status": "enabled" if enabled else "disabled",
                "quality_score": round(success_rate),
                "last_checked": str(row.get("last_checked_at") or "暂无"),
                "total_captured": item_count,
                "parse_success_rate": round(success_rate),
                "source_scope": "subscription",
                "source_label": "小宇宙订阅" if platform == "xiaoyuzhou" else "数据库订阅",
                "platform": platform,
                "media_type": "audio" if platform == "xiaoyuzhou" else "video",
                "source_type": str(row.get("source_type") or "feed"),
                "feed_url": str(row.get("feed_url") or ""),
                "last_error": last_error,
                "last_item_published_at": str(row.get("last_item_published_at") or row.get("latest_content_published_at") or ""),
                "in_config": True,
                "monitor_enabled": enabled,
                "config_enabled": enabled,
                "can_toggle": True,
                "can_delete_config": True,
            }
        )
    return sources


def _source_subscription_id(source_id: str) -> int:
    text = str(source_id or "").strip()
    if not text.startswith("sub:"):
        return 0
    try:
        return int(text.split(":", 1)[1])
    except ValueError:
        return 0


def _preview_xiaoyuzhou_source(config: AppConfig, url: str) -> dict[str, Any]:
    from kenradar.sources.xiaoyuzhou import XiaoyuzhouAdapter

    source_url = str(url or "").strip()
    if not source_url:
        raise ValueError("请填写小宇宙节目、单集或 RSS Feed URL")
    adapter = XiaoyuzhouAdapter(config)
    items = adapter.resolve_source(source_url)
    if not items:
        raise ValueError("没有解析到可用单集")
    first = items[0]
    raw_source = str(first.raw_metadata.get("source") or "")
    is_episode = "/episode/" in source_url
    source_type = "episode" if is_episode else ("rss" if raw_source == "rss" else "homepage")
    feed_url = source_url if source_type == "rss" else str(first.raw_metadata.get("feed_url") or "")
    display_name = str(first.creator or first.raw_metadata.get("show_title") or "小宇宙播客")
    source_key = feed_url or str(first.creator_id or display_name or source_url)
    return {
        "platform": "xiaoyuzhou",
        "source_type": source_type,
        "source_key": source_key,
        "display_name": display_name,
        "source_url": source_url,
        "feed_url": feed_url,
        "episode_count": len(items),
        "latest_episode_title": first.original_title,
        "latest_episode_id": first.content_id,
        "latest_episode_url": first.source_url,
        "audio_available": bool(first.media_url),
        "media_url": first.media_url or "",
    }


def _extract_source_sec_uid(url: str) -> str:
    match = re.search(r"/user/([^/?#]+)", url or "")
    return match.group(1) if match else ""


def _source_key(item: dict[str, Any]) -> str:
    return str(item.get("sec_uid") or _extract_source_sec_uid(str(item.get("url") or "")) or item.get("url") or item.get("name") or "").strip()


def _source_aliases(item: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for value in (
        item.get("source_key"),
        item.get("key"),
        item.get("sec_uid"),
        _extract_source_sec_uid(str(item.get("douyin_url") or item.get("url") or "")),
        item.get("douyin_url"),
        item.get("url"),
        item.get("nickname"),
        item.get("name"),
    ):
        text = str(value or "").strip()
        if text:
            aliases.add(text)
    return aliases


_DEFAULT_SOURCE_CATEGORIES = ["科技", "财经", "投资", "AI", "商业"]


def _clean_source_category(value: Any) -> str:
    return str(value or "").strip()


def _configured_source_categories(raw: dict[str, Any]) -> list[str]:
    configured = raw.get("source_categories")
    values = configured if isinstance(configured, list) else _DEFAULT_SOURCE_CATEGORIES
    categories: list[str] = []
    for value in values:
        category = _clean_source_category(value)
        if category and category not in categories:
            categories.append(category)
    return categories


def _assigned_source_categories(raw: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    bloggers = raw.get("bloggers", []) or []
    for item in bloggers if isinstance(bloggers, list) else []:
        if not isinstance(item, dict):
            continue
        category = _clean_source_category(item.get("category"))
        if category and category not in categories:
            categories.append(category)
    return categories


def _source_category_options(raw: dict[str, Any]) -> list[str]:
    categories = _configured_source_categories(raw)
    for category in _assigned_source_categories(raw):
        if category not in categories:
            categories.append(category)
    return categories


# ---------------------------------------------------------------------------
# Push / log / alert formatting
# ---------------------------------------------------------------------------

def _frontend_push(row: dict[str, Any]) -> dict[str, Any]:
    import json as _json
    return {
        "id": str(row.get("id") or ""),
        "aweme_id": str(row.get("aweme_id") or ""),
        "title": str(row.get("title") or "无标题"),
        "blogger": str(row.get("nickname") or "未知博主"),
        "push_type": "card" if str(row.get("channel") or "").lower() != "text" else "text",
        "sent_at": str(row.get("pushed_at") or ""),
        "status": "success" if str(row.get("status") or "") == "success" else "failed",
        "response_msg": str(row.get("error_message") or ""),
        "payload": _json.dumps({key: row.get(key) for key in row.keys()}, ensure_ascii=False, default=str, indent=2),
    }


def _frontend_log(row: dict[str, Any], index: int) -> dict[str, Any]:
    level = str(row.get("level") or "info").lower()
    if level == "warning":
        level = "warn"
    module = str(row.get("component") or "WebUI")
    module_map = {"download": "Downloader", "whisper": "Whisper", "openai": "AI", "ai": "AI", "feishu": "Feishu", "web": "WebUI", "scheduler": "Scheduler"}
    return {
        "id": f"log_{index}",
        "timestamp": str(row.get("timestamp") or ""),
        "level": level if level in {"info", "warn", "error", "debug"} else "info",
        "module": module_map.get(module.lower(), "WebUI"),
        "message": str(row.get("message") or row.get("line") or ""),
    }


def _frontend_alert(row: dict[str, Any], index: int) -> dict[str, Any]:
    level = str(row.get("level") or "warn").lower()
    component = str(row.get("component") or "system")
    aweme_id = str(row.get("aweme_id") or "")
    title = str(row.get("title") or (f"内容异常 [{aweme_id}]" if aweme_id else "系统告警"))
    occurrence_count = int(row.get("occurrence_count") or 1)
    description = str(row.get("message") or "")[:1000]
    if occurrence_count > 1:
        description = f"{description}（累计 {occurrence_count} 次）"
    return {
        "id": f"alert_{index}",
        "title": title,
        "desc": description,
        "time": str(row.get("last_seen_at") or row.get("created_at") or ""),
        "level": "critical" if level in {"error", "critical", "fatal"} else "warn",
        "module": component,
    }


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------

def _frontend_system_info(config: AppConfig) -> dict[str, Any]:
    from kenradar.publishing import GithubSyncManager

    gpu_label = "GPU 调度"
    gpu_status = "Active" if bool(config.get("gpu_scheduler.enabled", True)) else "Disabled"
    gpu_percent: int | None = None
    query_tool = str(config.get("gpu_scheduler.memory_check.command") or ("nv" + "idia-smi"))
    try:
        result = subprocess.run(
            [query_tool, "--query-gpu=name,utilization.gpu", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
            check=False,
        )
        first_line = (result.stdout or "").splitlines()[0].strip() if result.stdout else ""
        if result.returncode == 0 and first_line:
            name, _, util = first_line.partition(",")
            gpu_label = name.strip() or gpu_label
            gpu_percent = max(0, min(100, int(float(util.strip() or 0))))
    except Exception:
        gpu_percent = None
    return {
        "port": int(config.get("app.web_port", 8765) or 8765),
        "gpu_label": gpu_label,
        "gpu_status": gpu_status,
        "gpu_percent": gpu_percent,
        "whisper_model": str(config.get("transcribe.model", config.get("ai.whisper.model", "large-v3-turbo"))),
        "log_path": str((config.data_dir / "kenradar.log").relative_to(config.root_dir) if config.data_dir.is_relative_to(config.root_dir) else config.data_dir / "kenradar.log"),
        "health": _safe_query(lambda: load_health(config), {}),
        "background_task": {
            "running": task_state.current().get("running", False),
            "message": task_state.current().get("message", "空闲"),
            "started_at": task_state.current().get("started_at"),
            "finished_at": task_state.current().get("finished_at"),
            "status": task_state.current().get("status", "idle"),
            "requested_by": task_state.current().get("requested_by", ""),
            "progress": task_state.current().get("progress"),
            "queue": task_state.public_queue(),
        },
        "runtime_timeline": _safe_query(lambda: _frontend_runtime_timeline(config), {}),
        "publishing": _safe_query(lambda: GithubSyncManager(config).status_summary(), {}),
    }


# ---------------------------------------------------------------------------
# Config formatting
# ---------------------------------------------------------------------------

def _frontend_config(config: AppConfig) -> dict[str, Any]:
    schedule = config.get("schedule", {}) or {}
    whisper = config.get("ai.whisper", {}) or {}
    transcribe = config.get("transcribe", {}) or {}
    organizer = config.get("ai.organizer", {}) or {}
    providers = organizer.get("providers") if isinstance(organizer.get("providers"), list) else []
    provider = providers[0] if providers else {}
    fallback_provider = next(
        (
            item
            for item in providers[1:]
            if isinstance(item, dict) and item.get("enabled", True) and str(item.get("api_type") or "").lower() == "ollama"
        ),
        {},
    )
    download = config.get("download", {}) or {}
    feishu = config.get("notification.channels.feishu", {}) or {}
    github_pages = config.get("publishing.github_pages", {}) or {}
    github_sync = config.get("publishing.github_sync", {}) or {}
    public_base_url = str(github_pages.get("public_base_url") or "")
    return {
        "scheduler": {
            "enabled": bool(schedule.get("enabled", True)),
            "cronExpression": ", ".join(schedule.get("times", []) or []),
            "grace_period_mins": int(schedule.get("retry_interval_seconds", 300) or 300) // 60,
            "max_concurrent_tasks": int(schedule.get("max_items_per_run", 0) or 0),
            "retry_times": int(schedule.get("retry_times", 2) or 2),
            "max_items_per_blogger": int(schedule.get("max_items_per_blogger", 0) or 0),
            "manual_trigger_enabled": bool(schedule.get("manual_trigger_enabled", True)),
        },
        "whisper": {
            "model": str(transcribe.get("model") or whisper.get("model", "large-v3-turbo")),
            "device": str(transcribe.get("device") or whisper.get("device", "cpu")),
            "threads": int(transcribe.get("cpu_threads_per_worker", whisper.get("cpu_threads", 4)) or 4),
            "use_gpu": str(transcribe.get("device") or whisper.get("device", "cpu")) == "cuda",
            "vram_offload_gb": int(config.get("gpu_scheduler.memory_check.min_free_vram_mb_for_whisper_gpu", 4000) or 4000) // 1000,
            "staged_gpu_scheduling": bool(config.get("gpu_scheduler.enabled", True)),
        },
        "ai": {
            "api_type": str(provider.get("api_type") or organizer.get("api_type") or "chat_completions"),
            "endpoint": str(provider.get("endpoint") or organizer.get("endpoint") or "https://apihub.agnes-ai.com/v1"),
            "model": str(provider.get("model") or organizer.get("model") or "agnes-2.5-flash"),
            "provider_name": str(provider.get("name") or "AI"),
            "fallback_enabled": bool(fallback_provider),
            "fallback_provider_name": str(fallback_provider.get("name") or "ollama"),
            "fallback_endpoint": str(fallback_provider.get("endpoint") or ""),
            "fallback_provider_model": str(fallback_provider.get("model") or ""),
            "temperature": float(organizer.get("temperature", 0.2) or 0.2),
            "top_p": float(provider.get("top_p", organizer.get("top_p", 0.9)) or 0.9),
            "top_k": int(provider.get("top_k", organizer.get("top_k", 40)) or 40),
            "timeout_sec": int(organizer.get("request_timeout", organizer.get("timeout", 120)) or 120),
            "max_tokens": int(organizer.get("max_tokens", 2048) or 2048),
            "max_input_chars": int(provider.get("max_input_chars", organizer.get("max_input_chars", 12000)) or 12000),
            "keep_alive": str(provider.get("keep_alive", organizer.get("keep_alive", "10m")) or "10m"),
            "no_think": bool(provider.get("no_think", organizer.get("no_think", True))),
            "compact_prompt": bool(provider.get("compact_prompt", organizer.get("compact_prompt", True))),
            "fallback_model": str(organizer.get("fallback_model") or ""),
            "prompt_template": str(organizer.get("prompt_template") or ""),
        },
        "download": {
            "path": str(download.get("path") or "data/Downloaded"),
            "max_workers": int(download.get("max_workers", 1) or 1),
            "batch_size": int(download.get("batch_size", 5) or 5),
            "batch_cooldown_seconds": int(download.get("batch_cooldown_seconds", download.get("batch_cooldown", 5)) or 5),
            "max_duration_seconds": int(download.get("max_duration_seconds", 900) or 900),
            "retry_failed": bool(download.get("retry_failed", True)),
            "circuit_breaker_failures": int(download.get("circuit_breaker_failures", 5) or 5),
            "circuit_breaker_cooldown_seconds": int(download.get("circuit_breaker_cooldown_seconds", 300) or 300),
            "save_json": bool(download.get("save_json", True)),
        },
        "feishu": {
            "webhook_url": "",
            "message_type": str(feishu.get("message_type") or "auto"),
            "push_threshold_rating": float(feishu.get("push_threshold_rating", 7.5) or 7.5),
            "retry_attempts": int(feishu.get("retry_attempts", 3) or 3),
            "card_max_items": int(feishu.get("card_max_items", 5) or 5),
            "card_theme": str(feishu.get("card_theme") or "blue"),
        },
        "security": {
            "port": int(config.get("app.web_port", 8765) or 8765),
            "bind_ip": str(config.get("app.web_host", "127.0.0.1")),
            "password_auth": bool(config.get("app.web_password", "")),
            "web_password": "",
            "access_token_ttl_hours": 24,
        },
        "publishing": {
            "github_pages_enabled": bool(github_pages.get("enabled", False)),
            "github_pages_output_dir": str(github_pages.get("output_dir") or "./data/github-pages"),
            "github_pages_public_base_url": public_base_url,
            "github_pages_public_base_url_configured": bool(public_base_url.strip() and "${" not in public_base_url),
            "github_sync_enabled": bool(github_sync.get("enabled", False)),
            "github_sync_repo_dir": str(github_sync.get("repo_dir") or "./data/github-pages"),
            "github_sync_branch": str(github_sync.get("branch") or "gh-pages"),
            "github_sync_auto_commit": bool(github_sync.get("auto_commit", False)),
            "github_sync_auto_push": bool(github_sync.get("auto_push", False)),
            "github_sync_include_html_docs": bool(github_sync.get("include_html_docs", True)),
            "github_sync_include_markdown_notes": bool(github_sync.get("include_markdown_notes", False)),
            "github_sync_include_briefs": bool(github_sync.get("include_briefs", False)),
            "github_sync_include_transcripts": bool(github_sync.get("include_transcripts", False)),
        },
    }


# ---------------------------------------------------------------------------
# Bootstrap (uses helpers above)
# ---------------------------------------------------------------------------

def _build_frontend_bootstrap(config: AppConfig) -> dict[str, Any]:
    from kenradar.core.curation import CurationPolicy
    policy = CurationPolicy.from_config(config)
    library_stats = _safe_query(lambda: load_library_counts(config), {})
    rows = _safe_query(lambda: load_content_rows(config, limit=FRONTEND_BOOTSTRAP_LIMIT), [])
    failures = {str(item.get("aweme_id") or ""): item for item in _safe_query(lambda: load_failures(config, limit=60), [])}
    return {
        "videos": [_frontend_content(config, row, failures.get(str(row.get("aweme_id") or ""))) for row in rows],
        "curationThresholds": policy.frontend_thresholds(),
        "highValueThreshold": policy.frontend_thresholds()["high_value_threshold"],
        "libraryStats": {
            **library_stats,
            "loaded_items": len(rows),
            "display_limit": FRONTEND_BOOTSTRAP_LIMIT,
        },
        "tasks": [_frontend_task(row) for row in _safe_query(lambda: load_research_jobs(config, limit=30), [])],
        "sources": _frontend_sources(config),
        "sourceCategories": _source_category_options(config.raw),
        "pushRecords": [_frontend_push(row) for row in _safe_query(lambda: load_push_logs(config, limit=20), [])],
        # Compatibility keys: heavy archive/log payloads are loaded on demand.
        "logs": [],
        "notes": [],
        "briefs": [],
        "config": _frontend_config(config),
        "alerts": [_frontend_alert(row, index) for index, row in enumerate(_safe_query(lambda: load_recent_alerts(config, limit=20), []))],
        "taskRuns": _safe_query(lambda: load_task_runs(config, limit=30), []),
        "system": _frontend_system_info(config),
        "taskState": task_state.current(),
    }


# ---------------------------------------------------------------------------
# Manual task progress merging
# ---------------------------------------------------------------------------

def _merge_manual_task_progress(progress: dict[str, Any], task_state: dict[str, Any]) -> None:
    if not task_state.get("running"):
        return
    aweme_id = str(progress.get("aweme_id") or "")
    task_id = str(task_state.get("status") or "")
    if not aweme_id or aweme_id not in task_id:
        return

    if task_id.startswith("retry-summary-"):
        stage_key = "ai"
    elif task_id.startswith("retry-transcribe-"):
        stage_key = "transcript"
    elif task_id.startswith("retry-download-"):
        stage_key = "download"
    else:
        stage_key = _first_unfinished_step(progress.get("steps") or [])

    for step in progress.get("steps") or []:
        if step.get("key") == stage_key:
            step["state"] = "running"
            step["status"] = "running"
            step["updated_at"] = str(task_state.get("started_at") or step.get("updated_at") or "")
            step["error"] = ""
        elif stage_key == "ai" and step.get("key") == "note" and step.get("state") != "success":
            step["state"] = "pending"
    progress["overall"] = "running"
    progress["manual_task"] = {
        "status": task_id,
        "message": str(task_state.get("message") or ""),
        "started_at": str(task_state.get("started_at") or ""),
    }
    progress["percent"] = int(sum(int(step.get("weight") or 0) for step in progress.get("steps") or [] if step.get("state") in {"success", "skipped"}) / 4)


def _first_unfinished_step(steps: list[dict[str, Any]]) -> str:
    for step in steps:
        if step.get("state") != "success":
            return str(step.get("key") or "download")
    return "ai"


# ---------------------------------------------------------------------------
# Task lifecycle (used by POST handlers still in app.py)
# ---------------------------------------------------------------------------

def _mark_running_tasks_cancelled(config_path: str, reason: str) -> None:
    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    database.cancel_active_task_runs(reason)
    if config.database_type == "sqlite":
        for job in database.list_research_jobs(limit=1000):
            if job["status"] in {"pending", "running", "paused"}:
                database.control_research_job(job["id"], "cancel", reason)
        return
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='cancelled',
                finished_at=NOW(),
                last_error=%s,
                updated_at=NOW()
            WHERE status IN ('pending', 'running')
            """,
            (reason,),
        )
        conn.execute(
            """
            UPDATE research_job_item
            SET status='cancelled',
                error_message=%s,
                updated_at=NOW()
            WHERE status IN ('pending', 'running', 'downloading', 'downloaded', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting')
            """,
            (reason,),
        )


def _mark_research_job_cancelled(config_path: str, job_id: int, reason: str) -> None:
    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    if config.database_type == "sqlite":
        database.control_research_job(job_id, "cancel", reason)
        return
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='cancelled',
                finished_at=NOW(),
                last_error=%s,
                updated_at=NOW()
            WHERE id = %s AND status IN ('pending', 'running')
            """,
            (reason, job_id),
        )
        conn.execute(
            """
            UPDATE research_job_item
            SET status='cancelled',
                error_message=%s,
                updated_at=NOW()
            WHERE job_id = %s AND status IN ('pending', 'running', 'downloading', 'downloaded', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting')
            """,
            (reason, job_id),
        )


def _mark_research_job_paused(config_path: str, job_id: int) -> None:
    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    if config.database_type == "sqlite":
        database.control_research_job(job_id, "pause", "用户在 Web 后台暂停研究任务")
        return
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='paused',
                last_error='用户在 Web 后台暂停研究任务',
                updated_at=NOW()
            WHERE id = %s AND status = 'running'
            """,
            (job_id,),
        )


def _mark_research_job_resumed(config_path: str, job_id: int) -> None:
    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    if config.database_type == "sqlite":
        database.control_research_job(job_id, "resume")
        return
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='running',
                last_error='',
                updated_at=NOW()
            WHERE id = %s AND status = 'paused'
            """,
            (job_id,),
        )
