from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import yaml

from kenradar.core.config import load_config
from kenradar.core.workflow import Workflow
from kenradar.sources.base import ContentItem
from kenradar.sources.xiaoyuzhou.audio_downloader import AudioDownloader
from kenradar.sources.xiaoyuzhou.page_parser import parse_page
from kenradar.sources.xiaoyuzhou.rss_client import parse_rss


def _config(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "app": {"data_dir": str(tmp_path / "data"), "web_base_url": "http://127.0.0.1:8765"},
                "output": {"obsidian_root": str(tmp_path / "data")},
                "ai": {"whisper": {"device": "cpu"}, "organizer": {"model": "test-model"}},
                "sources": {
                    "xiaoyuzhou": {
                        "enabled": False,
                        "audio_temp_dir": str(tmp_path / "audio"),
                        "delete_audio_after_transcribe": True,
                        "auto_push_feishu": False,
                    }
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return load_config(config_path)


def test_xiaoyuzhou_rss_fixture_parses_episode():
    xml = Path("tests/fixtures/xiaoyuzhou_feed.xml").read_text(encoding="utf-8")
    items = parse_rss(xml, feed_url="https://example.com/feed.xml")
    assert len(items) == 1
    assert items[0].platform == "xiaoyuzhou"
    assert items[0].media_type == "audio"
    assert items[0].content_id == "episode-1"
    assert items[0].duration == 3723
    assert items[0].media_url == "https://cdn.example.com/audio/episode-1.mp3"


def test_xiaoyuzhou_page_fixtures_parse_episode_and_podcast():
    episode_html = Path("tests/fixtures/xiaoyuzhou_episode.html").read_text(encoding="utf-8")
    episode_items = parse_page(episode_html, page_url="https://www.xiaoyuzhoufm.com/episode/episode-1")
    assert [item.content_id for item in episode_items] == ["episode-1"]
    assert episode_items[0].media_url.endswith(".m4a")

    podcast_html = Path("tests/fixtures/xiaoyuzhou_podcast.html").read_text(encoding="utf-8")
    podcast_items = parse_page(podcast_html, page_url="https://www.xiaoyuzhoufm.com/podcast/podcast-1")
    assert [item.content_id for item in podcast_items] == ["episode-1", "episode-2"]
    assert {item.media_type for item in podcast_items} == {"audio"}


def test_audio_download_failure_records_reason(tmp_path):
    item = ContentItem(
        platform="xiaoyuzhou",
        creator="Ken Podcast",
        creator_id="podcast-1",
        content_id="episode-1",
        source_url="https://www.xiaoyuzhoufm.com/episode/episode-1",
        original_title="第一期",
        published_at=None,
        media_type="audio",
        duration=None,
        description=None,
        cover_url=None,
        media_url="https://cdn.example.com/audio/episode-1.exe",
        raw_metadata={},
    )
    assert AudioDownloader(_config(tmp_path)).download(item) is None
    assert item.failure_reason == "unsupported_audio_type:.exe"


def test_podcast_markdown_uses_audio_template(tmp_path):
    workflow = Workflow.__new__(Workflow)
    workflow.config = _config(tmp_path)
    path = workflow._write_item_summary(
        "episode-1",
        "第一期：AI 与投资研究",
        '{"brief_title":"AI 与投资研究","one_sentence_conclusion":"AI 正在改变投研流程。","tags":["AI","投资研究"],"corrected_transcript_sections":[{"title":"开场","content":"今天聊 AI。"}],"value_score":8}',
        "这是原始转录。",
        {
            "platform": "xiaoyuzhou",
            "media_type": "audio",
            "blogger_name": "Ken Podcast",
            "blogger_id": "podcast-1",
            "publish_time": "2026-06-26 10:00:00",
            "video_url": "https://www.xiaoyuzhoufm.com/episode/episode-1",
            "duration": 3723,
            "episode_id": "episode-1",
            "show_id": "podcast-1",
        },
        "",
        "success",
    )
    text = path.read_text(encoding="utf-8")
    assert "platform: xiaoyuzhou" in text
    assert "media_type: audio" in text
    assert "content_id: \"episode-1\"" in text
    assert "## 原始转录" in text
    assert "视频原始转录" not in text


class _FakeDb:
    def __init__(self):
        self.content_ids: set[tuple[str, str]] = set()
        self.upsert_count = 0
        self.summary_rows = []
        self.cleared = []

    def upsert_creator(self, **kwargs):
        return 1

    def upsert_content_item(self, **kwargs):
        key = (str(kwargs["platform"]), str(kwargs["content_id"]))
        self.content_ids.add(key)
        self.upsert_count += 1
        return len(self.content_ids)

    def get_successful_transcript(self, content_id, platform="douyin"):
        return None

    def upsert_summary(self, **kwargs):
        self.summary_rows.append(kwargs)

    def clear_transcript_paths(self, aweme_id, platform="douyin"):
        self.cleared.append((aweme_id, platform))


def test_xiaoyuzhou_mvp_processes_single_episode_without_feishu(tmp_path):
    config = _config(tmp_path)
    audio = tmp_path / "episode-1.mp3"
    audio.write_bytes(b"audio")
    item = ContentItem(
        platform="xiaoyuzhou",
        creator="Ken Podcast",
        creator_id="podcast-1",
        content_id=123,
        source_url="https://www.xiaoyuzhoufm.com/episode/123",
        original_title="第一期",
        published_at=None,
        media_type="audio",
        duration=60,
        description="desc",
        cover_url=None,
        media_url="https://cdn.example.com/audio/123.mp3",
        raw_metadata={"episode_id": "123", "show_id": "podcast-1"},
    )
    workflow = Workflow.__new__(Workflow)
    workflow.config = config
    workflow.database = _FakeDb()

    async def transcribe(*args, **kwargs):
        return {"status": "success", "text": "足够长的转录文本。", "text_path": ""}

    workflow.transcriber = SimpleNamespace(transcribe=transcribe)
    workflow.organizer = SimpleNamespace(
        last_error=None,
        organize=lambda *args, **kwargs: '{"brief_title":"第一期","one_sentence_conclusion":"一句话。","tags":["播客"],"value_score":7}',
    )
    workflow.pusher = SimpleNamespace(push=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("feishu should stay disabled")))
    workflow._publish_markdown = lambda path, title: "https://example.com/episode.html"
    adapter = SimpleNamespace(download_media=lambda _item: audio)

    result = asyncio.run(workflow._process_xiaoyuzhou_item(item, adapter, force=True))
    assert result["status"] == "success"
    assert result["content_id"] == "123"
    assert ("xiaoyuzhou", "123") in workflow.database.content_ids
    assert workflow.database.summary_rows[0]["platform"] == "xiaoyuzhou"


def test_xiaoyuzhou_no_publish_skips_pages_sync_and_feishu(tmp_path, monkeypatch):
    config = _config(tmp_path)
    audio = tmp_path / "episode-2.mp3"
    audio.write_bytes(b"audio")
    item = ContentItem(
        platform="xiaoyuzhou",
        creator="Ken Podcast",
        creator_id="podcast-1",
        content_id="episode-2",
        source_url="https://www.xiaoyuzhoufm.com/episode/episode-2",
        original_title="第二期",
        published_at=None,
        media_type="audio",
        duration=60,
        description="desc",
        cover_url=None,
        media_url="https://cdn.example.com/audio/episode-2.mp3",
        raw_metadata={"episode_id": "episode-2", "show_id": "podcast-1"},
    )
    adapter = SimpleNamespace(resolve_source=lambda _source: [item], download_media=lambda _item: audio)
    monkeypatch.setattr("kenradar.core.workflow.XiaoyuzhouAdapter", lambda _config: adapter)

    workflow = Workflow.__new__(Workflow)
    workflow.config = config
    workflow.database = _FakeDb()

    async def transcribe(*args, **kwargs):
        return {"status": "success", "text": "足够长的转录文本。", "text_path": ""}

    workflow.transcriber = SimpleNamespace(transcribe=transcribe)
    workflow.organizer = SimpleNamespace(
        last_error=None,
        organize=lambda *args, **kwargs: '{"brief_title":"第二期","one_sentence_conclusion":"一句话。","tags":["播客"],"value_score":7}',
    )
    workflow._publish_markdown = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("pages publish should stay disabled"))
    workflow._sync_github_publication = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("git sync should stay disabled"))
    workflow.pusher = SimpleNamespace(push=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("feishu should stay disabled")))

    result = asyncio.run(workflow.research_xiaoyuzhou("https://example.com/feed.xml", push=True, publish=False))
    assert result["processed"] == 1
    assert result["pushed"] is False
    assert result["items"][0]["html_url"] == ""


def test_xiaoyuzhou_cleanup_transcript_temp_after_successful_archive(tmp_path):
    config = _config(tmp_path)
    workflow = Workflow.__new__(Workflow)
    workflow.config = config
    workflow.database = _FakeDb()
    temp_dir = Path(config.get("sources.xiaoyuzhou.audio_temp_dir"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    text_path = temp_dir / "episode-3.transcript.txt"
    json_path = temp_dir / "episode-3.transcript.json"
    text_path.write_text("text", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    removed = workflow._cleanup_xiaoyuzhou_transcript_temp(
        "episode-3",
        {"text_path": str(text_path), "json_path": str(json_path)},
    )
    assert removed == 2
    assert not text_path.exists()
    assert not json_path.exists()
    assert workflow.database.cleared == [("episode-3", "xiaoyuzhou")]


def test_xiaoyuzhou_failed_processing_keeps_transcript_temp(tmp_path):
    config = _config(tmp_path)
    audio = tmp_path / "episode-4.mp3"
    audio.write_bytes(b"audio")
    temp_dir = Path(config.get("sources.xiaoyuzhou.audio_temp_dir"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    text_path = temp_dir / "episode-4.transcript.txt"
    json_path = temp_dir / "episode-4.transcript.json"
    text_path.write_text("debug text", encoding="utf-8")
    json_path.write_text("{}", encoding="utf-8")

    workflow = Workflow.__new__(Workflow)
    workflow.config = config
    workflow.database = _FakeDb()

    async def transcribe(*args, **kwargs):
        return {"status": "failed", "error": "asr failed", "text_path": str(text_path), "json_path": str(json_path)}

    workflow.transcriber = SimpleNamespace(transcribe=transcribe)
    workflow.organizer = SimpleNamespace(last_error=None)
    adapter = SimpleNamespace(download_media=lambda _item: audio)
    item = ContentItem(
        platform="xiaoyuzhou",
        creator="Ken Podcast",
        creator_id="podcast-1",
        content_id="episode-4",
        source_url="https://www.xiaoyuzhoufm.com/episode/episode-4",
        original_title="第四期",
        published_at=None,
        media_type="audio",
        duration=60,
        description="desc",
        cover_url=None,
        media_url="https://cdn.example.com/audio/episode-4.mp3",
        raw_metadata={"episode_id": "episode-4", "show_id": "podcast-1"},
    )

    result = asyncio.run(workflow._process_xiaoyuzhou_item(item, adapter, force=True, publish=False))
    assert result["status"] == "failed"
    assert text_path.exists()
    assert json_path.exists()
