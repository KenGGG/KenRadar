"""Add source_daily_metrics table for source insights MVP.

Revision ID: 0008_source_insights
Revises: 0007_source_subscriptions
Create Date: 2026-07-15
"""
from __future__ import annotations

from alembic import op

revision = "0008_source_insights"
down_revision = "0007_source_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_daily_metrics (
            id                  BIGSERIAL PRIMARY KEY,
            source_id           BIGINT NOT NULL
                REFERENCES source_subscription(id) ON DELETE CASCADE,
            metric_date         DATE NOT NULL,
            total_content       INT NOT NULL DEFAULT 0,
            rated_count         INT NOT NULL DEFAULT 0,
            high_value_count    INT NOT NULL DEFAULT 0,
            avg_rating          REAL,
            push_count          INT NOT NULL DEFAULT 0,
            review_count        INT NOT NULL DEFAULT 0,
            failed_count        INT NOT NULL DEFAULT 0,
            calculation_version VARCHAR(16) NOT NULL DEFAULT 'v1',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (source_id, metric_date)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_daily_metrics_date
            ON source_daily_metrics(metric_date)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_source_daily_metrics_source_date
            ON source_daily_metrics(source_id, metric_date DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_daily_metrics")
