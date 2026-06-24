"""Add provider attempt fields for company notice downloads.

Revision ID: 0004_company_notice_attempts
Revises: 0003_company_research
Create Date: 2026-06-20
"""
from __future__ import annotations

from alembic import op

revision = "0004_company_notice_attempts"
down_revision = "0003_company_research"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS provider_attempts_json JSONB DEFAULT '{}'::jsonb;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS final_provider TEXT;
        """
    )


def downgrade() -> None:
    raise RuntimeError("KenRadar company notice attempts migration 不支持自动降级；请通过数据库备份恢复")
