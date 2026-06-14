from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from typing import Any

from kenradar.core.config import AppConfig, load_config
from kenradar.core.workflow import Workflow
from kenradar.domain import TaskRunStatus, TASK_RUN_TERMINAL_STATUSES
from kenradar.jobs.handlers import execute_task_run
from kenradar.notification.alert import AlertManager
from kenradar.storage import create_database

logger = logging.getLogger(__name__)


class TaskWorker:
    def __init__(self, config_path: str, worker_name: str = "", poll_seconds: float = 2.0):
        self.config_path = str(config_path)
        self.worker_name = worker_name or f"{socket.gethostname()}:{threading.get_native_id()}"
        self.poll_seconds = max(0.2, float(poll_seconds))
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        logger.info("任务 worker 已启动: worker=%s", self.worker_name)
        while not self._stop.is_set():
            try:
                if not self.run_once():
                    self._stop.wait(self.poll_seconds)
            except Exception:
                logger.exception("任务 worker 循环异常: worker=%s", self.worker_name)
                self._stop.wait(min(5.0, self.poll_seconds * 2))

    def run_once(self) -> bool:
        config = load_config(self.config_path)
        database = create_database(config)
        record = database.claim_next_task_run(worker_name=self.worker_name, lease_seconds=300)
        if not record:
            return False
        self._execute(config, database, record)
        return True

    def _execute(self, config: AppConfig, database: Any, record: dict[str, Any]) -> None:
        run_id = int(record.get("id") or 0)
        task_type = str(record.get("task_type") or "")
        payload = record.get("payload_json") or {}
        message = str(record.get("message") or task_type)
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(30.0):
                database.heartbeat_task_run(run_id, lease_seconds=300)

        def progress(current: int, total: int, content_id: str, stage: str, progress_message: str) -> None:
            database.heartbeat_task_run(
                run_id,
                lease_seconds=300,
                progress={
                    "current": current,
                    "total": total,
                    "aweme_id": content_id,
                    "stage": stage,
                    "message": progress_message,
                },
            )

        thread = threading.Thread(target=heartbeat, daemon=True, name=f"task-heartbeat-{run_id}")
        thread.start()
        attempt_id = database.start_task_attempt(run_id, self.worker_name)
        try:
            if database.is_task_cancel_requested(run_id):
                database.mark_task_cancelled(run_id, "任务在执行前已取消")
                database.finish_task_attempt(attempt_id, TaskRunStatus.CANCELLED.value, "任务在执行前已取消")
                return
            stats = asyncio.run(
                execute_task_run(
                    Workflow(config),
                    task_type,
                    payload,
                    progress_callback=progress,
                )
            )
            if database.is_task_cancel_requested(run_id):
                database.mark_task_cancelled(run_id, "任务执行期间收到取消请求")
                database.finish_task_attempt(attempt_id, TaskRunStatus.CANCELLED.value, "任务执行期间收到取消请求")
                return
            database.complete_task_run(run_id, stats=stats)
            database.finish_task_attempt(attempt_id, TaskRunStatus.SUCCESS.value)
            logger.info("任务完成: run_id=%s task_type=%s", run_id, task_type)
        except Exception as exc:
            retrying = database.fail_task_run(run_id, str(exc))
            database.finish_task_attempt(attempt_id, TaskRunStatus.RETRY_WAIT.value if retrying else TaskRunStatus.FAILED.value, str(exc))
            if not retrying:
                try:
                    AlertManager(config, database).error(
                        "task_worker",
                        str(exc),
                        title=message,
                        context={"task_type": task_type, "task_run_id": run_id},
                    )
                except Exception:
                    logger.exception("任务失败告警写入失败: run_id=%s", run_id)
            logger.exception("任务执行失败: run_id=%s task_type=%s retrying=%s", run_id, task_type, retrying)
        finally:
            heartbeat_stop.set()
            thread.join(timeout=1.0)


def wait_for_task(config_path: str, run_id: int, poll_seconds: float = 2.0) -> dict[str, Any]:
    while True:
        database = create_database(load_config(config_path))
        row = database.get_task_run(run_id)
        if not row:
            raise ValueError(f"未找到任务: {run_id}")
        if str(row.get("status") or "") in {s.value for s in TASK_RUN_TERMINAL_STATUSES}:
            return row
        time.sleep(max(0.2, poll_seconds))
