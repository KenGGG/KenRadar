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
    if config.database_type != "postgresql":
        raise RuntimeError(
            "KenRadar 现已要求 PostgreSQL。请在环境变量 DATABASE_URL 或 app.database_url 中提供有效的 postgresql:// 连接串。"
        )
    url = config.database_url
    with _DATABASE_CACHE_LOCK:
        db = _DATABASE_CACHE.get(url)
        if db is None:
            from kenradar.storage.pg_database import Database as PostgreSQLDatabase

            db = PostgreSQLDatabase(url)
            _DATABASE_CACHE[url] = db
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
