from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

from kenradar.core.config import load_config


config = context.config
app_config = load_config(config.attributes.get("config_path", "config/config.yaml"))
config.set_main_option("sqlalchemy.url", app_config.database_url.replace("%", "%%"))


def run_migrations_offline() -> None:
    context.configure(
        url=app_config.database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(app_config.database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
