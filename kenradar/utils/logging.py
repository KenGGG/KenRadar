from __future__ import annotations

import logging
import logging.handlers
import os
from contextvars import ContextVar
from pathlib import Path

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(cid: str | None) -> None:
    """设置当前上下文的 correlation ID"""
    if cid:
        _correlation_id.set(cid)


def get_correlation_id() -> str | None:
    """获取当前上下文的 correlation ID"""
    return _correlation_id.get()


class CorrelationFormatter(logging.Formatter):
    """在日志消息前注入 correlation ID（如已设置）"""

    def format(self, record: logging.LogRecord) -> str:
        cid = get_correlation_id()
        if cid:
            record.msg = f"[correlation={cid}] {record.msg}"
        return super().format(record)


def configure_logging(level: str | None = None) -> None:
    resolved = (level or os.getenv("KENRADAR_LOG_LEVEL") or "INFO").upper()
    root = logging.getLogger()
    root.setLevel(getattr(logging, resolved, logging.INFO))

    formatter = CorrelationFormatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # When KENRADAR_LOG_FILE is set, own the log file with rotation so it does
    # not grow without bound. Otherwise fall back to stderr/stdout streaming
    # (e.g. when a supervisor already redirects output).
    log_file = os.getenv("KENRADAR_LOG_FILE")
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=int(os.getenv("KENRADAR_LOG_MAX_BYTES", "10_000_000")),
            backupCount=int(os.getenv("KENRADAR_LOG_BACKUPS", "5")),
            encoding="utf-8",
        )
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
