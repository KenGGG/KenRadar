"""Add cooperative pause, checkpoint and error classification to task_run.

Revision ID: 0014_task_run_controls
Revises: 0013_alert_aggregation
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op

revision = "0014_task_run_controls"
down_revision = "0013_alert_aggregation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE task_run ADD COLUMN IF NOT EXISTS pause_requested_at TIMESTAMPTZ",
        "ALTER TABLE task_run ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ",
        "ALTER TABLE task_run ADD COLUMN IF NOT EXISTS resumed_at TIMESTAMPTZ",
        "ALTER TABLE task_run ADD COLUMN IF NOT EXISTS error_code VARCHAR(128)",
        "ALTER TABLE task_run ADD COLUMN IF NOT EXISTS checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb",
        "ALTER TABLE task_run ADD COLUMN IF NOT EXISTS parent_task_run_id INT REFERENCES task_run(id)",
        "ALTER TABLE task_attempt ADD COLUMN IF NOT EXISTS error_code VARCHAR(128)",
        # Lease recovery scans only running rows with an expired lease.
        "CREATE INDEX IF NOT EXISTS idx_task_run_lease_expiry "
        "ON task_run(lease_expires_at) WHERE status = 'running'",
        # Paused tasks stay out of the claim scan but remain visible to the UI.
        "CREATE INDEX IF NOT EXISTS idx_task_run_paused ON task_run(paused_at DESC) WHERE status = 'paused'",
        "CREATE INDEX IF NOT EXISTS idx_task_attempt_status ON task_attempt(status)",
    ):
        op.execute(statement)

    # Rebuild the status check so a task can be parked in `paused`.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_task_run_status') THEN
                ALTER TABLE task_run DROP CONSTRAINT ck_task_run_status;
            END IF;
            ALTER TABLE task_run ADD CONSTRAINT ck_task_run_status
                CHECK (status IN (
                    'queued', 'running', 'retry_wait', 'paused',
                    'success', 'failed', 'cancelled'
                ));
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_task_run_status') THEN
                ALTER TABLE task_run DROP CONSTRAINT ck_task_run_status;
            END IF;
            ALTER TABLE task_run ADD CONSTRAINT ck_task_run_status
                CHECK (status IN (
                    'queued', 'running', 'retry_wait', 'success', 'failed', 'cancelled'
                ));
        END $$;
        """
    )
    for statement in (
        "DROP INDEX IF EXISTS idx_task_attempt_status",
        "DROP INDEX IF EXISTS idx_task_run_paused",
        "DROP INDEX IF EXISTS idx_task_run_lease_expiry",
        "ALTER TABLE task_attempt DROP COLUMN IF EXISTS error_code",
        "ALTER TABLE task_run DROP COLUMN IF EXISTS parent_task_run_id",
        "ALTER TABLE task_run DROP COLUMN IF EXISTS checkpoint_json",
        "ALTER TABLE task_run DROP COLUMN IF EXISTS error_code",
        "ALTER TABLE task_run DROP COLUMN IF EXISTS resumed_at",
        "ALTER TABLE task_run DROP COLUMN IF EXISTS paused_at",
        "ALTER TABLE task_run DROP COLUMN IF EXISTS pause_requested_at",
    ):
        op.execute(statement)
