"""Network failures must reach the subscription failure/backoff boundary."""
import asyncio
from unittest.mock import patch

import pytest
from test_sqlite_v2 import sqlite_db

from kenradar.vendor.douyin_downloader.api_client import DouyinAPIClient
from kenradar.sources.douyin.connector import DouyinConnector
from kenradar.core.source_monitor import SourceMonitorService


class Config:
    cookies = {}
    def get(self, *args):
        return False


class Database:
    def __init__(self):
        self.records = []
    def list_due_subscriptions(self, **kwargs):
        return [{"id": 1, "platform": "douyin", "source_key": "fixture"}]
    def record_subscription_scan(self, *args, **kwargs):
        self.records.append(kwargs)
    def content_exists(self, *args):
        raise AssertionError("Failed list must not reach content processing")


class Response:
    status = 403
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def text(self):
        return "Blocked by ArgusSecurityPlugin Uifid Not Found"


class Session:
    closed = False
    def get(self, *args, **kwargs):
        return Response()
    async def close(self):
        pass


async def ensure(client):
    client._session = Session()


async def token(client):
    return "fixture"


def test_argus_403_records_failed_scan_without_last_success():
    db = Database()
    with patch.object(DouyinAPIClient, "_ensure_session", ensure), patch.object(DouyinAPIClient, "_ensure_ms_token", token):
        stats = asyncio.run(SourceMonitorService(db, {"douyin": DouyinConnector(Config())}).scan_due_subscriptions())
    assert stats["failed"] == 1
    assert db.records[0]["success"] is False
    assert db.records[0]["last_success_at"] is None
    assert "ARGUS" in db.records[0]["last_error"]


@pytest.mark.parametrize("raw", [{}, {"status_code": 2483, "aweme_list": []}, {"status_code": 0}, {"status_code": 0, "aweme_list": None}, {"status_code": 0, "aweme_list": [], "has_more": "bad"}])
def test_invalid_platform_page_is_not_empty_success(raw):
    with pytest.raises(RuntimeError):
        DouyinAPIClient._normalize_paged_response(raw, ["aweme_list"])


def test_valid_empty_platform_page_is_success():
    page = DouyinAPIClient._normalize_paged_response({"status_code": 0, "aweme_list": [], "has_more": 0})
    assert page["items"] == [] and page["has_more"] is False


@pytest.mark.parametrize("raw", [{}, {"status_code": 2483, "aweme_list": []}, {"status_code": 0, "items": None, "has_more": 0}])
def test_connector_rejects_failed_custom_client_response(raw, monkeypatch):
    class Client:
        def __init__(self, *args): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get_user_post(self, *args, **kwargs): return raw
    monkeypatch.setattr("kenradar.sources.douyin.connector.DouyinAPIClient", Client)
    connector = DouyinConnector(None)
    with pytest.raises(RuntimeError):
        asyncio.run(connector.list_recent(connector.map_source("fixture", "fixture")))


@pytest.mark.parametrize("history", [False, True])
@pytest.mark.parametrize("scenario", ["terminal", "repeated", "cycle", "cap", "missing", "second_failure"])
def test_full_scan_requires_terminal_page(history, scenario):
    from types import SimpleNamespace
    from kenradar.sources.contracts import ContentPage
    class Connector:
        calls = 0
        async def list_recent(self, source, cursor=None):
            self.calls += 1
            if scenario == "second_failure" and self.calls == 2:
                raise RuntimeError("second page failed")
            next_cursor = {"terminal": "10", "repeated": "10", "cycle": str(self.calls % 2), "cap": str(self.calls), "missing": None, "second_failure": "10"}[scenario]
            return ContentPage(items=[], next_cursor=next_cursor, has_more=scenario != "terminal")
    class DB(Database):
        research_jobs = SimpleNamespace(create_scan_job=lambda **kw: {"id": 1})
        def find_subscription_by_id(self, _id): return self.list_due_subscriptions()[0]
    db, connector = DB(), Connector()
    service = SourceMonitorService(db, {"douyin": connector})
    if history:
        if scenario == "terminal":
            asyncio.run(service.scan_subscription_history(subscription_id=1))
        else:
            with pytest.raises(RuntimeError):
                asyncio.run(service.scan_subscription_history(subscription_id=1))
    else:
        stats = asyncio.run(service.scan_due_subscriptions(scan_scope="full"))
        assert stats["failed"] == int(scenario != "terminal")
    assert db.records[-1]["success"] is (scenario == "terminal")
    if scenario == "terminal":
        assert connector.calls == 1
    else:
        assert db.records[-1]["last_success_at"] is None
        assert db.records[-1]["last_error"]
        assert connector.calls <= 50


@pytest.mark.parametrize("cursor", [None, "bad", -1])
def test_continuing_platform_page_requires_valid_cursor(cursor):
    raw = {"status_code": 0, "aweme_list": [], "has_more": 1, "max_cursor": cursor}
    with pytest.raises(RuntimeError):
        DouyinAPIClient._normalize_paged_response(raw)


@pytest.mark.parametrize("status,payload,expected_calls", [(403, "denied", 1), (429, "rate limited", 3), (500, "server error", 3), (200, "", 1), (200, "<html>", 1), (200, [], 1)])
def test_transport_failure_never_becomes_empty_page(status, payload, expected_calls, monkeypatch):
    class Reply(Response):
        async def text(self): return str(payload)
        async def json(self, **kwargs):
            if isinstance(payload, str): raise ValueError("invalid JSON")
            return payload
    Reply.status = status
    class Transport(Session):
        calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            return Reply()
    session = Transport()
    async def setup(client): client._session = session
    async def sleep(_): pass
    monkeypatch.setattr(DouyinAPIClient, "_ensure_session", setup)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    client = DouyinAPIClient({})
    monkeypatch.setattr(client, "build_signed_path", lambda *a: ("https://example.invalid", "fixture"))
    with pytest.raises(RuntimeError):
        asyncio.run(client._request_json("/aweme/v1/web/aweme/post/", {}))
    assert session.calls == expected_calls


def test_rejected_list_keeps_prior_success_with_real_sqlite(sqlite_db):
    from datetime import datetime, timedelta, timezone
    db, _ = sqlite_db
    sid = db.upsert_subscription(platform="douyin", source_key="fixture", display_name="fixture", source_url="")
    old = datetime.now(timezone.utc) - timedelta(days=1)
    db.record_subscription_scan(sid, success=True, last_success_at=old, next_check_at=old)
    before = db.get_source_subscription(sid)
    with patch.object(DouyinAPIClient, "_ensure_session", ensure), patch.object(DouyinAPIClient, "_ensure_ms_token", token):
        stats = asyncio.run(SourceMonitorService(db, {"douyin": DouyinConnector(Config())}).scan_due_subscriptions())
    after = db.get_source_subscription(sid)
    assert stats["failed"] == 1
    assert after["last_success_at"] == before["last_success_at"]
    assert after["consecutive_failures"] == 1
    assert "ARGUS" in after["last_error"]
    assert db.count_pending_task_runs() == 0
