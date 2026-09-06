"""Idempotent audit records for delivery tasks."""

from __future__ import annotations

from typing import Any


class PublicationRepository:
    def __init__(self, database: Any):
        self.database = database

    def start(self, content_item_id: int, source_hash: str, idempotency_key: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO publication_log (content_item_id, source_hash, idempotency_key, status)
                VALUES (%s, %s, %s, 'running')
                ON CONFLICT (idempotency_key) DO UPDATE SET updated_at = publication_log.updated_at
                RETURNING id, content_item_id, source_hash, idempotency_key, status, target_url,
                          error_message, attempt_count, created_at, updated_at, completed_at
                """,
                (int(content_item_id), str(source_hash), str(idempotency_key)),
            ).fetchone()
        return dict(row) if row else {}

    def complete(self, publication_id: int, target_url: str = "") -> None:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE publication_log SET status='success', target_url=%s, error_message=NULL,
                   completed_at=NOW(), updated_at=NOW() WHERE id=%s""",
                (str(target_url or ""), int(publication_id)),
            )

    def fail(self, publication_id: int, error_message: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE publication_log SET status='failed', error_message=%s,
                   attempt_count=attempt_count+1, updated_at=NOW() WHERE id=%s""",
                (str(error_message), int(publication_id)),
            )

    def find_success(self, content_item_id: int, source_hash: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT id, content_item_id, source_hash, idempotency_key, status, target_url,
                   error_message, attempt_count, created_at, updated_at, completed_at
                   FROM publication_log WHERE content_item_id=%s AND source_hash=%s AND status='success'
                   ORDER BY id DESC LIMIT 1""",
                (int(content_item_id), str(source_hash)),
            ).fetchone()
        return dict(row) if row else None

    def find_notification_success(self, content_item_id: int, source_hash: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """SELECT id, status, target_url FROM push_log
                   WHERE content_item_id=%s AND idempotency_key=%s AND status='success'
                   LIMIT 1""",
                (int(content_item_id), f"notify:{content_item_id}:{source_hash}"),
            ).fetchone()
        return dict(row) if row else None

    def list_operations(self, content_item_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """Return delivery audit history without exposing task payloads."""
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT 'publication' AS operation, id, status, target_url, error_message,
                       attempt_count, created_at, updated_at, completed_at
                FROM publication_log WHERE content_item_id=%s
                UNION ALL
                SELECT 'notification' AS operation, id, status, target_url, error_message,
                       attempt_count, pushed_at AS created_at, updated_at, pushed_at AS completed_at
                FROM push_log WHERE content_item_id=%s AND idempotency_key IS NOT NULL
                ORDER BY created_at DESC NULLS LAST, id DESC LIMIT %s
                """,
                (int(content_item_id), int(content_item_id), max(1, min(int(limit), 200))),
            ).fetchall()
        return [dict(row) for row in rows]

    def start_notification(self, content_item_id: int, external_id: str, source_hash: str) -> dict[str, Any]:
        key = f"notify:{content_item_id}:{source_hash}"
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO push_log (content_item_id, aweme_id, batch_id, channel, message_type, status, idempotency_key)
                VALUES (%s, %s, %s, 'feishu', 'card', 'running', %s)
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO UPDATE SET updated_at = NOW(), attempt_count = push_log.attempt_count + 1
                RETURNING id, status, idempotency_key
                """,
                (int(content_item_id), str(external_id), f"content:{content_item_id}", key),
            ).fetchone()
        return dict(row) if row else {}

    def complete_notification(self, push_log_id: int, target_url: str = "") -> None:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE push_log SET status='success', target_url=%s, error_message=NULL, pushed_at=NOW()
                   WHERE id=%s""",
                (str(target_url or ""), int(push_log_id)),
            )

    def fail_notification(self, push_log_id: int, error_message: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE push_log SET status='failed', error_message=%s WHERE id=%s",
                (str(error_message), int(push_log_id)),
            )
