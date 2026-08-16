"""Add missing indexes on hot query paths.

Covers join/filter columns that the dashboard, content-item listing and
task-claim queries hit on every request but were not indexed:
push_log(aweme_id), alert_log(aweme_id), alert_log(notified),
research_job_item(aweme_id), task_step(stage, status, available_at).
"""
from __future__ import annotations

from alembic import op

revision = "0012_hot_path_indexes"
down_revision = "0011_backfill_douyin_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_push_log_aweme ON push_log(aweme_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alert_log_aweme ON alert_log(aweme_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alert_log_notified ON alert_log(notified)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_research_job_item_aweme ON research_job_item(aweme_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_step_claim ON task_step(stage, status, available_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_push_log_aweme")
    op.execute("DROP INDEX IF EXISTS idx_alert_log_aweme")
    op.execute("DROP INDEX IF EXISTS idx_alert_log_notified")
    op.execute("DROP INDEX IF EXISTS idx_research_job_item_aweme")
    op.execute("DROP INDEX IF EXISTS idx_task_step_claim")
