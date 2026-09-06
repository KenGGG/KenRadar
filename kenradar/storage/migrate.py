from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from kenradar.core.config import load_config


def alembic_config(config_path: str) -> Config:
    root = Path(config_path).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.attributes["config_path"] = str(Path(config_path).resolve())
    return cfg


def upgrade_database(config_path: str) -> None:
    command.upgrade(alembic_config(config_path), "head")


def schema_status(config_path: str) -> dict[str, str | bool]:
    cfg = alembic_config(config_path)
    app_config = load_config(config_path)
    # This powers readiness/dependency health.  A missing database must be
    # reported as unavailable instead of holding the HTTP request for libpq's
    # much longer default connection timeout.
    engine = create_engine(app_config.database_url, connect_args={"connect_timeout": 3})
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    return {"current": current or "", "head": head or "", "up_to_date": current == head}
