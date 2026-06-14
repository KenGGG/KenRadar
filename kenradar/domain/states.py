from __future__ import annotations

from enum import StrEnum


class TaskRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


TASK_RUN_TERMINAL_STATUSES = {
    TaskRunStatus.SUCCESS,
    TaskRunStatus.FAILED,
    TaskRunStatus.CANCELLED,
}
