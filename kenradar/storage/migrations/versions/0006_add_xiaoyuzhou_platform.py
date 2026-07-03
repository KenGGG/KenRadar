"""Add Xiaoyuzhou platform seed.

Revision ID: 0006_add_xiaoyuzhou_platform
Revises: 0005_fin_analysis_mvp
Create Date: 2026-06-26
"""
from __future__ import annotations

from alembic import op

revision = "0006_add_xiaoyuzhou_platform"
down_revision = "0005_fin_analysis_mvp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO platform (code, display_name)
        VALUES ('xiaoyuzhou', '小宇宙')
        ON CONFLICT (code) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM platform WHERE code = 'xiaoyuzhou'")
