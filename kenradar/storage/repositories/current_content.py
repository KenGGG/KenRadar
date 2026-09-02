"""Single-writer current-result storage for one content item.

The legacy per-stage tables stay untouched for compatibility; this repository
owns the *current* result of each stage. Replacement methods write all stages
in one transaction so a crash can never leave a half-updated record.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class CurrentContentRepository:
    def __init__(self, database: Any):
        self.database = database

    # ── reads ─────────────────────────────────────────────────────────

    def get_current_bundle(self, content_item_id: int) -> dict[str, Any] | None:
        """Return the current content/transcript/analysis/note of one item."""
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    ci.id,
                    ci.content_id,
                    ci.title AS content_title,
                    ci.status AS content_status,
                    ci.review_status,
                    ci.current_error_code,
                    ci.current_error_message,
                    ci.media_sha256,
                    ci.media_size_bytes,
                    ci.media_deleted_at,
                    ci.discovery_source,
                    ci.discovered_at,
                    t.id AS transcript_id,
                    t.status AS transcript_status,
                    t.source_type,
                    t.text_content,
                    t.input_sha256,
                    t.quality_score,
                    t.completed_at AS transcript_completed_at,
                    a.id AS analysis_id,
                    a.status AS analysis_status,
                    a.model,
                    a.provider,
                    a.profile_name,
                    a.user_instruction,
                    a.prompt_version,
                    a.transcript_hash,
                    a.result_hash,
                    a.result_json,
                    a.result_text,
                    a.completed_at AS analysis_completed_at,
                    n.id AS note_id,
                    n.note_type,
                    n.note_path,
                    n.title AS note_title,
                    n.content_sha256,
                    n.analysis_result_hash,
                    n.rendered_at
                FROM content_item ci
                LEFT JOIN transcript t ON t.content_item_id = ci.id
                LEFT JOIN ai_analysis a ON a.content_item_id = ci.id
                LEFT JOIN content_note n ON n.content_item_id = ci.id AND n.note_type = 'content'
                WHERE ci.id = %s
                """,
                (content_item_id,),
            ).fetchone()
        if not row:
            return None
        record = dict(row)
        return {
            "content": {key: record.get(key) for key in (
                "id", "content_id", "content_title", "content_status", "review_status",
                "current_error_code", "current_error_message", "media_sha256",
                "media_size_bytes", "media_deleted_at", "discovery_source", "discovered_at",
            )},
            "transcript": self._stage(record, (
                "transcript_id", "transcript_status", "source_type", "text_content",
                "input_sha256", "quality_score", "transcript_completed_at",
            )) or None,
            "analysis": self._stage(record, (
                "analysis_id", "analysis_status", "model", "provider", "profile_name",
                "user_instruction", "prompt_version", "transcript_hash", "result_hash",
                "result_json", "result_text", "analysis_completed_at",
            )) or None,
            "note": self._stage(record, (
                "note_id", "note_type", "note_path", "note_title", "content_sha256",
                "analysis_result_hash", "rendered_at",
            )) or None,
        }

    def find_content_item(self, platform: str, external_id: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT ci.id, ci.content_id, ci.title, ci.status, ci.review_status
                FROM content_item ci
                JOIN platform p ON p.id = ci.platform_id
                WHERE p.code = %s AND ci.content_id = %s
                """,
                (str(platform), str(external_id)),
            ).fetchone()
        return dict(row) if row else None

    # ── atomic replacement ────────────────────────────────────────────

    def replace_analysis_and_note(
        self,
        content_item_id: int,
        analysis: dict[str, Any],
        note: dict[str, Any],
    ) -> None:
        """Replace the current AI analysis and content note in one transaction."""
        self.replace_transcript_analysis_and_note(content_item_id, None, analysis, note)

    def replace_transcript_analysis_and_note(
        self,
        content_item_id: int,
        transcript: dict[str, Any] | None,
        analysis: dict[str, Any],
        note: dict[str, Any],
    ) -> None:
        """Replace transcript, AI analysis and content note in one transaction."""
        if not self._exists(content_item_id):
            raise ValueError(f"content_item 不存在: {content_item_id}")

        with self.database.connect() as conn:
            if transcript is not None:
                self._upsert_transcript(conn, content_item_id, transcript)
            self._upsert_analysis(conn, content_item_id, analysis)
            self._upsert_note(conn, content_item_id, note)
            conn.execute(
                """
                UPDATE content_item
                SET current_error_code = '',
                    current_error_message = '',
                    status = 'completed',
                    updated_at = NOW()
                WHERE id = %s
                """,
                (content_item_id,),
            )

    def mark_content_failure(
        self,
        content_item_id: int,
        error_code: str,
        error_message: str,
    ) -> None:
        """Record the current failure without touching previous successful results."""
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE content_item
                SET current_error_code = %s,
                    current_error_message = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (str(error_code or ""), str(error_message or ""), content_item_id),
            )

    # ── stage writers (single connection, single transaction) ─────────

    @staticmethod
    def _upsert_transcript(conn: Any, content_item_id: int, transcript: dict[str, Any]) -> None:
        text = transcript.get("text_content")
        if text is None or str(text) == "":
            # Schema-level guarantee: transcript text must never be silently empty.
            raise ValueError("转录文本为空，拒绝替换当前转录")
        result_json = transcript.get("result_json") or {}
        conn.execute(
            """
            INSERT INTO transcript (content_item_id, status, source_type, text_content,
                                    input_sha256, quality_score, quality_details, completed_at, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT(content_item_id) DO UPDATE SET
                status = EXCLUDED.status,
                source_type = EXCLUDED.source_type,
                text_content = EXCLUDED.text_content,
                input_sha256 = EXCLUDED.input_sha256,
                quality_score = EXCLUDED.quality_score,
                quality_details = EXCLUDED.quality_details,
                completed_at = NOW()
            """,
            (
                content_item_id,
                str(transcript.get("status") or "success"),
                str(transcript.get("source_type") or "funasr"),
                text,
                CurrentContentRepository._optional_hash(transcript.get("input_sha256")),
                CurrentContentRepository._optional_float(transcript.get("quality_score")),
                json.dumps(result_json, ensure_ascii=False) if result_json else None,
            ),
        )

    @staticmethod
    def _upsert_analysis(conn: Any, content_item_id: int, analysis: dict[str, Any]) -> None:
        result_json = analysis.get("result_json") or {}
        conn.execute(
            """
            INSERT INTO ai_analysis (content_item_id, analysis_type, status, model, provider, profile_name,
                                     user_instruction, prompt_version, transcript_hash, result_hash,
                                     result_json, result_text, completed_at, created_at)
            VALUES (%s, 'summary', %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, NOW(), NOW())
            ON CONFLICT(content_item_id, analysis_type) DO UPDATE SET
                status = EXCLUDED.status,
                model = EXCLUDED.model,
                provider = EXCLUDED.provider,
                profile_name = EXCLUDED.profile_name,
                user_instruction = EXCLUDED.user_instruction,
                prompt_version = EXCLUDED.prompt_version,
                transcript_hash = EXCLUDED.transcript_hash,
                result_hash = EXCLUDED.result_hash,
                result_json = EXCLUDED.result_json,
                result_text = EXCLUDED.result_text,
                completed_at = NOW()
            """,
            (
                content_item_id,
                str(analysis.get("status") or "success"),
                str(analysis.get("model") or ""),
                str(analysis.get("provider") or ""),
                str(analysis.get("profile_name") or "default"),
                str(analysis.get("user_instruction") or ""),
                str(analysis.get("prompt_version") or ""),
                CurrentContentRepository._optional_hash(analysis.get("transcript_hash")),
                CurrentContentRepository._optional_hash(analysis.get("result_hash")),
                json.dumps(result_json, ensure_ascii=False) if result_json else None,
                analysis.get("result_text") or "",
            ),
        )

    @staticmethod
    def _upsert_note(conn: Any, content_item_id: int, note: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO content_note (content_item_id, note_type, note_path, title,
                                      content_sha256, analysis_result_hash, rendered_at, updated_at)
            VALUES (%s, 'content', %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT(content_item_id, note_type) DO UPDATE SET
                note_path = EXCLUDED.note_path,
                title = EXCLUDED.title,
                content_sha256 = EXCLUDED.content_sha256,
                analysis_result_hash = EXCLUDED.analysis_result_hash,
                rendered_at = NOW(),
                updated_at = NOW()
            """,
            (
                content_item_id,
                str(note.get("note_path") or ""),
                str(note.get("title") or ""),
                CurrentContentRepository._optional_hash(note.get("content_sha256")),
                CurrentContentRepository._optional_hash(note.get("analysis_result_hash")),
            ),
        )

    # ── helpers ───────────────────────────────────────────────────────

    def _exists(self, content_item_id: int) -> bool:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM content_item WHERE id = %s", (content_item_id,)
            ).fetchone()
        return row is not None

    @staticmethod
    def _stage(record: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any] | None:
        stage = {key: record.get(key) for key in keys}
        return stage if any(stage.values()) else None

    @staticmethod
    def _optional_hash(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
