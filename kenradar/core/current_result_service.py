"""Orchestrates atomic replacement of a content item's current result.

Each stage produces a descriptor; the service writes them in one transaction so
a crash can never leave a half-written replacement. The service never deletes
the previous result until the new one is fully committed, satisfying the
"current result safe replacement" invariant of V2 M3.
"""

from __future__ import annotations

import logging
from typing import Any

from kenradar.domain.states import normalize_error_code
from kenradar.storage.repositories.current_content import sha256_text

logger = logging.getLogger(__name__)


class CurrentResultService:
    def __init__(self, database: Any):
        self.database = database

    # ── single-transaction replacement ────────────────────────────────

    def replace_transcript_analysis_note(
        self,
        content_item_id: int,
        *,
        transcript: dict[str, Any] | None = None,
        analysis: dict[str, Any] | None = None,
        note: dict[str, Any] | None = None,
    ) -> None:
        """Persist the current transcript, AI analysis and content note together."""
        if transcript is None and analysis is None and note is None:
            raise ValueError("至少需要一个阶段结果")
        self.database.replace_transcript_analysis_and_note(
            content_item_id,
            transcript,
            analysis or {},
            note or {},
        )
        logger.info("当前结果已替换: content_item=%s", content_item_id)

    def replace_analysis_note(
        self,
        content_item_id: int,
        *,
        analysis: dict[str, Any],
        note: dict[str, Any],
    ) -> None:
        """Persist the current AI analysis and content note together."""
        self.database.replace_analysis_and_note(content_item_id, analysis, note)

    # ── failure handling ─────────────────────────────────────────────

    def mark_failure(self, content_item_id: int, error_message: str, error_code: str = "") -> None:
        """Record a recoverable/permanent failure without losing prior results."""
        code = normalize_error_code(error_code)
        self.database.mark_content_failure(content_item_id, code, error_message)

    # ── descriptor helpers ────────────────────────────────────────────

    @staticmethod
    def build_transcript_descriptor(
        text_content: str,
        *,
        source_type: str = "funasr",
        input_sha256: str | None = None,
        quality_score: float | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "source_type": source_type,
            "text_content": text_content,
            "input_sha256": input_sha256 or sha256_text(text_content),
            "quality_score": quality_score,
        }

    @staticmethod
    def build_analysis_descriptor(
        result_json: dict[str, Any],
        result_text: str,
        *,
        model: str = "",
        provider: str = "",
        profile_name: str = "default",
        user_instruction: str = "",
        prompt_version: str = "",
        transcript_hash: str | None = None,
        result_hash: str | None = None,
    ) -> dict[str, Any]:
        return {
            "status": "success",
            "model": model,
            "provider": provider,
            "profile_name": profile_name,
            "user_instruction": user_instruction,
            "prompt_version": prompt_version,
            "transcript_hash": transcript_hash or (sha256_text(result_text) if result_text else None),
            "result_hash": result_hash or sha256_text(str(result_json)),
            "result_json": result_json,
            "result_text": result_text,
        }

    @staticmethod
    def build_note_descriptor(
        note_path: str,
        title: str,
        *,
        content_sha256: str | None = None,
        analysis_result_hash: str | None = None,
    ) -> dict[str, Any]:
        return {
            "note_path": note_path,
            "title": title,
            "content_sha256": content_sha256 or (sha256_text(note_path) if note_path else None),
            "analysis_result_hash": analysis_result_hash,
        }
