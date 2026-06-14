from __future__ import annotations

from typing import Any

from kenradar.core.config import AppConfig


def create_database(config: AppConfig) -> Any:
    if config.database_type == "postgresql":
        from kenradar.storage.pg_database import Database as PostgreSQLDatabase

        return PostgreSQLDatabase(config.database_url)
    raise RuntimeError(
        "KenRadar 现已要求 PostgreSQL。请在环境变量 DATABASE_URL 或 app.database_url 中提供有效的 postgresql:// 连接串。"
    )
