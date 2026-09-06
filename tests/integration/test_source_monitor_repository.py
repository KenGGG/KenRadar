"""PostgreSQL contract tests for the subscription radar repository (V2 M5)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kenradar.storage.pg_database import Database


@pytest.fixture
def subscription(content_db: Database) -> dict[str, Any]:
    content_db.ensure_platform("douyin", "抖音")
    with content_db.connect() as conn:
        row = conn.execute(
            """
            INSERT INTO source_subscription (platform_id, source_type, source_key, display_name,
                                             source_url, check_interval_minutes, next_check_at)
            VALUES ((SELECT id FROM platform WHERE code = 'douyin'), 'creator', 'sec-radar-1',
                    '雷达测试博主', 'https://www.douyin.com/user/sec-radar-1', 60, NOW() - INTERVAL '1 minute')
            RETURNING id
            """
        ).fetchone()
    return {"id": int(row["id"])}


def test_due_subscription_is_listed(content_db: Database, subscription: dict) -> None:
    rows = content_db.list_due_subscriptions()
    assert [row["id"] for row in rows] == [subscription["id"]]
    assert rows[0]["platform"] == "douyin"
    assert rows[0]["check_interval_minutes"] == 60


def test_future_subscription_is_not_due(content_db: Database, subscription: dict) -> None:
    with content_db.connect() as conn:
        conn.execute(
            "UPDATE source_subscription SET next_check_at = NOW() + INTERVAL '1 hour' WHERE id = %s",
            (subscription["id"],),
        )
    assert content_db.list_due_subscriptions() == []


def test_paused_subscription_is_not_due(content_db: Database, subscription: dict) -> None:
    with content_db.connect() as conn:
        conn.execute(
            "UPDATE source_subscription SET status = 'paused' WHERE id = %s",
            (subscription["id"],),
        )
    assert content_db.list_due_subscriptions() == []


def test_due_ordering_prefers_oldest_overdue_first(content_db: Database, subscription: dict) -> None:
    content_db.ensure_platform("xiaoyuzhou", "小宇宙")
    with content_db.connect() as conn:
        very_old = conn.execute(
            """
            INSERT INTO source_subscription (platform_id, source_type, source_key, display_name,
                                             source_url, check_interval_minutes, next_check_at)
            VALUES ((SELECT id FROM platform WHERE code = 'xiaoyuzhou'), 'podcast', 'pod-radar-1',
                    '雷达测试播客', 'https://www.xiaoyuzhoufm.com/podcast/pod-radar-1', 60,
                    NOW() - INTERVAL '5 hours')
            RETURNING id
            """
        ).fetchone()
    rows = content_db.list_due_subscriptions()
    assert rows[0]["id"] == int(very_old["id"])
    assert rows[-1]["id"] == subscription["id"]


def test_content_exists_reflects_stored_items(content_db: Database) -> None:
    content_db.ensure_platform("douyin", "抖音")
    assert content_db.content_exists("douyin", "not-there") is False
    with content_db.connect() as conn:
        creator = conn.execute(
            """
            INSERT INTO creator (platform_id, platform_uid, nickname, profile_url)
            VALUES ((SELECT id FROM platform WHERE code = 'douyin'), 'sec-radar-1', '博主',
                    'https://www.douyin.com/user/sec-radar-1')
            ON CONFLICT DO NOTHING RETURNING id
            """
        ).fetchone()
        if creator is None:
            creator = conn.execute(
                "SELECT id FROM creator WHERE platform_uid = 'sec-radar-1'"
            ).fetchone()
        conn.execute(
            """
            INSERT INTO content_item (platform_id, creator_id, content_id, title, source_url, content_type)
            VALUES ((SELECT id FROM platform WHERE code = 'douyin'), %s, 'aweme-radar-1', '标题',
                    'https://www.douyin.com/video/aweme-radar-1', 'video')
            """,
            (creator["id"],),
        )
    assert content_db.content_exists("douyin", "aweme-radar-1") is True


def test_record_scan_success_resets_failures(content_db: Database, subscription: dict) -> None:
    with content_db.connect() as conn:
        conn.execute(
            "UPDATE source_subscription SET consecutive_failures = 4 WHERE id = %s",
            (subscription["id"],),
        )
    next_check = datetime.now(timezone.utc) + timedelta(minutes=60)
    content_db.record_subscription_scan(
        subscription["id"],
        success=True,
        next_check_at=next_check,
        last_success_at=datetime.now(timezone.utc),
    )
    row = _load(content_db, subscription["id"])
    assert row["consecutive_failures"] == 0
    assert row["last_success_at"] is not None
    assert row["last_error"] == ""


def test_record_scan_failure_increments_and_records_error(content_db: Database, subscription: dict) -> None:
    content_db.record_subscription_scan(
        subscription["id"],
        success=False,
        next_check_at=datetime.now(timezone.utc) + timedelta(minutes=120),
        last_error="页面结构变化",
    )
    row = _load(content_db, subscription["id"])
    assert row["consecutive_failures"] == 1
    assert row["last_error"] == "页面结构变化"
    assert row["last_success_at"] is None


def _load(database: Database, subscription_id: int) -> dict[str, Any]:
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT consecutive_failures, last_error, last_success_at, next_check_at, last_checked_at
            FROM source_subscription WHERE id = %s
            """,
            (subscription_id,),
        ).fetchone()
    return dict(row)
