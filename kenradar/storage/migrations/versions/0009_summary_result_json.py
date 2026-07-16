"""Expose structured AI JSON through the legacy summary compatibility view."""
from __future__ import annotations

from alembic import op

revision = "0009_summary_result_json"
down_revision = "0008_source_insights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS summary;
        CREATE VIEW summary AS
        SELECT
            a.id,
            ci.content_id AS aweme_id,
            a.result_text AS summary_text,
            a.result_json,
            n.note_path AS summary_path,
            a.model,
            a.status,
            a.error_message,
            a.created_at,
            a.updated_at
        FROM ai_analysis a
        JOIN content_item ci ON ci.id = a.content_item_id
        LEFT JOIN content_note n ON n.content_item_id = ci.id AND n.note_type = 'content'
        WHERE a.analysis_type = 'summary'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP VIEW IF EXISTS summary;
        CREATE VIEW summary AS
        SELECT
            a.id,
            ci.content_id AS aweme_id,
            a.result_text AS summary_text,
            n.note_path AS summary_path,
            a.model,
            a.status,
            a.error_message,
            a.created_at,
            a.updated_at
        FROM ai_analysis a
        JOIN content_item ci ON ci.id = a.content_item_id
        LEFT JOIN content_note n ON n.content_item_id = ci.id AND n.note_type = 'content'
        WHERE a.analysis_type = 'summary'
        """
    )
