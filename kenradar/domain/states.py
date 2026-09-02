from __future__ import annotations

from kenradar.utils.compat import StrEnum


class TaskRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


TASK_RUN_TERMINAL_STATUSES = frozenset({
    TaskRunStatus.SUCCESS,
    TaskRunStatus.FAILED,
    TaskRunStatus.CANCELLED,
})

# A paused task keeps its history and checkpoint; it is waiting for the operator.
TASK_RUN_RESUMABLE_STATUSES = frozenset({TaskRunStatus.PAUSED})


class TaskAttemptStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    ABANDONED = "abandoned"


# Errors that will never succeed on retry without an external change.
PERMANENT_ERROR_CODES = frozenset({
    "AUTH_REQUIRED",
    "CONTENT_PRIVATE",
    "CONTENT_DELETED",
    "REGION_RESTRICTED",
    "AI_SCHEMA_INVALID",
    "NOTE_VALIDATION_FAILED",
})

# Transient errors that are safe to retry with bounded exponential backoff.
RETRYABLE_ERROR_CODES = frozenset({
    "RATE_LIMITED",
    "SOURCE_PARSE_CHANGED",
    "METADATA_FAILED",
    "DOWNLOAD_FAILED",
    "MEDIA_INVALID",
    "TRANSCRIPT_EMPTY",
    "TRANSCRIPT_LOW_QUALITY",
    "AI_PROVIDER_FAILED",
    "GITHUB_BUILD_FAILED",
    "GITHUB_PUSH_FAILED",
    "FEISHU_SEND_FAILED",
    "WORKER_LEASE_EXPIRED",
})

MAX_RETRY_DELAY_SECONDS = 1800


def normalize_error_code(value: Any) -> str:
    """Return a known error code or an empty string for unclassified errors."""
    code = str(value or "").strip().upper()
    if code in PERMANENT_ERROR_CODES or code in RETRYABLE_ERROR_CODES:
        return code
    return ""


def is_permanent_error(error_code: Any) -> bool:
    """Permanent errors must not be retried without an external change."""
    return str(error_code or "").strip().upper() in PERMANENT_ERROR_CODES


def retry_delay_seconds(attempt: int) -> int:
    """Bounded exponential backoff for classified transient errors."""
    try:
        current = max(1, int(attempt))
    except (TypeError, ValueError):
        current = 1
    return min(MAX_RETRY_DELAY_SECONDS, 30 * 2 ** (current - 1))


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
