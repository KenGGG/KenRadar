"""Aggregate repeated alerts and track one-time recovery."""
from __future__ import annotations

from alembic import op

revision = "0013_alert_aggregation"
down_revision = "0012_hot_path_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64)")
    op.execute("ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS occurrence_count INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ")
    op.execute("ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ")
    op.execute("ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS aggregation_window_started_at TIMESTAMPTZ")
    op.execute("ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS last_notified_at TIMESTAMPTZ")
    op.execute("ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
    op.execute("UPDATE alert_log SET first_seen_at = COALESCE(first_seen_at, created_at), last_seen_at = COALESCE(last_seen_at, created_at), aggregation_window_started_at = COALESCE(aggregation_window_started_at, created_at)")
    # Pre-aggregation rows remain readable history, but must not appear as active fingerprints.
    op.execute("UPDATE alert_log SET resolved_at = created_at WHERE fingerprint IS NULL AND resolved_at IS NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_log_active_fingerprint ON alert_log(fingerprint) WHERE fingerprint IS NOT NULL AND resolved_at IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alert_log_active_last_seen ON alert_log(last_seen_at DESC) WHERE resolved_at IS NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alert_log_active_last_seen")
    op.execute("DROP INDEX IF EXISTS uq_alert_log_active_fingerprint")
    for column in (
        "resolved_at", "last_notified_at", "aggregation_window_started_at",
        "last_seen_at", "first_seen_at", "occurrence_count", "fingerprint",
    ):
        op.execute(f"ALTER TABLE alert_log DROP COLUMN IF EXISTS {column}")
