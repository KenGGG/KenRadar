"""Contract tests for the subscription radar (V2 M5).

The monitor must scan only due subscriptions, mark discovered content as
`monitor`, enqueue per-content processing, and back off on repeated failures.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kenradar.sources.contracts import (
    ContentDescriptor,
    ContentPage,
    SourceDescriptor,
    SourceParseChanged,
)


@pytest.fixture(autouse=True)
def run_to_thread_inline(monkeypatch: pytest.MonkeyPatch):
    async def _inline(function, /, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _inline)


class _FakeConnector:
    platform = "douyin"

    def __init__(self, pages: dict[str, ContentPage] | None = None, fail: bool = False):
        self.pages = pages or {}
        self.fail = fail
        self.calls: list[str] = []

    async def list_recent(self, source: SourceDescriptor, cursor: str | None = None) -> ContentPage:
        self.calls.append(source.external_source_id)
        if self.fail:
            raise SourceParseChanged("页面结构变化")
        return self.pages.get(source.external_source_id, ContentPage(items=[]))


class _FakeDatabase:
    def __init__(self, subscriptions: list[dict[str, Any]], known: set[tuple[str, str]] | None = None):
        self.subscriptions = subscriptions
        self.known = known or set()
        self.enqueued: list[dict[str, Any]] = []
        self.recorded: list[tuple] = []
        self.discovered: list[tuple] = []

    def list_due_subscriptions(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.subscriptions[:limit]

    def content_exists(self, platform: str, external_id: str) -> bool:
        return (platform, external_id) in self.known

    def record_subscription_scan(
        self,
        subscription_id: int,
        *,
        success: bool,
        next_check_at: datetime,
        last_success_at: datetime | None = None,
        last_error: str = "",
    ) -> None:
        self.recorded.append((subscription_id, success, next_check_at, last_error))

    def enqueue_task_run(
        self,
        task_type: str,
        payload: dict[str, Any],
        message: str,
        requested_by: str = "",
        priority: int = 50,
        idempotency_key: str = "",
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        self.enqueued.append({
            "task_type": task_type,
            "payload": payload,
            "idempotency_key": idempotency_key,
            "priority": priority,
        })
        return {"id": len(self.enqueued)}

    def mark_content_discovered(
        self, platform: str, external_id: str, subscription_id: int, published_at: datetime | None
    ) -> None:
        self.discovered.append((platform, external_id, subscription_id))


def _subscription(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "platform": "douyin",
        "source_key": "sec-1",
        "display_name": "测试博主",
        "source_url": "https://www.douyin.com/user/sec-1",
        "feed_url": "",
        "check_interval_minutes": 60,
        "consecutive_failures": 0,
        "history_capability": "full",
    }
    base.update(overrides)
    return base


def _content(external_id: str, source_id: str = "sec-1") -> ContentDescriptor:
    return ContentDescriptor(
        platform="douyin",
        external_content_id=external_id,
        external_source_id=source_id,
        title=f"视频 {external_id}",
        published_at=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
        media_type="video",
        url=f"https://www.douyin.com/video/{external_id}",
    )


def _service(database: Any, connectors: dict[str, Any]):
    from kenradar.core.source_monitor import SourceMonitorService

    return SourceMonitorService(database, connectors=connectors)


def test_scan_enqueues_only_new_content():
    connector = _FakeConnector(
        pages={"sec-1": ContentPage(items=[_content("v1"), _content("v2")])}
    )
    database = _FakeDatabase([_subscription()], known={("douyin", "v1")})

    stats = asyncio.run(_service(database, {"douyin": connector}).scan_due_subscriptions())

    assert stats["scanned"] == 1
    assert stats["discovered"] == 1
    assert [item["payload"]["url"] for item in database.enqueued] == [
        "https://www.douyin.com/video/v2"
    ]
    assert database.discovered == [("douyin", "v2", 1)]


def test_scan_marks_discovered_content_with_monitor_source():
    connector = _FakeConnector(pages={"sec-1": ContentPage(items=[_content("v9")])})
    database = _FakeDatabase([_subscription()])

    asyncio.run(_service(database, {"douyin": connector}).scan_due_subscriptions())

    assert database.enqueued[0]["payload"]["discovery_source"] == "monitor"
    assert database.enqueued[0]["priority"] == 90


def test_scan_uses_stable_idempotency_key_per_content():
    connector = _FakeConnector(pages={"sec-1": ContentPage(items=[_content("v3")])})
    database = _FakeDatabase([_subscription()])

    asyncio.run(_service(database, {"douyin": connector}).scan_due_subscriptions())
    first = database.enqueued[0]["idempotency_key"]

    database.known.add(("douyin", "v3"))
    connector2 = _FakeConnector(pages={"sec-1": ContentPage(items=[_content("v3")])})
    database2 = _FakeDatabase([_subscription()], known={("douyin", "v3")})
    asyncio.run(_service(database2, {"douyin": connector2}).scan_due_subscriptions())
    assert database2.enqueued == []
    assert first == "monitor:douyin:v3"


def test_scan_advances_next_check_after_success():
    connector = _FakeConnector(pages={"sec-1": ContentPage(items=[])})
    database = _FakeDatabase([_subscription(check_interval_minutes=30)])

    asyncio.run(_service(database, {"douyin": connector}).scan_due_subscriptions())

    subscription_id, success, next_check_at, error = database.recorded[0]
    assert subscription_id == 1
    assert success is True
    assert error == ""
    assert next_check_at > datetime.now(timezone.utc) + timedelta(minutes=25)


def test_scan_backs_off_on_parse_failure():
    connector = _FakeConnector(fail=True)
    database = _FakeDatabase([_subscription(check_interval_minutes=60, consecutive_failures=2)])

    stats = asyncio.run(_service(database, {"douyin": connector}).scan_due_subscriptions())

    assert stats["failed"] == 1
    subscription_id, success, next_check_at, error = database.recorded[0]
    assert success is False
    assert "页面结构变化" in error
    # 3rd consecutive failure backs off well beyond the normal interval.
    assert next_check_at > datetime.now(timezone.utc) + timedelta(minutes=60)


def test_scan_skips_subscriptions_without_connector():
    database = _FakeDatabase([_subscription(platform="bilibili")])

    stats = asyncio.run(_service(database, {"douyin": _FakeConnector()}).scan_due_subscriptions())

    assert stats["skipped"] == 1
    assert database.enqueued == []
    assert database.recorded == []


def test_scan_continues_when_one_subscription_fails():
    connector = _FakeConnector(
        pages={"sec-2": ContentPage(items=[_content("v5", source_id="sec-2")])}
    )
    database = _FakeDatabase(
        [
            _subscription(id=1, source_key="sec-1"),
            _subscription(id=2, source_key="sec-2"),
        ]
    )

    class _FlakyConnector(_FakeConnector):
        async def list_recent(self, source, cursor=None):
            if source.external_source_id == "sec-1":
                raise SourceParseChanged("结构变化")
            return await super().list_recent(source, cursor)

    stats = asyncio.run(
        _service(database, {"douyin": _FlakyConnector(pages=connector.pages)}).scan_due_subscriptions()
    )

    assert stats["failed"] == 1
    assert stats["scanned"] == 2
    assert [item["payload"]["url"] for item in database.enqueued] == [
        "https://www.douyin.com/video/v5"
    ]


# ---------------------------------------------------------------------------
# Subscription backfill (V2 M5)
# ---------------------------------------------------------------------------

class _BackfillDatabase(_FakeDatabase):
    def __init__(self, sources, subscriptions=None):
        super().__init__([])
        self.sources = sources
        self.existing = subscriptions or {}
        self.upserts: list[dict[str, Any]] = []

    def list_content_sources_without_subscription(self, platform, limit=500):
        return self.sources if platform == "xiaoyuzhou" else []

    def find_subscription(self, platform, source_key):
        return self.existing.get(source_key)

    def upsert_subscription(self, **kwargs):
        self.upserts.append(kwargs)


def test_backfill_creates_subscription_for_unsubscribed_source():
    database = _BackfillDatabase([{"platform_uid": "pod-1", "nickname": "播客", "profile_url": "https://x"}])
    stats = asyncio.run(_service(database, {"xiaoyuzhou": _FakeConnector()}).backfill_subscriptions("xiaoyuzhou"))

    assert stats["created"] == 1
    assert database.upserts[0]["source_key"] == "pod-1"
    assert database.upserts[0]["display_name"] == "播客"


def test_backfill_is_idempotent_and_only_enriches_missing_feed():
    database = _BackfillDatabase(
        [{"platform_uid": "pod-1", "nickname": "播客", "profile_url": "https://x"}],
        subscriptions={"pod-1": {"id": 5, "source_key": "pod-1", "display_name": "播客",
                                  "source_url": "https://x", "feed_url": "https://feed", "history_capability": "full"}},
    )
    stats = asyncio.run(_service(database, {"xiaoyuzhou": _FakeConnector()}).backfill_subscriptions("xiaoyuzhou"))

    assert stats["created"] == 0
    assert stats["enriched"] == 0
    assert database.upserts == []


def test_backfill_enriches_subscription_without_feed_url():
    class _FeedConnector(_FakeConnector):
        def _fetch_text(self, url):
            return '<link rel="alternate" type="application/rss+xml" href="https://feed.example/rss" />'

    database = _BackfillDatabase(
        [{"platform_uid": "pod-2", "nickname": "播客2", "profile_url": "https://www.xiaoyuzhoufm.com/podcast/pod-2"}],
        subscriptions={"pod-2": {"id": 6, "source_key": "pod-2", "display_name": "播客2",
                                  "source_url": "https://www.xiaoyuzhoufm.com/podcast/pod-2",
                                  "feed_url": "", "history_capability": "limited"}},
    )
    stats = asyncio.run(_service(database, {"xiaoyuzhou": _FeedConnector()}).backfill_subscriptions("xiaoyuzhou"))

    assert stats["enriched"] == 1
    assert database.upserts[0]["feed_url"] == "https://feed.example/rss"
    assert database.upserts[0]["history_capability"] == "full"


def test_backfill_survives_network_failure():
    class _BrokenConnector(_FakeConnector):
        def _fetch_text(self, url):
            raise OSError("网络不可达")

    database = _BackfillDatabase([{"platform_uid": "pod-3", "nickname": "播客3", "profile_url": "https://x"}])
    stats = asyncio.run(_service(database, {"xiaoyuzhou": _BrokenConnector()}).backfill_subscriptions("xiaoyuzhou"))

    assert stats["created"] == 1
    assert database.upserts[0]["feed_url"] == ""
    assert database.upserts[0]["history_capability"] == "limited"
