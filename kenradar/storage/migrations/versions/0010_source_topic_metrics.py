"""Add daily source topic metrics derived from existing AI labels."""
from __future__ import annotations

from alembic import op

revision = "0010_source_topic_metrics"
down_revision = "0009_summary_result_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS source_topic_metrics (
            id BIGSERIAL PRIMARY KEY,
            source_id BIGINT NOT NULL REFERENCES source_subscription(id) ON DELETE CASCADE,
            metric_date DATE NOT NULL,
            topic VARCHAR(128) NOT NULL,
            content_count INT NOT NULL DEFAULT 0,
            content_ratio REAL,
            taxonomy_version VARCHAR(32) NOT NULL DEFAULT 'v1',
            model_name VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (source_id, metric_date, topic, taxonomy_version)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_source_topic_metrics_source_date ON source_topic_metrics(source_id, metric_date DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_topic_metrics")
