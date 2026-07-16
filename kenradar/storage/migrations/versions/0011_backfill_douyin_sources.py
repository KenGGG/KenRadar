"""Backfill source subscriptions for existing Douyin creators."""
from __future__ import annotations

from alembic import op

revision = "0011_backfill_douyin_sources"
down_revision = "0010_source_topic_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO source_subscription
            (platform_id, source_type, source_key, display_name, source_url, enabled)
        SELECT
            p.id, 'douyin_creator',
            COALESCE(NULLIF(c.platform_uid, ''), c.profile_url, c.nickname),
            COALESCE(NULLIF(c.nickname, ''), c.platform_uid),
            c.profile_url,
            COALESCE(c.enabled, TRUE)
        FROM creator c
        JOIN platform p ON p.id = c.platform_id AND p.code = 'douyin'
        WHERE COALESCE(NULLIF(c.platform_uid, ''), c.profile_url, c.nickname) IS NOT NULL
        ON CONFLICT (platform_id, source_key) DO UPDATE SET
            display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), source_subscription.display_name),
            source_url = COALESCE(NULLIF(EXCLUDED.source_url, ''), source_subscription.source_url),
            enabled = EXCLUDED.enabled,
            updated_at = NOW()
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM source_subscription WHERE source_type = 'douyin_creator'")
