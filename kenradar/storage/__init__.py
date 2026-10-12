from __future__ import annotations

import threading
from typing import Any

from kenradar.core.config import AppConfig

# Process-wide pool cache keyed by database URL so that repeated create_database
# calls (e.g. one per Web request) share a single ConnectionPool instead of
# opening an unbounded number of pools/connections.
_DATABASE_CACHE: dict[str, Any] = {}
_DATABASE_CACHE_LOCK = threading.Lock()


def create_database(config: AppConfig) -> Any:
    if config.database_type != "sqlite":
        raise RuntimeError(
            "本轮正常运行仅支持 SQLite；旧 PostgreSQL 请使用只读迁移工具。生产切换需单独授权。"
        )
    url = config.database_url
    with _DATABASE_CACHE_LOCK:
        db = _DATABASE_CACHE.get(url)
        if db is None:
            from kenradar.storage.sqlite_database import Database

            db = Database(url)
            db.initialize()
            _DATABASE_CACHE[url] = db
        # Source connectors need the active AppConfig (especially local cookies).
        # The pooled connection itself remains keyed only by database URL.
        db.config = config
        return db


def reset_database_cache() -> None:
    """Drop cached Database instances (used by tests / config reload)."""
    with _DATABASE_CACHE_LOCK:
        for db in _DATABASE_CACHE.values():
            try:
                db.close()
            except Exception:
                pass
        _DATABASE_CACHE.clear()
