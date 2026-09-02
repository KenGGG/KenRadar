"""V2 current-result columns for content, transcript, analysis, notes and subscriptions.

Revision ID: 0015_current_result_columns
Revises: 0014_task_run_controls
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op

revision = "0015_current_result_columns"
down_revision = "0014_task_run_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    statements = (
        # content_item: discovery, review and current failure state
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'discovered'",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS discovery_source VARCHAR(32) NOT NULL DEFAULT 'monitor'",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS discovered_at TIMESTAMPTZ",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS review_status VARCHAR(32) NOT NULL DEFAULT 'none'",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS current_error_code VARCHAR(128) NOT NULL DEFAULT ''",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS current_error_message TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS media_sha256 VARCHAR(64)",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS media_size_bytes BIGINT",
        "ALTER TABLE content_item ADD COLUMN IF NOT EXISTS media_deleted_at TIMESTAMPTZ",
        # transcript: provenance and quality of the current text
        "ALTER TABLE transcript ADD COLUMN IF NOT EXISTS source_type VARCHAR(32) NOT NULL DEFAULT 'funasr'",
        "ALTER TABLE transcript ADD COLUMN IF NOT EXISTS quality_score DOUBLE PRECISION",
        "ALTER TABLE transcript ADD COLUMN IF NOT EXISTS quality_details JSONB",
        "ALTER TABLE transcript ADD COLUMN IF NOT EXISTS input_sha256 VARCHAR(64)",
        "ALTER TABLE transcript ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
        # ai_analysis: profile/prompt provenance and result identity
        "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS profile_name VARCHAR(64) NOT NULL DEFAULT 'default'",
        "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS user_instruction TEXT NOT NULL DEFAULT ''",
        "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(32) NOT NULL DEFAULT ''",
        "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS transcript_hash VARCHAR(64)",
        "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS result_hash VARCHAR(64)",
        "ALTER TABLE ai_analysis ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
        # content_note: note content identity
        "ALTER TABLE content_note ADD COLUMN IF NOT EXISTS content_sha256 VARCHAR(64)",
        "ALTER TABLE content_note ADD COLUMN IF NOT EXISTS analysis_result_hash VARCHAR(64)",
        "ALTER TABLE content_note ADD COLUMN IF NOT EXISTS rendered_at TIMESTAMPTZ",
        # source_subscription: radar scheduling and per-source behaviour
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'active'",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS is_priority BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS next_check_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMPTZ",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS consecutive_failures INT NOT NULL DEFAULT 0",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS default_analysis_profile VARCHAR(64)",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS default_instruction TEXT",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS auto_publish BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS review_required BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS notify_mode VARCHAR(16) NOT NULL DEFAULT 'on_success'",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS media_retention_policy VARCHAR(32) NOT NULL DEFAULT 'after_success'",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS media_retention_days INT",
        "ALTER TABLE source_subscription ADD COLUMN IF NOT EXISTS history_capability VARCHAR(16) NOT NULL DEFAULT 'unknown'",
        # deterministic history backfills
        "UPDATE content_item SET status = 'completed'"
        " WHERE status = 'discovered' AND download_status = 'success'",
        "UPDATE content_item SET discovered_at = COALESCE(discovered_at, created_at)",
        "UPDATE transcript SET completed_at = COALESCE(completed_at, created_at)"
        " WHERE completed_at IS NULL AND status = 'success'",
        "UPDATE ai_analysis SET completed_at = COALESCE(completed_at, created_at)"
        " WHERE completed_at IS NULL AND status = 'success'",
        "UPDATE content_note SET rendered_at = COALESCE(rendered_at, updated_at) WHERE rendered_at IS NULL",
        "UPDATE source_subscription SET next_check_at = COALESCE(next_check_at, NOW())",
        # failure-state scan
        "CREATE INDEX IF NOT EXISTS idx_content_item_current_error"
        " ON content_item(current_error_code) WHERE current_error_code <> ''",
        # radar scan: due subscriptions first
        "CREATE INDEX IF NOT EXISTS idx_source_subscription_due"
        " ON source_subscription(next_check_at) WHERE status = 'active'",
        "CREATE INDEX IF NOT EXISTS idx_content_item_discovery ON content_item(discovery_source, discovered_at DESC)",
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    drop_indexes = (
        "DROP INDEX IF EXISTS idx_content_item_discovery",
        "DROP INDEX IF EXISTS idx_source_subscription_due",
        "DROP INDEX IF EXISTS idx_content_item_current_error",
    )
    for statement in drop_indexes:
        op.execute(statement)

    subscription_columns = (
        "history_capability",
        "media_retention_days",
        "media_retention_policy",
        "notify_mode",
        "review_required",
        "auto_publish",
        "default_instruction",
        "default_analysis_profile",
        "consecutive_failures",
        "last_success_at",
        "next_check_at",
        "is_priority",
        "status",
    )
    for column in subscription_columns:
        op.execute(f"ALTER TABLE source_subscription DROP COLUMN IF EXISTS {column}")

    note_columns = ("rendered_at", "analysis_result_hash", "content_sha256")
    for column in note_columns:
        op.execute(f"ALTER TABLE content_note DROP COLUMN IF EXISTS {column}")

    analysis_columns = ("completed_at", "result_hash", "transcript_hash", "prompt_version", "user_instruction", "profile_name")
    for column in analysis_columns:
        op.execute(f"ALTER TABLE ai_analysis DROP COLUMN IF EXISTS {column}")

    transcript_columns = ("completed_at", "input_sha256", "quality_details", "quality_score", "source_type")
    for column in transcript_columns:
        op.execute(f"ALTER TABLE transcript DROP COLUMN IF EXISTS {column}")

    item_columns = (
        "media_deleted_at",
        "media_size_bytes",
        "media_sha256",
        "current_error_message",
        "current_error_code",
        "review_status",
        "discovered_at",
        "discovery_source",
        "status",
    )
    for column in item_columns:
        op.execute(f"ALTER TABLE content_item DROP COLUMN IF EXISTS {column}")
