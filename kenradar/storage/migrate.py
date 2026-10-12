from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from kenradar.core.config import load_config


def alembic_config(config_path: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.attributes["config_path"] = str(Path(config_path).resolve())
    if load_config(config_path).database_type == "sqlite":
        cfg.set_main_option("script_location", str(Path(__file__).with_name("sqlite_migrations")))
    return cfg


def upgrade_database(config_path: str) -> None:
    app = load_config(config_path)
    if app.database_type != "sqlite":
        raise RuntimeError("PG 历史迁移已冻结；正常运行仅初始化 SQLite")
    from kenradar.storage.sqlite_engine import database_path, sqlite_engine
    path = database_path(app.database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = sqlite_engine(app.database_url)
    try:
        # WAL is established outside a transaction, only during explicit init.
        with engine.connect() as connection:
            dbapi = connection.connection.driver_connection
            mode = dbapi.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if mode != "wal":
                raise RuntimeError("SQLite 无法启用 WAL")
            with connection.begin():
                cfg = alembic_config(config_path)
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def schema_status(config_path: str) -> dict[str, str | bool]:
    cfg = alembic_config(config_path)
    app_config = load_config(config_path)
    # This powers readiness/dependency health.  A missing database must be
    # reported as unavailable instead of holding the HTTP request for libpq's
    # much longer default connection timeout.
    if app_config.database_type != "sqlite":
        raise RuntimeError("PG 不是当前运行后端")
    from kenradar.storage.sqlite_engine import database_path, sqlite_engine
    path = database_path(app_config.database_url)
    if not path.is_file():
        return {"current": "", "head": "s0001_v2", "up_to_date": False}
    engine = sqlite_engine(app_config.database_url)
    try:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    return {"current": current or "", "head": head or "", "up_to_date": current == head}
