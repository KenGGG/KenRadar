"""Add task_step table for content-stage-level atomic claim.

Revision ID: 0002_add_task_step
Revises: 0001_baseline
Create Date: 2026-06-15
"""
from __future__ import annotations

from alembic import op

revision = "0002_add_task_step"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # task_step 主表
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS task_step (
            id               BIGSERIAL PRIMARY KEY,
            task_run_id      INT REFERENCES task_run(id),
            content_item_id  INT,
            stage            VARCHAR(64) NOT NULL,
            status           VARCHAR(32) NOT NULL DEFAULT 'pending',
            input_version    VARCHAR(64),
            output_ref       JSONB DEFAULT '{}'::jsonb,
            priority         INT DEFAULT 50,
            available_at     TIMESTAMPTZ DEFAULT NOW(),
            locked_by        VARCHAR(128),
            locked_at        TIMESTAMPTZ,
            lease_expires_at TIMESTAMPTZ,
            heartbeat_at     TIMESTAMPTZ,
            attempt          INT DEFAULT 0,
            max_attempts     INT DEFAULT 3,
            error_code       VARCHAR(64),
            error_message    TEXT,
            started_at       TIMESTAMPTZ,
            finished_at      TIMESTAMPTZ,
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            updated_at       TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(content_item_id, stage, input_version)
        )
    """)

    # 状态 CHECK 约束
    conn.exec_driver_sql("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_task_step_status') THEN
                ALTER TABLE task_step ADD CONSTRAINT ck_task_step_status
                    CHECK (status IN (
                        'pending', 'running', 'retry_wait', 'success', 'failed', 'cancelled'
                    ));
            END IF;
        END $$;
    """)

    # 索引
    conn.exec_driver_sql("""
        CREATE INDEX IF NOT EXISTS idx_task_step_stage_status
            ON task_step(stage, status, priority DESC, available_at, created_at)
    """)


def downgrade() -> None:
    op.drop_table("task_step")
