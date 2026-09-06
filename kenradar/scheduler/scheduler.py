from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any

from kenradar.core.config import AppConfig, load_config
from kenradar.core.workflow import Workflow
from kenradar.storage import create_database

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - zoneinfo is stdlib on py3.9+
    ZoneInfo = None  # type: ignore[assignment]


def _config_timezone(config: AppConfig) -> Any:
    """Resolve the configured app.timezone, returning None for naive local time."""
    tz_name = str(config.get("app.timezone") or "").strip()
    if tz_name and ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            logger.warning("无效时区配置 app.timezone=%s，回退本地时区", tz_name)
    return None


def _now_in_tz(config: AppConfig) -> datetime:
    tz = _config_timezone(config)
    return datetime.now(tz) if tz is not None else datetime.now()


async def run_forever(config: AppConfig) -> None:
    # A process-wide lock so the direct (non-persistent) run_once path cannot
    # overlap with itself; the Web-embedded scheduler passes its own shared lock.
    task_lock = threading.Lock()
    await _run_loop(lambda: config, task_lock=task_lock, use_persistent_queue=False)


async def run_forever_from_path(
    config_path: str | Path,
    task_lock: threading.Lock | None = None,
    use_persistent_queue: bool = True,
) -> None:
    await _run_loop(lambda: load_config(config_path), task_lock=task_lock, use_persistent_queue=use_persistent_queue)


async def _run_loop(
    load_current_config: Any,
    task_lock: threading.Lock | None = None,
    use_persistent_queue: bool = False,
) -> None:
    config = load_current_config()
    times = set(config.get("schedule.times", ["09:00", "21:00"]) or [])
    if not times:
        raise ValueError("schedule.times 不能为空")

    seen: set[str] = set()
    pending: dict[str, str] = {}
    last_source_scan: datetime | None = None
    logger.info(
        "调度器已启动: times=%s enabled=%s persistent_queue=%s",
        sorted(times),
        config.get("schedule.enabled", True),
        use_persistent_queue,
    )
    while True:
        config = load_current_config()
        if not config.get("schedule.enabled", True):
            await asyncio.sleep(30)
            continue
        # The subscription radar polls independently of the fixed daily times:
        # each subscription carries its own next_check_at.
        last_source_scan = await _maybe_scan_sources(config, last_source_scan)
        times = set(config.get("schedule.times", ["09:00", "21:00"]) or [])
        now = _now_in_tz(config)
        grace_minutes = int(config.get("schedule.grace_minutes", 10) or 0)
        due_time = _due_time(now, times, grace_minutes)
        key = f"{now.strftime('%Y-%m-%d')} {due_time}" if due_time else ""
        today = now.strftime("%Y-%m-%d")
        if len(seen) > max(20, len(times) * 3):
            seen = {item for item in seen if item.startswith(today)}
        if pending:
            pending = {item_key: item_due for item_key, item_due in pending.items() if item_key.startswith(today)}
        for pending_key, pending_due_time in sorted(pending.items()):
            if pending_key in seen:
                pending.pop(pending_key, None)
                continue
            result = await _trigger_due_run(
                config,
                pending_due_time,
                grace_minutes=grace_minutes,
                task_lock=task_lock,
                use_persistent_queue=use_persistent_queue,
            )
            if result == "deferred":
                break
            seen.add(pending_key)
            pending.pop(pending_key, None)
            break
        if due_time and key not in seen and key not in pending:
            result = await _trigger_due_run(
                config,
                due_time,
                grace_minutes=grace_minutes,
                task_lock=task_lock,
                use_persistent_queue=use_persistent_queue,
            )
            if result == "deferred":
                pending[key] = due_time
                logger.warning("定时任务已进入待重试队列: due_time=%s key=%s", due_time, key)
            else:
                seen.add(key)
        await asyncio.sleep(30)


async def _trigger_due_run(
    config: AppConfig,
    due_time: str,
    *,
    grace_minutes: int,
    task_lock: threading.Lock | None = None,
    use_persistent_queue: bool = False,
) -> str:
    if use_persistent_queue:
        database = create_database(config)
        active = database.get_latest_active_task_run()
        if active and str(active.get("status") or "") == "running":
            if _is_preemptable_for_scheduler(config, active):
                resume_run = _preempt_research_task_for_scheduler(database, active, due_time)
                logger.warning(
                    "定时任务已抢占研究任务: due_time=%s active_run_id=%s resume_run_id=%s",
                    due_time,
                    active.get("id"),
                    (resume_run or {}).get("id"),
                )
            else:
                logger.warning(
                    "定时任务暂缓: due_time=%s，已有后台任务占用队列 status=%s task_type=%s run_id=%s",
                    due_time,
                    active.get("status"),
                    active.get("task_type"),
                    active.get("id"),
                )
                return "deferred"
        elif active:
            logger.info(
                "定时任务将插队到未开始任务前: due_time=%s active_status=%s active_task_type=%s active_run_id=%s",
                due_time,
                active.get("status"),
                active.get("task_type"),
                active.get("id"),
            )
        row = database.enqueue_task_run(
            task_type="run_once",
            payload={"push": True, "trigger": "scheduler", "due_time": due_time},
            message=f"定时任务触发：{due_time}",
            requested_by="scheduler",
            priority=100,
            idempotency_key=f"scheduler:run_once:{datetime.now().strftime('%Y-%m-%d')}:{due_time}",
            max_attempts=3,
        )
        logger.info(
            "定时任务已入持久队列: due_time=%s grace_minutes=%s run_id=%s",
            due_time,
            grace_minutes,
            row.get("id"),
        )
        return "queued"

    lock_acquired = False
    if task_lock is not None:
        lock_acquired = task_lock.acquire(blocking=False)
        if not lock_acquired:
            logger.warning(
                "定时任务暂缓: due_time=%s，已有 Web 手动任务或其他定时任务正在运行",
                due_time,
            )
            return "deferred"
    try:
        logger.info("触发定时任务: due_time=%s grace_minutes=%s", due_time, grace_minutes)
        stats = await Workflow(config).run_once(push=True)
        logger.info("定时任务完成: %s", stats)
        return "completed"
    except Exception:
        logger.exception("定时任务执行失败")
        return "failed"
    finally:
        if task_lock is not None and lock_acquired:
            task_lock.release()


async def _maybe_scan_sources(
    config: AppConfig, last_scan: datetime | None
) -> datetime | None:
    """Run the subscription radar at most once per configured interval."""
    if not config.get("schedule.source_radar_enabled", True):
        return last_scan
    interval = int(config.get("schedule.source_scan_interval_minutes", 15) or 15)
    now = _now_in_tz(config)
    if last_scan is not None and now - last_scan < timedelta(minutes=max(1, interval)):
        return last_scan
    try:
        stats = await scan_due_sources(config)
        if stats.get("scanned") or stats.get("failed"):
            logger.info(
                "订阅雷达扫描完成: scanned=%s discovered=%s failed=%s skipped=%s",
                stats.get("scanned"), stats.get("discovered"),
                stats.get("failed"), stats.get("skipped"),
            )
    except Exception:
        logger.exception("订阅雷达扫描失败")
    return now


async def scan_due_sources(config: AppConfig, limit: int = 50) -> dict[str, Any]:
    """Scan subscriptions whose next_check_at has passed (V2 subscription radar)."""
    from kenradar.core.source_monitor import SourceMonitorService

    database = create_database(config)
    try:
        stats = await SourceMonitorService(database).scan_due_subscriptions(limit=limit)
    finally:
        database.close()
    return stats


def _is_preemptable_for_scheduler(config: AppConfig, active: dict[str, Any]) -> bool:
    config_get = getattr(config, "get", lambda _key, default=None: default)
    if not bool(config_get("schedule.preempt_research.enabled", True)):
        return False
    task_type = str(active.get("task_type") or "")
    return task_type in {"research_blogger", "restart_research_job", "retry_research_failed"}


def _preempt_research_task_for_scheduler(database: Any, active: dict[str, Any], due_time: str) -> dict[str, Any] | None:
    reason = f"定时任务 {due_time} 优先执行，临时中断研究任务，稍后自动接续"
    active_run_id = int(active.get("id") or 0)
    if active_run_id > 0:
        database.request_task_cancel(active_run_id, reason)
    job_id = 0
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM research_job
            WHERE status = 'running'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if row:
            job_id = int(row["id"] or 0)
            conn.execute(
                """
                UPDATE research_job
                SET status='cancelled',
                    finished_at=NOW(),
                    last_error=%s,
                    updated_at=NOW()
                WHERE id = %s
                """,
                (reason, job_id),
            )
            conn.execute(
                """
                UPDATE research_job_item
                SET status='cancelled',
                    error_message=%s,
                    updated_at=NOW()
                WHERE job_id = %s
                  AND status IN ('pending', 'running', 'downloading', 'downloaded', 'transcribing',
                                 'transcribed_waiting_summary', 'summarizing', 'noting')
                """,
                (reason, job_id),
            )
    if job_id <= 0:
        return None
    return database.enqueue_task_run(
        task_type="restart_research_job",
        payload={"job_id": job_id, "trigger": "scheduler_preempt", "due_time": due_time},
        message=f"定时任务后接续研究任务 #{job_id}",
        requested_by="scheduler",
        priority=20,
        idempotency_key=f"scheduler:resume_research:{job_id}",
        max_attempts=3,
    )


def _due_time(now: datetime, times: set[str], grace_minutes: int) -> str | None:
    current = now.strftime("%H:%M")
    if current in times:
        return current
    if grace_minutes <= 0:
        return None
    for item in times:
        try:
            hour, minute = [int(part) for part in item.split(":", 1)]
        except ValueError:
            continue
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= now <= scheduled + timedelta(minutes=grace_minutes):
            return item
    return None
