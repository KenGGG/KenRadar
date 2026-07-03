from __future__ import annotations

import json
import re
import shutil
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from psycopg.errors import DeadlockDetected

from kenradar.core.config import AppConfig
from kenradar.core.obsidian import brief_dir, summary_dir
from kenradar.domain import (
    ResearchJobItemStatus,
    TranscriptStatus,
    AnalysisStatus,
)
from kenradar.storage import create_database

LEGACY_PROJECT_ROOTS = (
    Path("/home/ken/Projects") / "KenRadar",
)


def load_stats(config: AppConfig) -> dict[str, Any]:
    summaries = list_markdown_files(summary_dir(config))
    database = create_database(config)
    active_config_bloggers = sum(1 for row in _configured_bloggers(config) if row.get("enabled"))
    with database.connect() as conn:
        return {
            "bloggers": active_config_bloggers,
            "awemes": conn.execute("SELECT count(*) FROM aweme").fetchone()[0],
            "transcripts": conn.execute("SELECT count(*) FROM transcript WHERE status='success'").fetchone()[0],
            "pending": conn.execute(
                "SELECT count(*) FROM aweme a LEFT JOIN transcript t ON t.aweme_id=a.aweme_id WHERE COALESCE(t.status,'pending') != 'success'"
            ).fetchone()[0],
            "summaries": len(summaries),
        }


def load_dashboard_stats(config: AppConfig) -> dict[str, Any]:
    notes = list_markdown_files(summary_dir(config))
    database = create_database(config)
    active_config_bloggers = sum(1 for row in _configured_bloggers(config) if row.get("enabled"))
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM aweme WHERE date(created_at)=CURRENT_DATE) AS today_new_items,
              (SELECT count(*) FROM aweme WHERE download_status='done' AND date(created_at)=CURRENT_DATE) AS today_downloaded,
              (SELECT count(*) FROM transcript WHERE status='success' AND date(created_at)=CURRENT_DATE) AS today_transcribed,
              (SELECT count(*) FROM summary WHERE status='success' AND date(updated_at)=CURRENT_DATE) AS today_summarized,
              (SELECT count(*) FROM push_log WHERE status='success' AND date(pushed_at)=CURRENT_DATE) AS today_pushed,
              (SELECT count(*) FROM alert_log WHERE date(created_at)=CURRENT_DATE) AS today_failed,
              (SELECT count(*) FROM aweme WHERE download_status='failed') AS download_failed,
              (SELECT count(*) FROM transcript WHERE status='failed') AS transcript_failed,
              (SELECT count(*) FROM summary WHERE status='failed') AS summary_failed,
              (SELECT max(last_check_at) FROM blogger) AS last_check_time,
              (SELECT max(pushed_at) FROM push_log) AS last_push_time
            """
        ).fetchone()
    data = dict(row) if row else {}
    data["active_blogger_count"] = active_config_bloggers
    data["note_count"] = len(notes)
    return data


def load_health(config: AppConfig) -> dict[str, Any]:
    database = create_database(config)
    total, used, free = shutil.disk_usage(config.data_dir)
    with database.connect() as conn:
        last_check = conn.execute("SELECT max(last_check_at) FROM blogger").fetchone()[0]
        push_total = conn.execute("SELECT count(*) FROM push_log").fetchone()[0]
        push_success = conn.execute("SELECT count(*) FROM push_log WHERE status='success'").fetchone()[0]
        alert_total = conn.execute("SELECT count(*) FROM alert_log").fetchone()[0]
        alert_unnotified = conn.execute("SELECT count(*) FROM alert_log WHERE notified=FALSE").fetchone()[0]
        recent_unnotified_alerts = conn.execute(
            "SELECT count(*) FROM alert_log WHERE notified=FALSE AND created_at >= NOW() - INTERVAL '24 hours'"
        ).fetchone()[0]
        active_failures = conn.execute(
            """
            SELECT
                (SELECT count(*) FROM aweme WHERE download_status='failed')
                + (SELECT count(*) FROM transcript WHERE status='failed')
                + (SELECT count(*) FROM summary WHERE status='failed')
            """
        ).fetchone()[0]
        task_run_failed = conn.execute(
            "SELECT count(*) FROM task_run WHERE status='failed'"
        ).fetchone()[0]
        task_run_running = conn.execute(
            "SELECT count(*) FROM task_run WHERE status='running'"
        ).fetchone()[0]
        task_run_queued = conn.execute(
            "SELECT count(*) FROM task_run WHERE status='queued'"
        ).fetchone()[0]
        alert_attention = int(recent_unnotified_alerts or 0) + int(active_failures or 0)
    return {
        "last_check": last_check or "暂无",
        "schedule": "启用" if config.get("schedule.enabled", True) else "关闭",
        "next_run": next_schedule_time(config),
        "disk_free": f"{free // (1024 ** 3)} GB",
        "disk_used_percent": f"{used / total * 100:.1f}%",
        "push_rate": f"{push_success}/{push_total}" if push_total else "暂无推送",
        "alerts": f"{alert_total} 条 · 未通知 {alert_unnotified}",
        "alert_total": int(alert_total or 0),
        "alert_unnotified": int(alert_unnotified or 0),
        "alert_attention": alert_attention,
        "alert_attention_label": f"{alert_attention} 条需关注",
        "task_run_failed": int(task_run_failed or 0),
        "task_run_running": int(task_run_running or 0),
        "task_run_queued": int(task_run_queued or 0),
        "task_run_attention": int(task_run_failed or 0),
        "task_run_attention_label": f"{int(task_run_failed or 0)} 个任务失败",
    }


def load_aweme_rows(config: AppConfig, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    database = create_database(config)
    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT a.aweme_id, b.nickname, a.title, a.create_time, a.created_at AS aweme_created_at,
                   a.duration, a.video_url, a.cover_url, a.download_status, a.local_path,
                   COALESCE(t.status, 'pending') AS transcript_status,
                   t.error_message AS transcript_error,
                   t.created_at AS transcript_created_at, t.updated_at AS transcript_updated_at,
                   COALESCE(s.status, 'pending') AS summary_status,
                   s.error_message AS summary_error, s.updated_at AS summary_updated_at,
                   COALESCE((SELECT p.status FROM push_log p WHERE p.aweme_id=a.aweme_id ORDER BY p.id DESC LIMIT 1), 'pending') AS push_status,
                   s.summary_text,
                   t.text_path, s.summary_path, length(t.text_content) AS text_len,
                   COALESCE(c.favorite, FALSE) AS favorite,
                   COALESCE(c.topic_pool_status, '') AS topic_pool_status,
                   COALESCE(c.research_status, '') AS research_status,
                   COALESCE(c.user_note, '') AS user_note
            FROM aweme a
            LEFT JOIN blogger b ON b.id = a.blogger_id
            LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
            LEFT JOIN summary s ON s.aweme_id = a.aweme_id
            LEFT JOIN content_curation c ON c.content_item_id = a.id
            ORDER BY a.create_time DESC, a.id DESC
            LIMIT %s OFFSET %s
            """,
            (limit, max(0, int(offset))),
        ).fetchall()
        return [_enrich_aweme_row(dict(row)) for row in rows]


def load_library_counts(config: AppConfig) -> dict[str, int]:
    database = create_database(config)
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT
                count(*) AS total_items,
                count(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1
                        FROM summary s
                        WHERE s.aweme_id = a.aweme_id
                          AND s.status = 'success'
                    )
                ) AS content_notes,
                count(*) FILTER (
                    WHERE EXISTS (
                        SELECT 1
                        FROM transcript t
                        WHERE t.aweme_id = a.aweme_id
                          AND t.status = 'success'
                    )
                ) AS transcripts
            FROM aweme a
            """
        ).fetchone()
    return {
        "total_items": int(row["total_items"] or 0),
        "content_notes": int(row["content_notes"] or 0),
        "transcripts": int(row["transcripts"] or 0),
    }


def load_intelligence_overview(config: AppConfig) -> dict[str, Any]:
    rows = load_aweme_rows(config, limit=1500)
    today = datetime.now().date()
    week_start = datetime.now() - timedelta(days=7)
    today_rows = [row for row in rows if _row_publish_datetime(row) and _row_publish_datetime(row).date() == today]
    week_rows = [row for row in rows if _row_publish_datetime(row) and _row_publish_datetime(row) >= week_start]
    success_rows = [row for row in rows if str(row.get("summary_status") or "") == "success"]
    recommended = [row for row in today_rows if is_recommended_for_reading(row)]
    deep = [row for row in today_rows if row.get("deep_research_suggested") or str(row.get("recommended_action") or "") == "research"]
    if not today_rows:
        recommended = [row for row in success_rows if is_recommended_for_reading(row)][:5]
        deep = [row for row in success_rows if row.get("deep_research_suggested") or str(row.get("recommended_action") or "") == "research"][:5]

    topic_counter: Counter[str] = Counter()
    blogger_counter: Counter[str] = Counter()
    for row in week_rows:
        for tag in row.get("tags") or []:
            topic_counter[str(tag)] += 1
        blogger = str(row.get("nickname") or "")
        if blogger:
            blogger_counter[blogger] += 1

    failures = load_failures(config, limit=20)
    return {
        "today_new": len(today_rows),
        "recommended_count": len(recommended),
        "deep_count": len(deep),
        "failed_count": len(failures),
        "top_items": sorted(recommended, key=lambda row: float(row.get("value_score") or 0), reverse=True)[:5],
        "deep_items": sorted(deep, key=lambda row: float(row.get("value_score") or 0), reverse=True)[:5],
        "topics": topic_counter.most_common(8),
        "bloggers": blogger_counter.most_common(8),
        "failures": failures[:5],
    }


def is_recommended_for_reading(row: dict[str, Any]) -> bool:
    action = str(row.get("recommended_action") or "").lower()
    try:
        value_score = float(row.get("value_score") or 0)
    except (TypeError, ValueError):
        value_score = 0.0
    return action in {"push", "review", "research"} or value_score >= 4


def load_bloggers(config: AppConfig) -> list[dict[str, Any]]:
    database = create_database(config)
    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT b.id, 'douyin' AS platform, b.nickname, b.sec_uid, b.douyin_url, b.enabled,
                   b.last_check_at, b.updated_at, b.last_aweme_id,
                   count(a.id) AS item_count,
                   max(a.create_time) AS last_item_time
            FROM blogger b
            LEFT JOIN aweme a ON a.blogger_id=b.id
            GROUP BY b.id, b.nickname, b.sec_uid, b.douyin_url, b.enabled, b.last_check_at, b.updated_at, b.last_aweme_id
            ORDER BY b.enabled DESC, b.updated_at DESC, b.id DESC
            """
        ).fetchall()
    db_rows = [dict(row) for row in rows]
    config_rows = _configured_bloggers(config)
    config_by_alias: dict[str, dict[str, Any]] = {}
    for row in config_rows:
        for alias in _source_aliases(row):
            config_by_alias.setdefault(alias, row)
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []

    for row in db_rows:
        aliases = _source_aliases(row)
        cfg = next((config_by_alias[alias] for alias in aliases if alias in config_by_alias), None)
        in_config = cfg is not None
        seen.update(aliases)
        row["database_nickname"] = row.get("nickname")
        row["source_key"] = next(iter(aliases), str(row.get("id") or ""))
        row["in_config"] = in_config
        row["config_enabled"] = bool(cfg.get("enabled")) if cfg else False
        row["monitor_enabled"] = in_config and bool(cfg.get("enabled"))
        row["source_scope"] = "config" if in_config else "database"
        if cfg:
            row["nickname"] = cfg.get("name") or row.get("nickname")
            row["douyin_url"] = cfg.get("url") or row.get("douyin_url")
            row["sec_uid"] = cfg.get("sec_uid") or row.get("sec_uid")
            row["category"] = cfg.get("category") or ""
        merged.append(row)

    for cfg in config_rows:
        aliases = _source_aliases(cfg)
        if aliases & seen:
            continue
        merged.append(
            {
                "id": None,
                "platform": cfg.get("platform") or "douyin",
                "nickname": cfg.get("name") or cfg.get("sec_uid") or "未命名博主",
                "database_nickname": "",
                "sec_uid": cfg.get("sec_uid") or "",
                "douyin_url": cfg.get("url") or "",
                "category": cfg.get("category") or "",
                "enabled": 1 if cfg.get("enabled") else 0,
                "config_enabled": bool(cfg.get("enabled")),
                "monitor_enabled": bool(cfg.get("enabled")),
                "in_config": True,
                "source_scope": "config",
                "source_key": cfg.get("key") or next(iter(aliases), ""),
                "last_check_at": "",
                "updated_at": "",
                "last_aweme_id": "",
                "item_count": 0,
                "last_item_time": "",
            }
        )
    return sorted(merged, key=lambda row: (not bool(row.get("monitor_enabled")), str(row.get("nickname") or "")))


def load_source_quality(config: AppConfig) -> list[dict[str, Any]]:
    rows = load_aweme_rows(config, limit=5000)
    grouped: dict[str, list[dict[str, Any]]] = {}
    now = datetime.now()
    for row in rows:
        name = str(row.get("nickname") or "未知博主")
        grouped.setdefault(name, []).append(row)
    result: list[dict[str, Any]] = []
    for name, items in grouped.items():
        if not items:
            continue
        week_count = 0
        month_count = 0
        scores = []
        recommended = 0
        deep = 0
        pushed = 0
        success_summary = 0
        for item in items:
            published = _row_publish_datetime(item)
            if published and (now - published).days < 7:
                week_count += 1
            if published and (now - published).days < 30:
                month_count += 1
            score = float(item.get("value_score") or 0)
            if score:
                scores.append(score)
            if is_recommended_for_reading(item):
                recommended += 1
            if item.get("deep_research_suggested") or str(item.get("recommended_action") or "") == "research":
                deep += 1
            if str(item.get("push_status") or "") == "success":
                pushed += 1
            if str(item.get("summary_status") or "") == "success":
                success_summary += 1
        total = len(items)
        result.append(
            {
                "nickname": name,
                "total_count": total,
                "week_count": week_count,
                "month_count": month_count,
                "effective_rate": round(recommended / total * 100, 1) if total else 0,
                "average_score": round(sum(scores) / len(scores), 1) if scores else 0,
                "push_rate": round(pushed / total * 100, 1) if total else 0,
                "summary_success_rate": round(success_summary / total * 100, 1) if total else 0,
                "deep_count": deep,
            }
        )
    return sorted(result, key=lambda row: (float(row.get("average_score") or 0), int(row.get("month_count") or 0)), reverse=True)


def _configured_bloggers(config: AppConfig) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    bloggers = config.get("bloggers", []) or []
    if not isinstance(bloggers, list):
        return result
    for item in bloggers:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        sec_uid = str(item.get("sec_uid") or _extract_sec_uid(url) or "")
        key = sec_uid or url or str(item.get("name") or "")
        result.append(
            {
                "key": key,
                "platform": str(item.get("platform") or "douyin"),
                "name": str(item.get("name") or sec_uid or "未命名博主"),
                "url": url,
                "sec_uid": sec_uid,
                "category": str(item.get("category") or ""),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return result


def _extract_sec_uid(url: str) -> str:
    match = re.search(r"/user/([^/?#]+)", url or "")
    return match.group(1) if match else ""


def _source_aliases(row: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for value in (
        row.get("key"),
        row.get("sec_uid"),
        _extract_sec_uid(str(row.get("douyin_url") or row.get("url") or "")),
        row.get("douyin_url"),
        row.get("url"),
        row.get("nickname"),
        row.get("name"),
    ):
        text = str(value or "").strip()
        if text:
            aliases.add(text)
    return aliases


def load_push_logs(config: AppConfig, limit: int = 100) -> list[dict[str, Any]]:
    database = create_database(config)
    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.aweme_id, p.batch_id, p.channel, p.status, p.error_message, p.pushed_at,
                   a.title, b.nickname, s.summary_path
            FROM push_log p
            LEFT JOIN aweme a ON a.aweme_id=p.aweme_id
            LEFT JOIN blogger b ON b.id=a.blogger_id
            LEFT JOIN summary s ON s.aweme_id=p.aweme_id
            ORDER BY p.id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def load_failures(config: AppConfig, limit: int = 200) -> list[dict[str, Any]]:
    database = create_database(config)
    failures: dict[tuple[str, str], dict[str, Any]] = {}
    with database.connect() as conn:
        alerts = conn.execute(
            """
            SELECT 'alert' AS source, l.component AS stage, l.aweme_id, l.title, l.message AS error_message,
                   l.created_at AS failed_at, l.notified,
                   COALESCE(a.download_status, 'pending') AS download_status,
                   COALESCE(t.status, 'pending') AS transcript_status,
                   COALESCE(s.status, 'pending') AS summary_status
            FROM alert_log l
            LEFT JOIN aweme a ON a.aweme_id = l.aweme_id
            LEFT JOIN transcript t ON t.aweme_id = l.aweme_id
            LEFT JOIN summary s ON s.aweme_id = l.aweme_id
            WHERE l.aweme_id IS NOT NULL AND l.aweme_id != ''
            ORDER BY l.id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        for row in alerts:
            item = dict(row)
            stage = _normalize_failure_stage(str(item.get("stage") or ""), str(item.get("error_message") or ""))
            if not _stage_still_failed(stage, item):
                continue
            item["stage"] = stage
            failures.setdefault((str(item.get("aweme_id") or ""), stage), item)
        rows = conn.execute(
            """
            SELECT 'task' AS source, 'download' AS stage, a.aweme_id, a.title,
                   'download_status=failed' AS error_message, a.created_at AS failed_at, 0 AS notified,
                   a.download_status, COALESCE(t.status, 'pending') AS transcript_status, COALESCE(s.status, 'pending') AS summary_status
            FROM aweme a
            LEFT JOIN transcript t ON t.aweme_id=a.aweme_id
            LEFT JOIN summary s ON s.aweme_id=a.aweme_id
            WHERE a.download_status='failed'
            UNION ALL
            SELECT 'task' AS source, 'whisper' AS stage, t.aweme_id, a.title,
                   COALESCE(t.error_message, 'transcript failed') AS error_message, t.created_at AS failed_at, 0 AS notified,
                   COALESCE(a.download_status, 'pending') AS download_status, t.status AS transcript_status, COALESCE(s.status, 'pending') AS summary_status
            FROM transcript t
            LEFT JOIN aweme a ON a.aweme_id=t.aweme_id
            LEFT JOIN summary s ON s.aweme_id=t.aweme_id
            WHERE t.status='failed'
            UNION ALL
            SELECT 'task' AS source, 'ai' AS stage, s.aweme_id, a.title,
                   COALESCE(s.error_message, 'summary failed') AS error_message, s.updated_at AS failed_at, 0 AS notified,
                   COALESCE(a.download_status, 'pending') AS download_status, COALESCE(t.status, 'pending') AS transcript_status, s.status AS summary_status
            FROM summary s
            LEFT JOIN aweme a ON a.aweme_id=s.aweme_id
            LEFT JOIN transcript t ON t.aweme_id=s.aweme_id
            WHERE s.status='failed'
            ORDER BY failed_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
        for row in rows:
            item = dict(row)
            stage = _normalize_failure_stage(str(item.get("stage") or ""), str(item.get("error_message") or ""))
            item["stage"] = stage
            failures[(str(item.get("aweme_id") or ""), stage)] = item
    return sorted(failures.values(), key=lambda item: str(item.get("failed_at") or ""), reverse=True)[:limit]


def _normalize_failure_stage(stage: str, message: str = "") -> str:
    value = stage.lower()
    text = message.lower()
    if value in {"download", "downloader"} or "download" in text or "下载" in message:
        return "download"
    if value in {"whisper", "transcript", "transcribe"} or "whisper" in text or "transcript" in text or "转录" in message:
        return "whisper"
    if value in {"ai", "summary", "openai", "openai_api", "organizer"} or "openai" in text or "summary" in text or "ai" in text:
        return "ai"
    return value or "unknown"


def _stage_still_failed(stage: str, item: dict[str, Any]) -> bool:
    if stage == "download":
        return str(item.get("download_status") or "pending") == "failed"
    if stage == "whisper":
        return str(item.get("transcript_status") or "pending") == "failed"
    if stage == "ai":
        return str(item.get("summary_status") or "pending") == "failed"
    return False


def load_brief_files(config: AppConfig) -> list[dict[str, Any]]:
    files = list_markdown_files(brief_dir(config))
    result: list[dict[str, Any]] = []
    for path in files:
        content = read_text(path)
        result.append(
            {
                "path": str(path),
                "name": path.name,
                "title": first_heading(content) or path.stem,
                "created_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "item_count": content.count("\n### "),
                "status": "success" if "推送状态：success" in content else ("pending" if "推送状态：pending" in content else "unknown"),
            }
        )
    return result


def generate_weekly_brief(config: AppConfig) -> Path:
    rows = load_aweme_rows(config, limit=5000)
    since = datetime.now() - timedelta(days=7)
    week_rows = [row for row in rows if _row_publish_datetime(row) and _row_publish_datetime(row) >= since]
    week_rows = sorted(week_rows, key=lambda row: float(row.get("value_score") or 0), reverse=True)
    topic_counter: Counter[str] = Counter()
    blogger_counter: Counter[str] = Counter()
    for row in week_rows:
        for tag in row.get("tags") or []:
            topic_counter[str(tag)] += 1
        blogger = str(row.get("nickname") or "")
        if blogger:
            blogger_counter[blogger] += 1
    now = datetime.now()
    output_dir = brief_dir(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"weekly_{now.strftime('%Y-W%W')}_周报.md"
    lines = [
        f"# KenRadar 周报｜{now.strftime('%Y-%m-%d')}",
        "",
        f"统计范围：{since.strftime('%Y-%m-%d %H:%M')} 至 {now.strftime('%Y-%m-%d %H:%M')}",
        f"本周归档内容：{len(week_rows)} 条",
        "",
        "## 主题趋势",
        "",
    ]
    if topic_counter:
        lines.extend(f"- {name}：{count} 条" for name, count in topic_counter.most_common(12))
    else:
        lines.append("- 暂无主题标签。")
    lines.extend(["", "## 高活跃博主", ""])
    if blogger_counter:
        lines.extend(f"- {name}：{count} 条" for name, count in blogger_counter.most_common(12))
    else:
        lines.append("- 暂无博主更新。")
    lines.extend(["", "## 本周重点内容", ""])
    for index, row in enumerate(week_rows[:12], start=1):
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("brief_title") or row.get("title") or "无标题")
        summary = str(row.get("brief_summary") or "")
        reason = str(row.get("recommendation_reason") or "")
        tags = " / ".join(row.get("tags") or [])
        detail_url = str(config.get("app.web_base_url", "http://172.30.10.150:8765")).rstrip("/") + f"/aweme?id={aweme_id}"
        lines.extend(
            [
                f"### {index}. {title}",
                "",
                f"- 博主：{row.get('nickname') or '未知'}",
                f"- 价值评分：{row.get('value_score') or '暂无'}",
                f"- 推荐动作：{row.get('recommended_action') or '待判断'}",
                f"- 标签：{tags or '暂无'}",
                f"- 摘要：{summary or '暂无'}",
                f"- 推荐理由：{reason or '暂无'}",
                f"- 详情：{detail_url}",
                "",
            ]
        )
    if not week_rows:
        lines.append("暂无内容。")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def load_note_files(config: AppConfig) -> list[dict[str, Any]]:
    files = list_markdown_files(summary_dir(config))
    result: list[dict[str, Any]] = []
    root = summary_dir(config).resolve()
    for path in files:
        rel = path.resolve().relative_to(root) if root in path.resolve().parents else path.name
        parts = Path(rel).parts if not isinstance(rel, str) else (rel,)
        content = read_text(path)
        result.append(
            {
                "path": str(path),
                "name": path.name,
                "platform": parts[0] if len(parts) > 0 else "",
                "blogger": parts[1] if len(parts) > 1 else "",
                "title": first_heading(content) or path.stem,
                "updated_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_kb": path.stat().st_size // 1024,
            }
        )
    return result


def load_log_lines(config: AppConfig, limit: int = 500) -> list[dict[str, str]]:
    path = config.data_dir / "kenradar.log"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    result: list[dict[str, str]] = []
    for line in reversed(lines):
        timestamp = ""
        message = line
        level = "info"
        component = "system"
        match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+(\w+)\s+\[([^\]]+)\]\s+(.*)$", line)
        if match:
            timestamp = match.group(1)
            level = match.group(2).lower()
            raw_component = match.group(3)
            component = raw_component.rsplit(".", 1)[-1] or raw_component
            message = match.group(4)

        lower = line.lower()
        if "error" in lower or "exception" in lower or "失败" in line:
            level = "error"
        elif "warning" in lower or "warn" in lower:
            level = "warning"

        if component == "system":
            for name in ("crawler", "download", "whisper", "openai", "ai", "feishu", "web", "note"):
                if name in lower:
                    component = name
                    break

        result.append({"timestamp": timestamp, "level": level, "component": component, "message": message, "line": line})
    return result


def load_research_jobs(config: AppConfig, limit: int = 100) -> list[dict[str, Any]]:
    return create_database(config).list_research_jobs(limit)


def load_research_job(config: AppConfig, job_id: int) -> dict[str, Any] | None:
    return create_database(config).get_research_job(job_id)


def load_research_job_items(config: AppConfig, job_id: int, limit: int = 500) -> list[dict[str, Any]]:
    rows = create_database(config).list_research_job_items(job_id, limit)
    return [_with_effective_research_status(row) for row in rows]


def load_research_pipeline_stats(config: AppConfig, job_id: int) -> dict[str, Any]:
    database = create_database(config)
    status_groups = {
        "download": {ResearchJobItemStatus.PENDING.value, ResearchJobItemStatus.DOWNLOADING.value},
        "transcript": {ResearchJobItemStatus.DOWNLOADED.value, ResearchJobItemStatus.TRANSCRIBING.value},
        "ai": {ResearchJobItemStatus.TRANSCRIBED_WAITING_SUMMARY.value, ResearchJobItemStatus.SUMMARIZING.value, ResearchJobItemStatus.NOTING.value},
        "done": {ResearchJobItemStatus.SUCCESS.value, ResearchJobItemStatus.SKIPPED.value},
        "failed": {ResearchJobItemStatus.FAILED.value, ResearchJobItemStatus.CANCELLED.value},
    }
    counts = {key: 0 for key in status_groups}
    status_counts: Counter[str] = Counter()
    samples: dict[str, list[dict[str, str]]] = {key: [] for key in status_groups}
    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT i.aweme_id, i.status, i.updated_at, COALESCE(a.title, i.aweme_id) AS title,
                   COALESCE(t.status, 'pending') AS transcript_status,
                   COALESCE(s.status, 'pending') AS summary_status
            FROM research_job_item i
            LEFT JOIN aweme a ON a.aweme_id = i.aweme_id
            LEFT JOIN transcript t ON t.aweme_id = i.aweme_id
            LEFT JOIN summary s ON s.aweme_id = i.aweme_id
            WHERE i.job_id = %s
            ORDER BY i.updated_at DESC, i.id DESC
            """,
            (job_id,),
        ).fetchall()
        timing = conn.execute(
            """
            SELECT
              COUNT(*) AS done_count,
              (EXTRACT(EPOCH FROM MAX(updated_at)) - EXTRACT(EPOCH FROM MIN(created_at))) AS elapsed_seconds
            FROM research_job_item
            WHERE job_id = %s AND status IN (%s, %s)
            """,
            (job_id, ResearchJobItemStatus.SUCCESS.value, ResearchJobItemStatus.FAILED.value),
        ).fetchone()
    for raw_row in rows:
        row = _with_effective_research_status(dict(raw_row))
        status = str(row["status"] or "pending")
        status_counts[status] += 1
        for group, statuses in status_groups.items():
            if status in statuses:
                counts[group] += 1
                if len(samples[group]) < 5:
                    samples[group].append(
                        {
                            "aweme_id": str(row["aweme_id"] or ""),
                            "title": str(row["title"] or ""),
                            "status": status,
                            "updated_at": str(row["updated_at"] or ""),
                        }
                    )
                break
    active_remaining = counts.get("download", 0) + counts.get("transcript", 0) + counts.get("ai", 0)
    done_count = int(timing["done_count"] or 0) if timing else 0
    elapsed_seconds = float(timing["elapsed_seconds"] or 0) if timing else 0.0
    eta_seconds = int(elapsed_seconds / done_count * active_remaining) if done_count > 0 and active_remaining > 0 else 0
    return {
        "counts": counts,
        "status_counts": dict(status_counts),
        "total_items": len(rows),
        "active_remaining": active_remaining,
        "samples": samples,
        "download_dir_size": _format_bytes(_folder_size(config.download_dir)),
        "notes_dir_size": _format_bytes(_folder_size(summary_dir(config))),
        "eta_seconds": eta_seconds,
        "eta_text": _format_duration(eta_seconds),
    }


def _with_effective_research_status(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status") or "pending")
    transcript_status = str(row.get("transcript_status") or "")
    summary_status = str(row.get("summary_status") or "")
    if summary_status == "success":
        row["raw_status"] = status
        row["status"] = "success"
        row["error_message"] = None
    elif status not in {"failed", "cancelled", "success", "skipped"} and transcript_status == "success" and status not in {"summarizing", "noting"}:
        row["raw_status"] = status
        row["status"] = "transcribed_waiting_summary"
    return row


def _folder_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "暂无"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分"
    if minutes:
        return f"{minutes} 分 {sec} 秒"
    return f"{sec} 秒"


def load_recent_alerts(config: AppConfig, limit: int = 10) -> list[dict[str, Any]]:
    return create_database(config).list_recent_alerts(limit)


def load_task_runs(config: AppConfig, limit: int = 200) -> list[dict[str, Any]]:
    database = create_database(config)
    with database.connect() as conn:
        rows = conn.execute(
            """
            SELECT id, task_type, payload_json, message, requested_by, worker_name, priority,
                   idempotency_key, status, progress_json, stats_json, available_at,
                   lease_expires_at, heartbeat_at, cancel_requested_at, attempt, max_attempts,
                   started_at, finished_at,
                   last_error, created_at, updated_at
            FROM task_run
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [_normalize_task_run_row(dict(row)) for row in rows]


def load_task_run_detail(config: AppConfig, run_id: int) -> dict[str, Any] | None:
    if run_id <= 0:
        return None
    database = create_database(config)
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT id, task_type, payload_json, message, requested_by, worker_name, priority,
                   idempotency_key, status, progress_json, stats_json, available_at,
                   lease_expires_at, heartbeat_at, cancel_requested_at, attempt, max_attempts,
                   started_at, finished_at,
                   last_error, created_at, updated_at
            FROM task_run
            WHERE id = %s
            """,
            (run_id,),
        ).fetchone()
    return _normalize_task_run_row(dict(row)) if row else None


def _normalize_task_run_row(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("payload_json", "progress_json", "stats_json"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = {}
        if not isinstance(value, dict):
            value = {}
        row[key] = value
    row["status_label"] = _task_run_status_label(str(row.get("status") or ""))
    row["task_label"] = _task_run_type_label(str(row.get("task_type") or ""))
    row["requested_by_label"] = _task_requested_by_label(str(row.get("requested_by") or ""))
    return row


def _task_run_status_label(value: str) -> str:
    mapping = {
        "queued": "排队中",
        "running": "执行中",
        "success": "成功",
        "failed": "失败",
        "cancelled": "已取消",
    }
    return mapping.get(value, value or "未知")


def _task_run_type_label(value: str) -> str:
    mapping = {
        "system_health_check": "任务引擎健康检查",
        "run_once": "手动/定时检测",
        "test_latest": "最新作品测试",
        "retry_summary": "重试 AI 整理",
        "retry_download": "重试下载",
        "retry_transcribe": "重试转录",
        "retry_full": "全流程重试",
        "retry_batch": "批量重试",
        "retry_research_failed": "重跑研究失败项",
        "restart_research_job": "重启研究任务",
        "research_blogger": "研究博主",
        "research_video": "研究单视频",
        "summarize_existing": "补齐摘要",
        "backfill": "历史回填",
        "company_research_batch": "公司研究批次",
        "company_research_cleanup_notebooks": "清理 Notebook",
        "company_research_cleanup_local_pdfs": "清理本地 PDF",
        "company_financial_analysis": "公司财务分析",
    }
    return mapping.get(value, value or "未知任务")


def _task_requested_by_label(value: str) -> str:
    mapping = {
        "web": "Web 手动触发",
        "scheduler": "内置调度器",
        "codex": "Codex",
        "cli": "命令行",
        "api": "API",
    }
    return mapping.get(value, value or "未知来源")


def load_aweme_detail(config: AppConfig, aweme_id: str) -> dict[str, Any] | None:
    database = create_database(config)
    sql = """
        SELECT a.aweme_id, b.nickname, a.title, a.create_time, a.duration, a.video_url, a.cover_url, a.download_status,
               COALESCE(t.status, 'pending') AS transcript_status,
               t.text_content, t.text_path, t.json_path,
               s.summary_text, s.summary_path, s.model AS summary_model,
               COALESCE(s.status, 'pending') AS summary_status,
               COALESCE((SELECT p.status FROM push_log p WHERE p.aweme_id=a.aweme_id ORDER BY p.id DESC LIMIT 1), 'pending') AS push_status,
               s.error_message AS summary_error,
               COALESCE(c.favorite, FALSE) AS favorite,
               COALESCE(c.topic_pool_status, '') AS topic_pool_status,
               COALESCE(c.research_status, '') AS research_status,
               COALESCE(c.user_note, '') AS user_note
        FROM aweme a
        LEFT JOIN blogger b ON b.id = a.blogger_id
        LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
        LEFT JOIN summary s ON s.aweme_id = a.aweme_id
        LEFT JOIN content_curation c ON c.content_item_id = a.id
        WHERE a.aweme_id = %s
        """
    for attempt in range(3):
        try:
            with database.connect() as conn:
                row = conn.execute(sql, (aweme_id,)).fetchone()
                return _enrich_aweme_row(dict(row)) if row else None
        except DeadlockDetected:
            if attempt == 2:
                raise
            time.sleep(0.15 * (attempt + 1))
    return None


def load_aweme_progress(config: AppConfig, aweme_id: str) -> dict[str, Any] | None:
    database = create_database(config)
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT a.aweme_id, a.title, a.download_status, a.local_path, a.created_at AS aweme_updated_at,
                   b.nickname,
                   COALESCE(t.status, 'pending') AS transcript_status,
                   t.error_message AS transcript_error,
                   t.text_path, t.json_path, t.created_at AS transcript_created_at, t.updated_at AS transcript_updated_at,
                   COALESCE(s.status, 'pending') AS summary_status,
                   s.error_message AS summary_error,
                   s.summary_path, s.model AS summary_model, s.updated_at AS summary_updated_at,
                   i.job_id AS latest_job_id,
                   i.status AS latest_item_status,
                   i.error_message AS latest_item_error,
                   i.created_at AS latest_item_created_at,
                   i.updated_at AS latest_item_updated_at,
                   j.status AS latest_job_status,
                   j.blogger_name AS latest_job_name
            FROM aweme a
            LEFT JOIN blogger b ON b.id = a.blogger_id
            LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
            LEFT JOIN summary s ON s.aweme_id = a.aweme_id
            LEFT JOIN research_job_item i ON i.id = (
                SELECT id
                FROM research_job_item
                WHERE aweme_id = a.aweme_id
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
            )
            LEFT JOIN research_job j ON j.id = i.job_id
            WHERE a.aweme_id = %s
            """,
            (aweme_id,),
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    steps = _aweme_progress_steps(data)
    percent = int(sum(_step_progress_value(step) for step in steps) / 4)
    if any(step["state"] == "failed" for step in steps):
        overall = "failed"
    elif percent >= 100:
        overall = "success"
    elif any(step["state"] == "running" for step in steps):
        overall = "running"
    else:
        overall = "pending"
    return {
        "aweme_id": str(data.get("aweme_id") or ""),
        "title": str(data.get("title") or ""),
        "blogger_name": str(data.get("nickname") or ""),
        "overall": overall,
        "percent": percent,
        "steps": steps,
        "latest_job": {
            "id": data.get("latest_job_id"),
            "status": str(data.get("latest_job_status") or ""),
            "item_status": str(data.get("latest_item_status") or ""),
            "name": str(data.get("latest_job_name") or ""),
            "updated_at": str(data.get("latest_item_updated_at") or ""),
            "error": str(data.get("latest_item_error") or ""),
        },
        "model": str(data.get("summary_model") or ""),
        "updated_at": str(data.get("summary_updated_at") or data.get("latest_item_updated_at") or data.get("transcript_updated_at") or data.get("transcript_created_at") or data.get("aweme_updated_at") or ""),
    }


def _aweme_progress_steps(row: dict[str, Any]) -> list[dict[str, Any]]:
    item_status = str(row.get("latest_item_status") or "").lower()
    download_status = str(row.get("download_status") or "pending").lower()
    transcript_status = str(row.get("transcript_status") or "pending").lower()
    summary_status = str(row.get("summary_status") or "pending").lower()
    summary_path = str(row.get("summary_path") or "").strip()

    download_state = _progress_state(
        status=download_status,
        running=item_status == "downloading",
        success=download_status in {"done", "success", "completed", "ok"} or bool(row.get("local_path")),
    )
    transcript_state = _progress_state(
        status=transcript_status,
        running=item_status == "transcribing",
        success=transcript_status == "success",
    )
    ai_state = _progress_state(
        status=summary_status,
        running=item_status == "summarizing",
        success=summary_status == "success",
    )
    note_state = "success" if summary_path and summary_status == "success" else ("running" if item_status == "noting" else ("failed" if summary_status == "failed" else "pending"))

    transcript_error = row.get("transcript_error")
    if transcript_state == "success" and str(transcript_error or "").startswith("no_speech_music_dominant"):
        transcript_error = ""

    return [
        _progress_step("download", "下载", download_state, download_status, row.get("latest_item_updated_at"), row.get("latest_item_error")),
        _progress_step("transcript", "语音转录", transcript_state, transcript_status, row.get("transcript_updated_at") or row.get("transcript_created_at"), transcript_error, _extract_progress_percent(row.get("transcript_error"))),
        _progress_step("ai", "AI 整理", ai_state, summary_status, row.get("summary_updated_at"), row.get("summary_error")),
        _progress_step("note", "Markdown 笔记", note_state, "success" if note_state == "success" else summary_status, row.get("summary_updated_at"), row.get("summary_error")),
    ]


def _progress_state(status: str, *, running: bool = False, success: bool = False) -> str:
    if running:
        return "running"
    if success:
        return "success"
    if status in {"failed", "error", "fail"}:
        return "failed"
    if status in {"skipped", "skip"}:
        return "skipped"
    return "pending"


def _progress_step(key: str, label: str, state: str, raw_status: Any, updated_at: Any, error: Any = "", progress_percent: int | None = None) -> dict[str, Any]:
    visible_error = "" if str(error or "").startswith("progress=") else str(error or "")
    return {
        "key": key,
        "label": label,
        "state": state,
        "status": str(raw_status or ""),
        "updated_at": str(updated_at or ""),
        "error": visible_error,
        "progress_percent": progress_percent,
        "weight": 100,
    }


def _extract_progress_percent(value: Any) -> int | None:
    match = re.search(r"progress=(\d+)", str(value or ""))
    if not match:
        return None
    return max(0, min(99, int(match.group(1))))


def _step_progress_value(step: dict[str, Any]) -> int:
    if step.get("state") in {"success", "skipped"}:
        return 100
    if step.get("state") == "running" and step.get("progress_percent") is not None:
        return max(0, min(99, int(step.get("progress_percent") or 0)))
    return 0


def find_aweme_markdown(config: AppConfig, row: dict[str, Any]) -> Path | None:
    aweme_id = str(row.get("aweme_id") or "")
    candidates: list[Path] = []
    summary_path_value = str(row.get("summary_path") or "").strip()
    if summary_path_value:
        candidates.append(Path(summary_path_value))
    text_path_value = str(row.get("text_path") or "").strip()
    if text_path_value:
        text_path = Path(text_path_value)
        candidates.extend([text_path.with_suffix(".md"), text_path.with_name(f"{aweme_id}.md")])
    candidates.extend(summary_dir(config).glob(f"**/*{aweme_id}*.md"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


_AWEME_ID_RE = re.compile(r"(\d{15,})")


def find_aweme_id_from_note_path(config: AppConfig, path: Path) -> str | None:
    """Try to extract aweme_id from a note file path, or find it via DB."""
    name = path.stem
    match = _AWEME_ID_RE.search(name)
    if match:
        return match.group(1)
    database = create_database(config)
    with database.connect() as conn:
        row = conn.execute(
            "SELECT aweme_id FROM summary WHERE summary_path LIKE %s LIMIT 1",
            (f"%{name}%",),
        ).fetchone()
        if row:
            return str(row["aweme_id"])
        row = conn.execute(
            "SELECT aweme_id FROM transcript WHERE text_path LIKE %s LIMIT 1",
            (f"%{name}%",),
        ).fetchone()
        if row:
            return str(row["aweme_id"])
    return None


def list_markdown_files(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(folder.glob("**/*.md"), key=lambda path: path.stat().st_mtime, reverse=True)


def safe_data_path(config: AppConfig, raw_path: str) -> Path:
    value = unquote(raw_path or "")
    path = normalize_project_path(config, Path(value))
    if not path.is_absolute():
        path = config.root_dir / path
    path = path.resolve()
    data_dir = config.data_dir.resolve()
    if data_dir not in path.parents and path != data_dir:
        raise ValueError("只能读取 data 目录下的文件")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def normalize_project_path(config: AppConfig, path: Path) -> Path:
    if not path.is_absolute():
        return path
    for legacy_root in LEGACY_PROJECT_ROOTS:
        try:
            relative = path.resolve().relative_to(legacy_root)
        except ValueError:
            continue
        return config.root_dir / relative
    return path


def read_text(path: Path | None) -> str:
    if not path:
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def first_heading(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def parse_summary_json(value: str) -> dict[str, Any] | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        text = re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)"', r'\1"\2"', text)
        text = re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _enrich_aweme_row(row: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_summary_json(str(row.get("summary_text") or "")) or {}
    row["summary_json"] = parsed
    row["brief_title"] = str(parsed.get("brief_title") or row.get("title") or "无标题")
    row["brief_summary"] = str(parsed.get("brief_summary") or "")
    row["one_sentence_conclusion"] = str(
        parsed.get("one_sentence")
        or parsed.get("one_sentence_conclusion")
        or parsed.get("summary")
        or parsed.get("brief_summary")
        or ""
    )
    row["tags"] = _string_list(parsed.get("tags") or parsed.get("keywords") or [])
    row["keywords"] = _string_list(parsed.get("keywords") or [])
    row["recommended_action"] = _normalize_action(parsed.get("recommended_action"))
    row["recommendation_reason"] = str(parsed.get("recommendation_reason") or "")
    row["deep_research_suggested"] = bool(parsed.get("deep_research_suggested"))
    row["importance_score"] = _score(parsed.get("importance_score"), parsed.get("importance_level"))
    row["novelty_score"] = _score(parsed.get("novelty_score"))
    row["information_density"] = _score(parsed.get("information_density"))
    row["business_relevance"] = _score(parsed.get("business_relevance"))
    row["value_score"] = _score(parsed.get("value_score")) or _average_score(
        row["importance_score"],
        row["novelty_score"],
        row["information_density"],
        row["business_relevance"],
    )
    return row


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:8]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，/、\s]+", value) if item.strip()][:8]
    return []


def _normalize_action(value: Any) -> str:
    action = str(value or "").strip().lower()
    if action in {"push", "archive", "review", "research"}:
        return action
    return ""


def _score(value: Any, level: Any = None) -> float:
    try:
        score = float(value)
        if score > 0:
            return max(1.0, min(5.0, score))
    except (TypeError, ValueError):
        pass
    level_text = str(level or "")
    if level_text == "高":
        return 4.5
    if level_text == "中":
        return 3.0
    if level_text == "低":
        return 2.0
    return 0.0


def _average_score(*values: float) -> float:
    scores = [float(value) for value in values if value]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 1)


def _row_publish_datetime(row: dict[str, Any]) -> datetime | None:
    value = row.get("create_time")
    try:
        timestamp = int(float(value or 0))
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp)


def next_schedule_time(config: AppConfig) -> str:
    times = [str(item) for item in (config.get("schedule.times", []) or [])]
    if not times:
        return "未配置"
    now = datetime.now()
    candidates: list[datetime] = []
    for item in times:
        try:
            hour, minute = [int(part) for part in item.split(":", 1)]
        except ValueError:
            continue
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        candidates.append(candidate)
    if not candidates:
        return "时间格式错误"
    return min(candidates).strftime("%m-%d %H:%M")
