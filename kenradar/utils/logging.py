from __future__ import annotations

import logging
import os
from contextvars import ContextVar

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
    handler = logging.StreamHandler()
    handler.setFormatter(
        CorrelationFormatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(getattr(logging, resolved, logging.INFO))
    root.addHandler(handler)
