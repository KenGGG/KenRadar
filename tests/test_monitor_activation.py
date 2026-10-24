import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from test_sqlite_v2 import sqlite_db


def test_first_scan_enqueues_new_content_and_respects_disabled_sources(sqlite_db):
    from kenradar.core.source_monitor import SourceMonitorService
    from kenradar.sources.contracts import ContentDescriptor

    db, _ = sqlite_db
    sid = db.upsert_subscription(platform="douyin", source_key="first-scan", display_name="fixture", source_url="")
    disabled = db.upsert_subscription(platform="douyin", source_key="disabled", display_name="disabled", source_url="")
    future = db.upsert_subscription(platform="douyin", source_key="future", display_name="future", source_url="")
    db.set_source_subscription_enabled(disabled, False)
    db.record_subscription_scan(future, success=True, next_check_at=datetime.now(timezone.utc) + timedelta(days=1))
    calls = []

    class Connector:
        async def list_recent(self, source, cursor=None):
            calls.append(source.external_source_id)
            return SimpleNamespace(items=[ContentDescriptor(
                "douyin", "new-video", "first-scan", "new item", None, "video",
                "https://www.douyin.com/video/new-video",
            )], next_cursor=None)

    service = SourceMonitorService(db, connectors={"douyin": Connector()})
    stats = asyncio.run(service.scan_due_subscriptions())
    assert calls == ["first-scan"]
    assert stats["enqueued"] == 1
    task = db.claim_next_task_run("test-monitor")
    assert task["task_type"] == "process_url"
    assert task["payload_json"]["external_content_id"] == "new-video"
    assert task["payload_json"]["push"] is False
    assert db.get_source_subscription(sid)["last_success_at"]
    assert asyncio.run(service.scan_due_subscriptions())["scanned"] == 0
