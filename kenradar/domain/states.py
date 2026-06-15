from __future__ import annotations

from kenradar.utils.compat import StrEnum


class TaskRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


TASK_RUN_TERMINAL_STATUSES = frozenset({
    TaskRunStatus.SUCCESS,
    TaskRunStatus.FAILED,
    TaskRunStatus.CANCELLED,
})


class ResearchJobStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TRANSCRIBE_ONLY_COMPLETED = "transcribe_only_completed"
    TRANSCRIBE_ONLY_PARTIAL_FAILED = "transcribe_only_partial_failed"


class ResearchJobItemStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED_WAITING_SUMMARY = "transcribed_waiting_summary"
    SUMMARIZING = "summarizing"
    NOTING = "noting"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


RESEARCH_JOB_ITEM_ACTIVE_STATUSES = frozenset({
    ResearchJobItemStatus.RUNNING,
    ResearchJobItemStatus.DOWNLOADING,
    ResearchJobItemStatus.DOWNLOADED,
    ResearchJobItemStatus.TRANSCRIBING,
    ResearchJobItemStatus.TRANSCRIBED_WAITING_SUMMARY,
    ResearchJobItemStatus.SUMMARIZING,
    ResearchJobItemStatus.NOTING,
})

RESEARCH_JOB_ITEM_TERMINAL_STATUSES = frozenset({
    ResearchJobItemStatus.SUCCESS,
    ResearchJobItemStatus.FAILED,
    ResearchJobItemStatus.CANCELLED,
    ResearchJobItemStatus.SKIPPED,
})


class DownloadStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DONE = "done"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class TranscriptStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"
    SKIPPED = "skipped"


class AlertLevel(StrEnum):
    DEGRADED = "degraded"
    WARNING = "warning"
    ERROR = "error"
    RECOVERED = "recovered"
    CRITICAL = "critical"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class ArtifactStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    ARCHIVED = "archived"
