"""Subscription radar reads and writes for source_subscription."""

from __future__ import annotations

from datetime import datetime
from typing import Any


class SourceMonitorRepository:
    def __init__(self, database: Any):
        self.database = database

    def list_due_subscriptions(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return active subscriptions whose next_check_at has passed, oldest first."""
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id,
                       p.code AS platform,
                       s.source_key,
                       s.display_name,
                       s.source_url,
                       COALESCE(s.feed_url, '') AS feed_url,
                       COALESCE(s.check_interval_minutes, 60) AS check_interval_minutes,
                       COALESCE(s.consecutive_failures, 0) AS consecutive_failures,
                       COALESCE(s.history_capability, 'unknown') AS history_capability,
                       s.next_check_at
                FROM source_subscription s
                JOIN platform p ON p.id = s.platform_id
                WHERE s.status = 'active'
                  AND COALESCE(s.enabled, TRUE) IS TRUE
                  AND s.next_check_at IS NOT NULL
                  AND s.next_check_at <= NOW()
                ORDER BY s.next_check_at ASC, s.id ASC
                LIMIT %s
                """,
                (max(1, int(limit)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def content_exists(self, platform: str, external_id: str) -> bool:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM content_item ci
                JOIN platform p ON p.id = ci.platform_id
                WHERE p.code = %s AND ci.content_id = %s
                LIMIT 1
                """,
                (str(platform), str(external_id)),
            ).fetchone()
        return row is not None

    def mark_content_discovered(
        self,
        platform: str,
        external_id: str,
        subscription_id: int,
        published_at: datetime | None = None,
    ) -> None:
        """Stamp a stored content item as discovered by the subscription radar."""
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE content_item
                SET discovery_source = 'monitor',
                    discovered_at = COALESCE(discovered_at, NOW()),
                    updated_at = NOW()
                WHERE id = (
                    SELECT ci.id
                    FROM content_item ci
                    JOIN platform p ON p.id = ci.platform_id
                    WHERE p.code = %s AND ci.content_id = %s
                    LIMIT 1
                )
                """,
                (str(platform), str(external_id)),
            )

    def list_content_sources_without_subscription(
        self, platform: str, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Creators that already have stored content but may lack a subscription row."""
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT ON (c.platform_uid)
                       c.platform_uid,
                       c.nickname,
                       c.profile_url
                FROM creator c
                JOIN content_item ci ON ci.creator_id = c.id
                JOIN platform p ON p.id = c.platform_id
                WHERE p.code = %s
                  AND COALESCE(c.platform_uid, '') <> ''
                ORDER BY c.platform_uid, c.id DESC
                LIMIT %s
                """,
                (str(platform), max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def find_subscription(self, platform: str, source_key: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, source_key, display_name, source_url, feed_url, history_capability
                FROM source_subscription
                WHERE platform_id = (SELECT id FROM platform WHERE code = %s)
                  AND source_key = %s
                LIMIT 1
                """,
                (str(platform), str(source_key)),
            ).fetchone()
        return dict(row) if row else None

    def find_subscription_by_id(self, subscription_id: int) -> dict[str, Any] | None:
        """Return one subscription with scan scheduling fields for history scan."""
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT s.id,
                       p.code AS platform,
                       s.source_key,
                       s.display_name,
                       s.source_url,
                       COALESCE(s.feed_url, '') AS feed_url,
                       COALESCE(s.check_interval_minutes, 60) AS check_interval_minutes,
                       COALESCE(s.consecutive_failures, 0) AS consecutive_failures,
                       COALESCE(s.history_capability, 'unknown') AS history_capability,
                       COALESCE(s.status, 'active') AS status,
                       s.next_check_at
                FROM source_subscription s
                JOIN platform p ON p.id = s.platform_id
                WHERE s.id = %s
                LIMIT 1
                """,
                (int(subscription_id),),
            ).fetchone()
        return dict(row) if row else None

    def upsert_subscription(
        self,
        *,
        platform: str,
        source_key: str,
        display_name: str,
        source_url: str,
        feed_url: str = "",
        history_capability: str = "unknown",
        check_interval_minutes: int = 60,
    ) -> None:
        """Insert or refresh a subscription without clobbering scan state."""
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_subscription (
                    platform_id, source_type, source_key, display_name, source_url,
                    feed_url, check_interval_minutes, history_capability, next_check_at
                )
                VALUES (
                    (SELECT id FROM platform WHERE code = %s),
                    CASE WHEN %s = 'xiaoyuzhou' THEN 'podcast' ELSE 'creator' END,
                    %s, %s, %s, %s, %s, %s, NOW()
                )
                ON CONFLICT(platform_id, source_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    source_url = COALESCE(NULLIF(EXCLUDED.source_url, ''), source_subscription.source_url),
                    feed_url = COALESCE(NULLIF(EXCLUDED.feed_url, ''), source_subscription.feed_url),
                    history_capability = CASE
                        WHEN NULLIF(EXCLUDED.feed_url, '') IS NOT NULL THEN 'full'
                        ELSE source_subscription.history_capability
                    END,
                    updated_at = NOW()
                """,
                (
                    str(platform),
                    str(platform),
                    str(source_key),
                    str(display_name),
                    str(source_url),
                    str(feed_url or ""),
                    max(1, int(check_interval_minutes)),
                    str(history_capability),
                ),
            )

    def record_subscription_scan(
        self,
        subscription_id: int,
        *,
        success: bool,
        next_check_at: datetime,
        last_success_at: datetime | None = None,
        last_error: str = "",
    ) -> None:
        """Persist the outcome of one scan and schedule the next check."""
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE source_subscription
                SET last_checked_at = NOW(),
                    next_check_at = %s,
                    last_success_at = CASE WHEN %s THEN COALESCE(%s, NOW()) ELSE last_success_at END,
                    consecutive_failures = CASE WHEN %s THEN 0 ELSE consecutive_failures + 1 END,
                    last_error = CASE WHEN %s THEN '' ELSE %s END,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (
                    next_check_at,
                    success,
                    last_success_at,
                    success,
                    success,
                    last_error,
                    subscription_id,
                ),
            )
