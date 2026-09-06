"""Remove retired company research tables and V1 compatibility views."""

from __future__ import annotations

from alembic import op

revision = "0018_remove_retired_features"
down_revision = "0017_pub_notification_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS summary;
        DROP VIEW IF EXISTS aweme;
        DROP VIEW IF EXISTS blogger;
        DROP TABLE IF EXISTS company_financial_red_flags CASCADE;
        DROP TABLE IF EXISTS company_financial_analysis_reports CASCADE;
        DROP TABLE IF EXISTS company_financial_question_answers CASCADE;
        DROP TABLE IF EXISTS company_financial_report_files CASCADE;
        DROP TABLE IF EXISTS company_financial_analysis_jobs CASCADE;
        DROP TABLE IF EXISTS company_research_answers CASCADE;
        DROP TABLE IF EXISTS company_notebooks CASCADE;
        DROP TABLE IF EXISTS company_notice_files CASCADE;
        DROP TABLE IF EXISTS company_research_jobs CASCADE;
        DROP TABLE IF EXISTS company_research_batches CASCADE;
        """
    )


def downgrade() -> None:
    raise RuntimeError("已移除的实验性功能不支持自动恢复；请使用数据库备份。")
