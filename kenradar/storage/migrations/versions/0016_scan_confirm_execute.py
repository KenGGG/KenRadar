"""Extend research_job for scan-confirm-execute (V2 M6).

Adds scan scope, history capability, source subscription linkage and
confirm/execute workflow fields to research_job, plus external_content_id
on research_job_item so historical scans can be reviewed before execution.

Revision ID: 0016_scan_confirm_execute
Revises: 0015_current_result_columns
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op

revision = "0016_scan_confirm_execute"
down_revision = "0015_current_result_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # research_job: scope + source linkage + confirm/execute workflow
    op.execute(
        """
        ALTER TABLE research_job
            ADD COLUMN IF NOT EXISTS scan_scope VARCHAR(16) NOT NULL DEFAULT 'recent',
            ADD COLUMN IF NOT EXISTS history_capability VARCHAR(16) NOT NULL DEFAULT 'unknown',
            ADD COLUMN IF NOT EXISTS source_subscription_id BIGINT REFERENCES source_subscription(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS external_content_id VARCHAR(128),
            ADD COLUMN IF NOT EXISTS discovered_count INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS confirmed_count INT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS confirm_status VARCHAR(16) NOT NULL DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS confirmed_by VARCHAR(128),
            ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_job_subscription
            ON research_job(source_subscription_id)
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_research_job_scan_scope'
            ) THEN
                ALTER TABLE research_job
                    ADD CONSTRAINT ck_research_job_scan_scope
                    CHECK (scan_scope IN ('recent', 'full'));
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_research_job_confirm_status'
            ) THEN
                ALTER TABLE research_job
                    ADD CONSTRAINT ck_research_job_confirm_status
                    CHECK (confirm_status IN ('pending', 'confirmed', 'rejected', 'executed'));
            END IF;
        END
        $$
        """
    )

    # research_job_item: link to external content for historical review
    op.execute(
        """
        ALTER TABLE research_job_item
            ADD COLUMN IF NOT EXISTS external_content_id VARCHAR(128),
            ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS title TEXT,
            ADD COLUMN IF NOT EXISTS url TEXT,
            ADD COLUMN IF NOT EXISTS review_status VARCHAR(16) NOT NULL DEFAULT 'pending'
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'ck_research_job_item_review_status'
            ) THEN
                ALTER TABLE research_job_item
                    ADD CONSTRAINT ck_research_job_item_review_status
                    CHECK (review_status IN ('pending', 'approved', 'rejected'));
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_research_job_item_external
            ON research_job_item(job_id, external_content_id)
        """
    )

    # source_subscription: remember last scan scope and history capability
    op.execute(
        """
        ALTER TABLE source_subscription
            ADD COLUMN IF NOT EXISTS last_scan_scope VARCHAR(16),
            ADD COLUMN IF NOT EXISTS history_capability VARCHAR(16) NOT NULL DEFAULT 'unknown'
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE research_job_item DROP COLUMN IF EXISTS review_status"
    )
    op.execute(
        "ALTER TABLE research_job_item DROP COLUMN IF EXISTS url"
    )
    op.execute(
        "ALTER TABLE research_job_item DROP COLUMN IF EXISTS title"
    )
    op.execute(
        "ALTER TABLE research_job_item DROP COLUMN IF EXISTS published_at"
    )
    op.execute(
        "ALTER TABLE research_job_item DROP COLUMN IF EXISTS external_content_id"
    )
    op.execute(
        "ALTER TABLE source_subscription DROP COLUMN IF EXISTS history_capability"
    )
    op.execute(
        "ALTER TABLE source_subscription DROP COLUMN IF EXISTS last_scan_scope"
    )
    op.execute(
        "ALTER TABLE research_job DROP CONSTRAINT IF EXISTS ck_research_job_confirm_status"
    )
    op.execute(
        "ALTER TABLE research_job DROP CONSTRAINT IF EXISTS ck_research_job_scan_scope"
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_research_job_item_external"
    )
    op.execute(
        "DROP INDEX IF EXISTS idx_research_job_subscription"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS confirmed_at"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS confirmed_by"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS confirm_status"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS confirmed_count"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS discovered_count"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS external_content_id"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS source_subscription_id"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS history_capability"
    )
    op.execute(
        "ALTER TABLE research_job DROP COLUMN IF EXISTS scan_scope"
    )
