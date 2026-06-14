"""KenRadar PostgreSQL baseline.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-14
"""
from __future__ import annotations

from alembic import op

from kenradar.storage.pg_database import SCHEMA_SQL

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SCHEMA_SQL)
    op.execute("DROP INDEX IF EXISTS idx_task_run_status_created")
    op.execute(
        """
        CREATE INDEX idx_task_run_status_created
        ON task_run(status, priority DESC, available_at, created_at, id)
        """
    )


def downgrade() -> None:
    raise RuntimeError("KenRadar baseline 不支持自动降级；请通过数据库备份恢复")
