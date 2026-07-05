from __future__ import annotations

from scripts.legacy.migrate_sqlite_to_pg import main, migrate, write_report

__all__ = ["main", "migrate", "write_report"]


if __name__ == "__main__":
    main()
