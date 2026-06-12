from __future__ import annotations

import warnings
from typing import Any

from kenradar.core.config import AppConfig


def create_database(config: AppConfig) -> Any:
    if config.database_type == "postgresql":
        from kenradar.storage.pg_database import Database as PostgreSQLDatabase

        return PostgreSQLDatabase(config.database_url)
    warnings.warn(
        "SQLite database backend is deprecated. Please use database_url in config.yaml to configure PostgreSQL.",
        DeprecationWarning,
        stacklevel=2,
    )
    from kenradar.storage.database import Database as SQLiteDatabase

    return SQLiteDatabase(config.database_path)