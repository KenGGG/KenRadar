"""Add source subscriptions.

Revision ID: 0007_source_subscriptions
Revises: 0006_add_xiaoyuzhou_platform
Create Date: 2026-06-28
"""
from __future__ import annotations

from alembic import op

revision = "0007_source_subscriptions"
down_revision = "0006_add_xiaoyuzhou_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_subscription (
            id BIGSERIAL PRIMARY KEY,
            platform_id BIGINT NOT NULL REFERENCES platform(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            source_key TEXT NOT NULL,
            display_name TEXT NOT NULL,
            source_url TEXT,
            feed_url TEXT,
            category TEXT,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            check_interval_minutes INTEGER,
            last_checked_at TIMESTAMPTZ,
            last_item_published_at TIMESTAMPTZ,
            last_error TEXT,
            extra JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(platform_id, source_key)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_subscription_platform_enabled
            ON source_subscription(platform_id, enabled)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_subscription")
