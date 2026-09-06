"""Persist idempotent publication and notification attempts (V2 M7)."""

from __future__ import annotations

from alembic import op

revision = "0017_pub_notification_logs"
down_revision = "0016_scan_confirm_execute"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS publication_log (
            id SERIAL PRIMARY KEY,
            content_item_id INT NOT NULL REFERENCES content_item(id),
            source_hash VARCHAR(64) NOT NULL,
            idempotency_key VARCHAR(192) NOT NULL UNIQUE,
            status VARCHAR(32) NOT NULL DEFAULT 'running',
            target_url TEXT,
            error_message TEXT,
            attempt_count INT NOT NULL DEFAULT 1,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_publication_log_content ON publication_log(content_item_id, created_at DESC)")
    op.execute(
        """
        ALTER TABLE push_log
            ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(192),
            ADD COLUMN IF NOT EXISTS research_job_id INT REFERENCES research_job(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS target_url TEXT,
            ADD COLUMN IF NOT EXISTS attempt_count INT NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_push_log_idempotency
            ON push_log(idempotency_key) WHERE idempotency_key IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_push_log_idempotency")
    op.execute("ALTER TABLE push_log DROP COLUMN IF EXISTS attempt_count")
    op.execute("ALTER TABLE push_log DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE push_log DROP COLUMN IF EXISTS target_url")
    op.execute("ALTER TABLE push_log DROP COLUMN IF EXISTS research_job_id")
    op.execute("ALTER TABLE push_log DROP COLUMN IF EXISTS idempotency_key")
    op.execute("DROP TABLE IF EXISTS publication_log")
