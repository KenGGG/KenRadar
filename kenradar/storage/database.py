from __future__ import annotations

import warnings

warnings.warn(
    "kenradar.storage.database is legacy-only. Use PostgreSQL via database_url in config.yaml.",
    DeprecationWarning,
    stacklevel=2,
)

from scripts.legacy.sqlite_database import Database

__all__ = ["Database"]
