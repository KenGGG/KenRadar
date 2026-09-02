"""Contract tests for the explicit dual-platform source connector layer."""

from __future__ import annotations

from datetime import datetime

import pytest

from kenradar.sources.contracts import (
    ContentDescriptor,
    ContentPage,
    DownloadResult,
    SourceConnector,
    SourceDescriptor,
    SourceParseChanged,
)
from kenradar.sources.registry import CONNECTORS, connector_for_url, connectors_for_config


def test_registry_only_exposes_launch_connectors():
    assert set(CONNECTORS) == {"douyin", "xiaoyuzhou"}


def test_connector_for_url_matches_launch_platforms():
    assert connector_for_url("https://www.douyin.com/video/1").platform == "douyin"
    assert connector_for_url("https://v.douyin.com/AbCdEf/").platform == "douyin"
    assert connector_for_url("https://www.douyin.com/user/MS4wLjABAAAA").platform == "douyin"
    assert connector_for_url("https://www.xiaoyuzhoufm.com/episode/1").platform == "xiaoyuzhou"
    assert connector_for_url("https://www.xiaoyuzhoufm.com/podcast/1").platform == "xiaoyuzhou"
    assert connector_for_url("https://example.com/feed.xml") is None


def test_connector_implements_protocol():
    for connector in connectors_for_config(None).values():
        assert isinstance(connector, SourceConnector)


def test_descriptors_use_generic_identity_fields():
    source = SourceDescriptor(
        platform="douyin",
        external_source_id="MS4wLjABAAAA",
        display_name="示例博主",
        source_url="https://www.douyin.com/user/MS4wLjABAAAA",
    )
    content = ContentDescriptor(
        platform="douyin",
        external_content_id="7123456789",
        external_source_id="MS4wLjABAAAA",
        title="示例视频",
        published_at=datetime(2026, 9, 1, 12, 0, 0),
        media_type="video",
        url="https://www.douyin.com/video/7123456789",
        raw_metadata={"aweme_id": "7123456789"},
    )
    page = ContentPage(items=[content])
    download = DownloadResult(success=True, path="/tmp/a.mp4")

    assert "aweme_id" not in {f for f in source.__dataclass_fields__}
    assert "aweme_id" not in {f for f in content.__dataclass_fields__}
    assert "sec_uid" not in {f for f in content.__dataclass_fields__}
    assert page.history_capability == "unknown"
    assert download.error_code == ""


def test_source_parse_changed_is_a_distinct_signal():
    exc = SourceParseChanged("页面结构变化，解析结果为空")
    assert isinstance(exc, ValueError)
    assert exc.error_code == "SOURCE_PARSE_CHANGED"


def test_connectors_for_config_returns_fresh_instances():
    first = connectors_for_config(None)
    second = connectors_for_config(None)
    assert set(first) == set(CONNECTORS)
    assert first["douyin"] is not second["douyin"]


# ---------------------------------------------------------------------------
# Douyin connector mapping
# ---------------------------------------------------------------------------

RAW_AWEME = {
    "aweme_id": 7123456789012345678,
    "desc": "示例视频标题",
    "create_time": 1756684800,
    "duration": 90000,
    "author": {"sec_uid": "MS4wLjABAAAA-example", "nickname": "示例博主"},
    "video": {"play_addr": {"url_list": ["https://example.com/video.mp4"]}},
    "cover": {"origin_cover": {"url_list": ["https://example.com/cover.jpg"]}},
}


def test_douyin_connector_maps_aweme_to_generic_descriptor():
    from kenradar.sources.douyin.connector import DouyinConnector

    connector = DouyinConnector(None)
    item = connector.map_content(RAW_AWEME)

    assert item.platform == "douyin"
    assert item.external_content_id == "7123456789012345678"
    assert item.external_source_id == "MS4wLjABAAAA-example"
    assert "aweme_id" in item.raw_metadata
    assert not hasattr(item, "aweme_id")
    assert item.media_type == "video"
    assert item.url == "https://www.douyin.com/video/7123456789012345678"


def test_douyin_connector_maps_page_to_generic_source():
    from kenradar.sources.douyin.connector import DouyinConnector

    connector = DouyinConnector(None)
    source = connector.map_source("MS4wLjABAAAA-example", "示例博主")

    assert source.platform == "douyin"
    assert source.external_source_id == "MS4wLjABAAAA-example"
    assert source.display_name == "示例博主"
    assert source.source_url == "https://www.douyin.com/user/MS4wLjABAAAA-example"
    assert source.history_capability == "full"


def test_douyin_connector_skips_gallery_items():
    from kenradar.sources.douyin.connector import DouyinConnector

    connector = DouyinConnector(None)
    gallery = dict(RAW_AWEME, image_post_info={"images": []})
    assert connector.map_content(gallery) is None


def test_douyin_connector_list_recent_wraps_api_page(monkeypatch):
    import asyncio

    from kenradar.sources.douyin import connector as douyin_connector

    class _FakeAPIClient:
        def __init__(self, cookies):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get_user_post(self, sec_uid, max_cursor=0, count=20):
            assert sec_uid == "MS4wLjABAAAA-example"
            return {
                "items": [RAW_AWEME],
                "has_more": False,
                "max_cursor": 10,
            }

    monkeypatch.setattr(douyin_connector, "DouyinAPIClient", _FakeAPIClient)
    connector = douyin_connector.DouyinConnector(None)
    source = connector.map_source("MS4wLjABAAAA-example", "示例博主")
    page = asyncio.run(connector.list_recent(source))

    assert page.has_more is False
    assert page.next_cursor == "10"
    assert [item.external_content_id for item in page.items] == ["7123456789012345678"]


# ---------------------------------------------------------------------------
# Xiaoyuzhou connector mapping
# ---------------------------------------------------------------------------

def test_xiaoyuzhou_connector_maps_rss_item_to_generic_descriptor():
    from datetime import datetime

    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector

    connector = XiaoyuzhouConnector(None)
    from kenradar.sources.base import ContentItem

    legacy = ContentItem(
        platform="xiaoyuzhou",
        creator="示例播客",
        creator_id="pod-1",
        content_id="ep-1",
        source_url="https://www.xiaoyuzhoufm.com/episode/ep-1",
        original_title="第 1 期",
        published_at=datetime(2026, 9, 1),
        media_type="audio",
        duration=3600,
        description="shownotes",
        cover_url="https://example.com/cover.jpg",
        media_url="https://example.com/ep1.mp3",
        raw_metadata={"source": "rss", "guid": "ep-1"},
    )

    item = connector.map_content(legacy)

    assert item.platform == "xiaoyuzhou"
    assert item.external_content_id == "ep-1"
    assert item.external_source_id == "pod-1"
    assert item.title == "第 1 期"
    assert item.media_type == "audio"
    assert item.media_url == "https://example.com/ep1.mp3"
    assert not hasattr(item, "episode_id")


def test_xiaoyuzhou_program_without_discoverable_feed_is_limited():
    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector

    connector = XiaoyuzhouConnector(None)
    source = connector.map_source(
        external_source_id="pod-1",
        display_name="示例播客",
        source_url="https://www.xiaoyuzhoufm.com/podcast/pod-1",
        feed_url="",
    )

    assert source.history_capability in {"full", "limited"}
    assert source.history_capability == ("full" if source.feed_url else "limited")


def test_xiaoyuzhou_program_with_rss_feed_is_full():
    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector

    connector = XiaoyuzhouConnector(None)
    source = connector.map_source(
        external_source_id="pod-1",
        display_name="示例播客",
        source_url="https://www.xiaoyuzhoufm.com/podcast/pod-1",
        feed_url="https://example.com/feed.xml",
    )

    assert source.history_capability == "full"
