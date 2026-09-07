from __future__ import annotations

import logging
import threading
import time
from copy import deepcopy
from typing import Any

from kenradar.core.config import load_config
from kenradar.storage import create_database

logger = logging.getLogger(__name__)

_STATE: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",
    "message": "空闲",
    "stats": None,
    "progress": None,
    "queue": [],
}
_CONFIG_PATH = ""
_SYNC_STARTED = False


def configure(config_path: str) -> None:
    global _CONFIG_PATH
    _CONFIG_PATH = str(config_path)


def current() -> dict[str, Any]:
    return deepcopy(_STATE)


def public_queue(config_path: str | None = None) -> list[dict[str, Any]]:
    path = str(config_path or _CONFIG_PATH or "")
    if not path:
        return []
    try:
        config = load_config(path)
        rows = create_database(config).list_queued_task_runs(limit=20)
    except Exception:
        logger.exception("读取持久任务队列失败")
        return []
    return [
        {
            "position": index,
            "task_id": str(row.get("task_type") or ""),
            "message": str(row.get("message") or ""),
            "queued_at": str(row.get("created_at") or ""),
            "requested_by": str(row.get("requested_by") or ""),
            "run_id": int(row.get("id") or 0),
            "queue_total": int(row.get("queue_total") or 0),
        }
        for index, row in enumerate(rows, start=1)
    ]


def sync(config_path: str | None = None) -> dict[str, Any]:
    path = str(config_path or _CONFIG_PATH or "")
    if not path:
        return current()
    try:
        config = load_config(path)
        database = create_database(config)
        active = database.get_latest_active_task_run()
        latest = active or database.get_latest_task_run()
        queue = public_queue(path)
        if not latest:
            _STATE.update(
                {
                    "running": False,
                    "started_at": None,
                    "finished_at": None,
                    "status": "idle",
                    "message": "空闲",
                    "stats": None,
                    "progress": None,
                    "queue": queue,
                }
            )
            return current()
        progress = latest.get("progress_json") or {}
        stats = latest.get("stats_json") or {}
        _STATE.update(
            {
                "running": str(latest.get("status") or "") == "running",
                "started_at": str(latest.get("started_at") or "") or None,
                "finished_at": str(latest.get("finished_at") or "") or None,
                "status": str(latest.get("task_type") or latest.get("status") or "idle"),
                "message": str(latest.get("message") or "空闲"),
                "stats": stats if isinstance(stats, dict) and stats else None,
                "progress": progress if isinstance(progress, dict) and progress else None,
                "queue": queue,
                "last_error": str(latest.get("last_error") or ""),
                "requested_by": str(latest.get("requested_by") or ""),
                "run_id": int(latest.get("id") or 0),
            }
        )
    except Exception:
        logger.exception("同步持久任务状态失败")
    return current()


def start_sync(config_path: str) -> None:
    global _SYNC_STARTED
    configure(config_path)
    if _SYNC_STARTED:
        return

    def sync_loop() -> None:
        while True:
            sync(config_path)
            time.sleep(2.5)

    sync(config_path)
    threading.Thread(target=sync_loop, daemon=True, name="kenradar-task-state-sync").start()
    _SYNC_STARTED = True
    logger.info("持久任务状态同步器已启动")


def enqueue(config_path: str, task_type: str, payload: dict[str, Any], message: str, requested_by: str = "web") -> dict[str, Any]:
    config = load_config(config_path)
    database = create_database(config)
    row = database.enqueue_task_run(task_type=task_type, payload=payload, message=message, requested_by=requested_by)
    state = sync(config_path)
    position = 1
    for index, item in enumerate(state.get("queue") or [], start=1):
        if int(item.get("run_id") or 0) == int(row.get("id") or 0):
            position = index
            break
    return {"run_id": int(row.get("id") or 0), "queue_position": position}
