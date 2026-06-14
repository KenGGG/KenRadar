from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kenradar.core.config import AppConfig, load_config
from kenradar.core.workflow import Workflow
from kenradar.storage import create_database

logger = logging.getLogger(__name__)


async def run_forever(config: AppConfig) -> None:
    await _run_loop(lambda: config, use_persistent_queue=False)


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
        times = set(config.get("schedule.times", ["09:00", "21:00"]) or [])
        now = datetime.now()
        grace_minutes = int(config.get("schedule.grace_minutes", 10) or 0)
        due_time = _due_time(now, times, grace_minutes)
        key = f"{now.strftime('%Y-%m-%d')} {due_time}" if due_time else ""
        if len(seen) > max(20, len(times) * 3):
            today = now.strftime("%Y-%m-%d")
            seen = {item for item in seen if item.startswith(today)}
        if due_time and key not in seen:
            seen.add(key)
            await _trigger_due_run(
                config,
                due_time,
                grace_minutes=grace_minutes,
                task_lock=task_lock,
                use_persistent_queue=use_persistent_queue,
            )
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
        if active:
            logger.warning(
                "定时任务暂缓: due_time=%s，已有后台任务占用队列 status=%s task_type=%s run_id=%s",
                due_time,
                active.get("status"),
                active.get("task_type"),
                active.get("id"),
            )
            return "deferred"
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
            logger.warning("定时任务暂缓: due_time=%s，已有 Web 手动任务或其他定时任务正在运行", due_time)
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
