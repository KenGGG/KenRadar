from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kenradar.core.config import AppConfig, load_config
from kenradar.core.workflow import Workflow

logger = logging.getLogger(__name__)


async def run_forever(config: AppConfig) -> None:
    await _run_loop(lambda: config)


async def run_forever_from_path(config_path: str | Path, task_lock: threading.Lock | None = None) -> None:
    await _run_loop(lambda: load_config(config_path), task_lock=task_lock)


async def _run_loop(load_current_config: Any, task_lock: threading.Lock | None = None) -> None:
    config = load_current_config()
    times = set(config.get("schedule.times", ["09:00", "21:00"]) or [])
    if not times:
        raise ValueError("schedule.times 不能为空")

    seen: set[str] = set()
    logger.info("调度器已启动: times=%s enabled=%s", sorted(times), config.get("schedule.enabled", True))
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
            lock_acquired = False
            if task_lock is not None:
                lock_acquired = task_lock.acquire(blocking=False)
                if not lock_acquired:
                    logger.warning("定时任务暂缓: due_time=%s，已有 Web 手动任务或其他定时任务正在运行", due_time)
                    await asyncio.sleep(30)
                    continue
            seen.add(key)
            try:
                logger.info("触发定时任务: due_time=%s grace_minutes=%s", due_time, grace_minutes)
                stats = await Workflow(config).run_once(push=True)
                logger.info("定时任务完成: %s", stats)
            except Exception:
                logger.exception("定时任务执行失败")
            finally:
                if task_lock is not None and lock_acquired:
                    task_lock.release()
        await asyncio.sleep(30)


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
