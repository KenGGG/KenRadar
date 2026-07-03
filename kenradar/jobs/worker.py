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
from kenradar.utils.logging import set_correlation_id

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
        set_correlation_id(f"task_{run_id}")
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
            timeout_seconds = _task_timeout_seconds(config, task_type)
            task = execute_task_run(
                Workflow(config),
                task_type,
                payload,
                progress_callback=progress,
            )
            if timeout_seconds > 0:
                task = asyncio.wait_for(task, timeout=timeout_seconds)
            stats = asyncio.run(
                task
            )
            if database.is_task_cancel_requested(run_id):
                database.mark_task_cancelled(run_id, "任务执行期间收到取消请求")
                database.finish_task_attempt(attempt_id, TaskRunStatus.CANCELLED.value, "任务执行期间收到取消请求")
                return
            database.complete_task_run(run_id, stats=stats)
            database.finish_task_attempt(attempt_id, TaskRunStatus.SUCCESS.value)
            logger.info("任务完成: run_id=%s task_type=%s", run_id, task_type)
        except asyncio.TimeoutError:
            timeout_seconds = _task_timeout_seconds(config, task_type)
            message = f"任务运行超过上限 {timeout_seconds}s，已自动取消以释放队列"
            database.request_task_cancel(run_id, message)
            database.fail_task_run(run_id, message)
            database.finish_task_attempt(attempt_id, TaskRunStatus.CANCELLED.value, message)
            try:
                AlertManager(config, database).error(
                    "task_worker",
                    message,
                    title=message,
                    context={"task_type": task_type, "task_run_id": run_id},
                )
            except Exception:
                logger.exception("任务超时告警写入失败: run_id=%s", run_id)
            logger.error("任务超时取消: run_id=%s task_type=%s timeout=%ss", run_id, task_type, timeout_seconds)
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


def _task_timeout_seconds(config: AppConfig, task_type: str) -> int:
    task_type = str(task_type or "").strip()
    specific = config.get(f"task_run.max_runtime_hours.{task_type}", None)
    configured = specific if specific is not None else config.get("task_run.max_runtime_hours", None)
    if configured is None:
        configured = 12 if task_type in {"research_blogger", "restart_research_job", "refresh_old_notes"} else 3
    try:
        hours = float(configured or 0)
    except (TypeError, ValueError):
        hours = 0.0
    return max(0, int(hours * 3600))


def wait_for_task(config_path: str, run_id: int, poll_seconds: float = 2.0) -> dict[str, Any]:
    while True:
        database = create_database(load_config(config_path))
        row = database.get_task_run(run_id)
        if not row:
            raise ValueError(f"未找到任务: {run_id}")
        if str(row.get("status") or "") in {s.value for s in TASK_RUN_TERMINAL_STATUSES}:
            return row
        time.sleep(max(0.2, poll_seconds))


class StepWorker:
    """处理 task_step（内容级 stage claim）的 worker"""

    STAGE_HANDLERS: dict[str, str] = {
        "fetch": "kenradar.processing.fetch.FetchHandler",
        "download": "kenradar.processing.download.DownloadHandler",
        "transcribe": "kenradar.processing.transcribe.TranscribeHandler",
    }

    def __init__(self, config_path: str, worker_name: str = "", poll_seconds: float = 2.0):
        self.config_path = str(config_path)
        self.worker_name = worker_name or f"step:{socket.gethostname()}:{threading.get_native_id()}"
        self.poll_seconds = max(0.2, float(poll_seconds))
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        logger.info("step worker 已启动: worker=%s", self.worker_name)
        while not self._stop.is_set():
            try:
                if not self.run_once():
                    self._stop.wait(self.poll_seconds)
            except Exception:
                logger.exception("step worker 循环异常: worker=%s", self.worker_name)
                self._stop.wait(min(5.0, self.poll_seconds * 2))

    def run_once(self) -> bool:
        config = load_config(self.config_path)
        database = create_database(config)
        step = database.claim_next_task_step(
            stages=tuple(self.STAGE_HANDLERS.keys()),
            worker_name=self.worker_name,
            lease_seconds=300,
        )
        if not step:
            return False
        self._execute_step(config, database, step)
        return True

    def _execute_step(self, config: AppConfig, database: Any, step: dict[str, Any]) -> None:
        step_id = int(step["id"])
        stage = str(step["stage"])
        content_item_id = step.get("content_item_id")
        set_correlation_id(f"step_{step_id}_{stage}")

        handler_cls = self._resolve_handler(stage)
        if handler_cls is None:
            database.fail_task_step(step_id, f"未知 stage: {stage}")
            return

        try:
            workflow = Workflow(config)
            handler = handler_cls(workflow, database, config)
            ctx = StageContext(
                task_run_id=step.get("task_run_id"),
                content_item_id=content_item_id,
                payload=step.get("output_ref") or {},
                config=config,
            )
            result = asyncio.run(handler.execute(ctx))
            database.complete_task_step(step_id, output_ref=result)
            database.insert_state_transition(
                "task_step", str(step_id), "running", "success",
                reason=stage, actor=self.worker_name,
            )
            logger.info("step 完成: step_id=%s stage=%s result=%s", step_id, stage, result)
        except Exception as exc:
            retrying = database.fail_task_step(step_id, str(exc))
            final_status = "retry_wait" if retrying else "failed"
            database.insert_state_transition(
                "task_step", str(step_id), "running", final_status,
                reason=str(exc), actor=self.worker_name,
            )
            if not retrying:
                alert = AlertManager(config, database)
                alert.error(f"step_{stage}", str(exc), context={"step_id": step_id})
            logger.exception("step 失败: step_id=%s stage=%s retrying=%s", step_id, stage, retrying)

    def _resolve_handler(self, stage: str) -> Any | None:
        import importlib
        dotted = self.STAGE_HANDLERS.get(stage)
        if not dotted:
            return None
        try:
            module_path, _, class_name = dotted.rpartition(".")
            module = importlib.import_module(module_path)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            logger.error("解析 handler 失败: stage=%s path=%s error=%s", stage, dotted, exc)
            return None
