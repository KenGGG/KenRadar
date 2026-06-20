from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kenradar.core.ai_json import fallback_analysis, parse_ai_json
from kenradar.core.checker import BloggerTarget, Checker
from kenradar.core.config import load_config, save_config
from kenradar.core.downloader import Downloader
from kenradar.core.organizer import ContentOrganizer
from kenradar.core.transcriber import Transcriber
from kenradar.core.workflow import Workflow
from kenradar.notification.feishu import FeishuPusher, _raise_for_feishu_error
from kenradar.publishing import GithubSyncManager, StaticSitePublisher
from kenradar.scheduler.scheduler import _trigger_due_run
from kenradar.storage import create_database
from kenradar.web.queries import _normalize_task_run_row
from kenradar.web.app import _execute_task_run, _validate_web_binding_security


def test_config_expands_env_without_overwriting_saved_placeholder(tmp_path, monkeypatch):
    monkeypatch.setenv("KENRADAR_TEST_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/test-token")
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    raw = {
        "app": {"data_dir": "./data", "web_base_url": "http://127.0.0.1:8765"},
        "schedule": {"times": ["10:00"]},
        "ai": {
            "whisper": {"device": "cpu"},
            "organizer": {"endpoint": "http://127.0.0.1:11434/v1", "max_tokens": 128, "top_p": 0.9, "top_k": 0},
        },
        "notification": {"channels": {"feishu": {"webhook_url": "${KENRADAR_TEST_WEBHOOK}"}}},
    }
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    config = load_config(config_path)
    assert config.feishu_webhook_url.endswith("/test-token")

    save_config(config, raw)
    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["notification"]["channels"]["feishu"]["webhook_url"] == "${KENRADAR_TEST_WEBHOOK}"


def test_load_config_warns_but_checker_dedupes_duplicate_bloggers(tmp_path, caplog):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    raw = {
        "app": {"data_dir": "./data", "database_url": "postgresql://user:pass@localhost:5432/kenradar", "web_base_url": "http://127.0.0.1:8765"},
        "schedule": {"times": ["10:00"]},
        "ai": {
            "whisper": {"device": "cpu"},
            "organizer": {"endpoint": "http://127.0.0.1:11434/v1", "max_tokens": 128, "top_p": 0.9, "top_k": 0},
        },
        "bloggers": [
            {"name": "A", "sec_uid": "sec-1", "url": "https://www.douyin.com/user/sec-1", "enabled": True},
            {"name": "B", "sec_uid": "sec-1", "url": "https://www.douyin.com/user/sec-1", "enabled": True},
        ],
    }
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    with caplog.at_level("WARNING"):
        config = load_config(config_path)

    assert "重复来源" in caplog.text

    class Database:
        def __init__(self):
            self.calls = []

        def upsert_blogger(self, **kwargs):
            self.calls.append(kwargs)
            return len(self.calls)

    database = Database()
    targets = Checker(config, database).load_targets()
    assert len(targets) == 1
    assert len(database.calls) == 1


def test_save_config_rejects_duplicate_bloggers(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    raw = {
        "app": {"data_dir": "./data", "database_url": "postgresql://user:pass@localhost:5432/kenradar", "web_base_url": "http://127.0.0.1:8765"},
        "schedule": {"times": ["10:00"]},
        "ai": {
            "whisper": {"device": "cpu"},
            "organizer": {"endpoint": "http://127.0.0.1:11434/v1", "max_tokens": 128, "top_p": 0.9, "top_k": 0},
        },
        "bloggers": [
            {"name": "A", "sec_uid": "sec-1", "url": "https://www.douyin.com/user/sec-1", "enabled": True},
            {"name": "B", "sec_uid": "sec-1", "url": "https://www.douyin.com/user/sec-1", "enabled": True},
        ],
    }
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    config = load_config(config_path)

    with pytest.raises(ValueError, match="重复来源"):
        save_config(config, raw)


def test_create_database_requires_postgresql():
    config = SimpleNamespace(database_type="sqlite", database_url="", database_path=Path("/tmp/kenradar.db"))
    with pytest.raises(RuntimeError, match="要求 PostgreSQL|提供有效的 postgresql"):
        create_database(config)


def test_workflow_llm_worker_not_disabled_by_ollama_flag():
    class Config:
        @staticmethod
        def get(key, default=None):
            values = {
                "pipeline.enable_llm_worker": True,
                "gpu_scheduler.ollama.enabled": False,
            }
            return values.get(key, default)

    workflow = Workflow.__new__(Workflow)
    workflow.config = Config()
    assert workflow._enable_llm_worker_for_pipeline(transcribe_only_gpu=False) is True
    # staged GPU 转录阶段不再禁用 AI worker（允许远程 Agnes 运行）
    assert workflow._enable_llm_worker_for_pipeline(transcribe_only_gpu=True) is True


def test_ollama_fallback_provider_requires_gpu():
    raw = yaml.safe_load(Path("config/config.yaml").read_text(encoding="utf-8"))
    providers = raw["ai"]["organizer"]["providers"]
    ollama_provider = next(provider for provider in providers if provider["api_type"] == "ollama")

    assert ollama_provider["require_gpu"] is True
    assert ollama_provider["num_gpu"] == -1
    assert ollama_provider["main_gpu"] == 0


def test_validate_web_binding_security_requires_password_for_non_loopback():
    config = SimpleNamespace(get=lambda key, default=None: "" if key == "app.web_password" else default)
    with pytest.raises(RuntimeError, match="必须先配置 app.web_password"):
        _validate_web_binding_security(config, "0.0.0.0")

    _validate_web_binding_security(config, "127.0.0.1")


def test_execute_task_run_dispatches_research_blogger():
    called = {}

    class WorkflowStub:
        async def research_blogger(self, **kwargs):
            called.update(kwargs)
            return {"ok": True}

    result = asyncio.run(
        _execute_task_run(
            WorkflowStub(),
            "research_blogger",
            {"blogger": "tester", "limit": 3, "push": True, "force": False, "since": "2026-01-01", "until": "2026-01-31"},
        )
    )

    assert result == {"ok": True}
    assert called == {
        "blogger": "tester",
        "limit": 3,
        "push": True,
        "force": False,
        "since": "2026-01-01",
        "until": "2026-01-31",
    }


def test_execute_task_run_dispatches_retry_batch():
    captured = {}

    class WorkflowStub:
        async def retry_batch(self, aweme_ids, retry_from="auto", on_progress=None):
            captured["aweme_ids"] = aweme_ids
            captured["retry_from"] = retry_from
            assert on_progress is not None
            on_progress(1, 2, "123", "done", "finished")
            return {"processed": 2}

    result = asyncio.run(
        _execute_task_run(
            WorkflowStub(),
            "retry_batch",
            {"aweme_ids": ["123", "456"], "retry_from": "transcribe"},
        )
    )

    assert result == {"processed": 2}
    assert captured["aweme_ids"] == ["123", "456"]
    assert captured["retry_from"] == "transcribe"


def test_scheduler_trigger_enqueues_persistent_run(monkeypatch):
    captured = {}

    class DatabaseStub:
        @staticmethod
        def get_latest_active_task_run():
            return None

        @staticmethod
        def enqueue_task_run(task_type, payload, message, requested_by="web", **kwargs):
            captured.update(
                {
                    "task_type": task_type,
                    "payload": payload,
                    "message": message,
                    "requested_by": requested_by,
                    **kwargs,
                }
            )
            return {"id": 42}

    monkeypatch.setattr("kenradar.scheduler.scheduler.create_database", lambda config: DatabaseStub())
    config = SimpleNamespace()

    result = asyncio.run(_trigger_due_run(config, "10:00", grace_minutes=10, use_persistent_queue=True))

    assert result == "queued"
    assert captured["task_type"] == "run_once"
    assert captured["payload"]["trigger"] == "scheduler"
    assert captured["payload"]["due_time"] == "10:00"
    assert captured["requested_by"] == "scheduler"
    assert captured["priority"] == 100
    assert captured["idempotency_key"].endswith(":10:00")


def test_scheduler_trigger_defers_when_queue_busy(monkeypatch):
    class DatabaseStub:
        @staticmethod
        def get_latest_active_task_run():
            return {"id": 7, "status": "running", "task_type": "research_blogger"}

    monkeypatch.setattr("kenradar.scheduler.scheduler.create_database", lambda config: DatabaseStub())
    config = SimpleNamespace()

    result = asyncio.run(_trigger_due_run(config, "21:00", grace_minutes=10, use_persistent_queue=True))

    assert result == "deferred"


def test_normalize_task_run_row_decodes_json_strings():
    row = _normalize_task_run_row(
        {
            "id": 9,
            "task_type": "retry_batch",
            "status": "running",
            "requested_by": "scheduler",
            "payload_json": '{"aweme_ids":["1","2"]}',
            "progress_json": '{"current":1,"total":2,"message":"step"}',
            "stats_json": '{"processed":2}',
        }
    )

    assert row["task_label"] == "批量重试"
    assert row["status_label"] == "执行中"
    assert row["requested_by_label"] == "内置调度器"
    assert row["payload_json"]["aweme_ids"] == ["1", "2"]
    assert row["progress_json"]["current"] == 1
    assert row["stats_json"]["processed"] == 2


def test_execute_task_run_supports_health_check():
    result = asyncio.run(_execute_task_run(SimpleNamespace(), "system_health_check", {}))
    assert result == {"ok": True, "check": "task_engine"}


def test_web_password_prefers_environment(monkeypatch):
    monkeypatch.setenv("KENRADAR_WEB_PASSWORD", "environment-secret")
    config = SimpleNamespace(web_password="environment-secret", get=lambda key, default=None: default)
    _validate_web_binding_security(config, "0.0.0.0")


def test_ai_json_parser_handles_fenced_and_plain_fallback():
    parsed = parse_ai_json('```json\n{"brief_summary": "半导体景气度改善", "value_score": 4.2}\n```')
    assert parsed
    assert parsed["brief_summary"] == "半导体景气度改善"

    fallback = fallback_analysis("半导体订单超预期，行业进入补库存周期。")
    assert fallback["brief_summary"]
    assert fallback["value_score"] >= 3.0


def test_downloader_prefers_direct_cdn_url_over_douyin_play_endpoint():
    class ApiClient:
        BASE_URL = "https://www.douyin.com"
        headers = {"User-Agent": "test-agent"}

        @staticmethod
        def sign_url(url):
            raise AssertionError(f"CDN 地址存在时不应签名播放地址: {url}")

    aweme = {
        "video": {
            "bit_rate": [
                {
                    "bit_rate": 1000,
                    "play_addr": {
                        "width": 1280,
                        "url_list": [
                            "https://cdn.example.com/video.mp4",
                            "https://www.douyin.com/aweme/v1/play/?video_id=test",
                        ],
                    },
                }
            ]
        }
    }

    url, _headers = Downloader.__new__(Downloader)._build_video_download(aweme, ApiClient())
    assert url == "https://cdn.example.com/video.mp4"


def test_organizer_rejects_incomplete_corrected_transcript_sections():
    incomplete = """
    {
      "brief_title": "测试",
      "brief_summary": "测试摘要",
      "content_sections": [{"title": "要点", "content": "说明"}],
      "corrected_transcript_sections": [{"title": "第一段", "content": "只保留了很短的一部分原文"}]
    }
    """
    original = "这是一段必须完整保留的原始视频转录内容。" * 80

    with pytest.raises(ValueError, match="覆盖不足"):
        ContentOrganizer._validate_provider_output(incomplete, original)

    complete = """
    {
      "brief_title": "测试",
      "brief_summary": "测试摘要",
      "content_sections": [{"title": "要点", "content": "说明"}],
      "corrected_transcript_sections": [{"title": "第一段", "content": "%s"}]
    }
    """ % original
    ContentOrganizer._validate_provider_output(complete, original)


def test_organizer_splits_long_transcript_on_sentence_boundaries():
    transcript = "第一段内容。" * 80 + "第二段内容！" * 80 + "最后一段内容？" * 40
    chunks = ContentOrganizer._split_correction_chunks(transcript, 320)

    assert len(chunks) > 1
    assert "".join(chunks) == transcript
    assert all(len(chunk) <= 320 for chunk in chunks)
    assert all(chunk[-1] in "。！？" for chunk in chunks[:-1])


def test_organizer_retries_invalid_correction_chunk(monkeypatch):
    original = "这是一段需要完整纠错的原始转录内容。" * 20
    summary = '{"brief_title":"测试","brief_summary":"摘要","content_sections":[]}'
    responses = iter(
        [
            "not-json",
            '{"corrected_transcript_sections":[{"title":"完整原文","content":"%s"}]}' % original,
        ]
    )

    class Config:
        @staticmethod
        def get(key, default=None):
            return default

    organizer = ContentOrganizer.__new__(ContentOrganizer)
    organizer.config = Config()
    monkeypatch.setattr(organizer, "_organize_with_provider", lambda *args: next(responses))

    result = organizer._complete_corrected_transcript(
        {"name": "agnes", "correction_chunk_chars": 5000, "correction_retry_count": 2},
        "key",
        summary,
        original,
    )

    assert len(parse_ai_json(result)["corrected_transcript_sections"]) == 1


def test_organizer_falls_back_to_local_correction_when_chunk_coverage_is_low(monkeypatch):
    original = "这是一段需要完整纠错的原始转录内容。" * 220
    summary = '{"brief_title":"测试","brief_summary":"摘要","content_sections":[],"corrected_transcript_sections":[]}'
    low_coverage = '{"corrected_transcript_sections":[{"title":"压缩","content":"%s"}]}' % original[:120]

    class Config:
        @staticmethod
        def get(key, default=None):
            return default

    organizer = ContentOrganizer.__new__(ContentOrganizer)
    organizer.config = Config()
    monkeypatch.setattr(organizer, "_organize_with_provider", lambda *args: low_coverage)

    result = organizer._complete_corrected_transcript(
        {"name": "agnes", "correction_chunk_chars": 900, "correction_retry_count": 1},
        "key",
        summary,
        original,
    )

    sections = parse_ai_json(result)["corrected_transcript_sections"]
    corrected_length = sum(len(section["content"]) for section in sections)
    assert len(sections) > 1
    assert corrected_length >= len(original) * 0.9


def test_static_site_publisher_generates_html_and_public_url(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    data_dir = tmp_path / "data"
    note = data_dir / "notes" / "douyin" / "tester" / "sample.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntype: video_note\npublished_at: \"2026-05-01 10:20:30\"\n---\n# 样例笔记\n\n> [!summary]\n> 一句话。\n\n"
        "## 三、分段原文\n\n### 1. 行业变化\n\n这是纠错后的博主原文。\n\n"
        "## 四、视频原始转录\n\n这是原始转录。\n\n[[半导体]]",
        encoding="utf-8",
    )
    newer_note = note.with_name("newer.md")
    newer_note.write_text(
        "---\ntype: video_note\npublished_at: \"2026-05-03 09:15:00\"\n---\n# 更新的笔记\n",
        encoding="utf-8",
    )
    raw = {
        "app": {"data_dir": str(data_dir), "web_base_url": "http://127.0.0.1:8765"},
        "output": {"obsidian_root": str(data_dir)},
        "publishing": {
            "github_pages": {
                "enabled": True,
                "output_dir": str(tmp_path / "docs"),
                "public_base_url": "https://example.github.io/KenRadar",
            }
        },
        "schedule": {"times": ["10:00"]},
        "ai": {
            "whisper": {"device": "cpu"},
            "organizer": {"endpoint": "http://127.0.0.1:11434/v1", "max_tokens": 128, "top_p": 0.9, "top_k": 0},
        },
    }
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    config = load_config(config_path)

    url = StaticSitePublisher(config).publish_markdown(note)

    assert url == "https://example.github.io/KenRadar/notes/douyin/tester/sample.html"
    html_path = tmp_path / "docs" / "notes" / "douyin" / "tester" / "sample.html"
    assert html_path.exists()
    html = html_path.read_text(encoding="utf-8")
    assert "样例笔记" in html
    assert "wikilink" in html
    assert "三、分段原文" in html
    assert '<details class="transcript">' in html
    assert "<summary>四、视频原始转录</summary>" in html

    collection_url = StaticSitePublisher(config).publish_research_collection(7, "测试博主", [note, newer_note])
    assert collection_url == "https://example.github.io/KenRadar/batch-notes/job-0007-%E6%B5%8B%E8%AF%95%E5%8D%9A%E4%B8%BB/index.html"
    collection = tmp_path / "docs" / "batch-notes" / "job-0007-测试博主"
    assert (collection / "index.html").exists()
    assert (collection / "sample.html").exists()
    collection_html = (collection / "index.html").read_text(encoding="utf-8")
    assert "2026-05-03 09:15" in collection_html
    assert "2026-05-01 10:20" in collection_html
    assert collection_html.index("更新的笔记") < collection_html.index("样例笔记")
    assert "批量转化笔记" in (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "job 0007 测试博主" in (tmp_path / "docs" / "batch-notes" / "index.html").read_text(encoding="utf-8")


def test_static_site_removes_old_title_pages_for_same_video(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    data_dir = tmp_path / "data"
    note_dir = data_dir / "notes" / "douyin" / "tester"
    note_dir.mkdir(parents=True)
    old_note = note_dir / "旧标题_7604693889647217929.md"
    new_note = note_dir / "新标题_7604693889647217929.md"
    old_note.write_text("# 旧标题", encoding="utf-8")
    new_note.write_text("# 新标题", encoding="utf-8")
    raw = {
        "app": {"data_dir": str(data_dir)},
        "output": {"obsidian_root": str(data_dir)},
        "publishing": {"github_pages": {"enabled": True, "output_dir": str(tmp_path / "docs")}},
        "schedule": {"times": ["10:00"]},
        "ai": {"whisper": {"device": "cpu"}, "organizer": {}},
    }
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    publisher = StaticSitePublisher(load_config(config_path))

    publisher.publish_markdown(old_note)
    old_note.unlink()
    publisher.publish_markdown(new_note)

    assert not publisher.html_path_for(old_note).exists()
    assert publisher.html_path_for(new_note).exists()


def test_corrected_transcript_sections_keep_paragraph_text():
    sections = Workflow._normalize_corrected_transcript_sections(
        [
            {"title": "算力需求变化", "content": "原来识别成“算例”，这里修正为“算力”。\n\n观点顺序保持不变。"},
            {"title": "估值判断", "content": "第二段博主原文。"},
        ]
    )

    assert sections == [
        {"title": "算力需求变化", "content": "原来识别成“算例”，这里修正为“算力”。\n\n观点顺序保持不变。"},
        {"title": "估值判断", "content": "第二段博主原文。"},
    ]
    rendered = Workflow._render_corrected_transcript({"corrected_transcript_sections": sections})
    assert "### 1. 算力需求变化" in rendered
    assert "观点顺序保持不变" in rendered

    incomplete = Workflow._validated_corrected_transcript_sections(
        [{"title": "过短结果", "content": "只有很短的一段。"}],
        "这是一段需要完整保留的原始转录。" * 30,
    )
    assert incomplete == []


def test_corrected_transcript_sections_keep_long_chunked_output():
    original = "".join(f"第{index}段完整原文内容。" * 20 for index in range(66))
    sections = [
        {"title": f"段落{index}", "content": f"第{index}段完整原文内容。" * 20}
        for index in range(66)
    ]

    validated = Workflow._validated_corrected_transcript_sections(sections, original)

    assert len(validated) == 66
    assert sum(len(item["content"]) for item in validated) == len(original)


def test_github_sync_dry_run_lists_allowed_publish_files(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    data_dir = tmp_path / "data"
    docs_dir = tmp_path / "docs"
    note = data_dir / "notes" / "douyin" / "tester" / "sample.md"
    brief = data_dir / "briefs" / "brief.md"
    page = docs_dir / "index.html"
    note.parent.mkdir(parents=True)
    brief.parent.mkdir(parents=True)
    docs_dir.mkdir(parents=True)
    note.write_text("# 样例笔记\n\n摘要。", encoding="utf-8")
    brief.write_text("# 简报", encoding="utf-8")
    page.write_text("<html>ok</html>", encoding="utf-8")
    raw = {
        "app": {"data_dir": str(data_dir), "web_base_url": "http://127.0.0.1:8765"},
        "output": {"obsidian_root": str(data_dir)},
        "publishing": {
            "github_pages": {"enabled": True, "output_dir": str(docs_dir), "public_base_url": "https://example.github.io/KenRadar"},
            "github_sync": {
                "enabled": True,
                "repo_dir": str(tmp_path),
                "include_html_docs": True,
                "include_markdown_notes": True,
                "include_briefs": True,
                "include_transcripts": True,
            },
        },
        "schedule": {"times": ["10:00"]},
        "ai": {
            "whisper": {"device": "cpu"},
            "organizer": {"endpoint": "http://127.0.0.1:11434/v1", "max_tokens": 128, "top_p": 0.9, "top_k": 0},
        },
    }
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    config = load_config(config_path)

    result = GithubSyncManager(config).sync(dry_run=True)

    assert result["ok"] is True
    assert "docs/index.html" in result["files"]
    assert "data/notes/douyin/tester/sample.md" in result["files"]
    assert "data/briefs/brief.md" in result["files"]


def test_github_sync_handles_unicode_paths(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    data_dir = tmp_path / "data"
    docs_dir = tmp_path / "docs"
    note = data_dir / "notes" / "douyin" / "测试博主" / "中文 标题.md"
    page = docs_dir / "notes" / "测试博主" / "中文 标题.html"
    note.parent.mkdir(parents=True)
    page.parent.mkdir(parents=True)
    note.write_text("# 中文标题", encoding="utf-8")
    page.write_text("<html>中文标题</html>", encoding="utf-8")
    raw = {
        "app": {"data_dir": str(data_dir), "web_base_url": "http://127.0.0.1:8765"},
        "output": {"obsidian_root": str(data_dir)},
        "publishing": {
            "github_pages": {"enabled": True, "output_dir": str(docs_dir), "public_base_url": "https://example.github.io/KenRadar"},
            "github_sync": {
                "enabled": True,
                "repo_dir": str(tmp_path),
                "auto_commit": False,
                "auto_push": False,
                "include_html_docs": True,
                "include_markdown_notes": True,
                "include_briefs": False,
                "include_transcripts": True,
            },
        },
        "schedule": {"times": ["10:00"]},
        "ai": {
            "whisper": {"device": "cpu"},
            "organizer": {"endpoint": "http://127.0.0.1:11434/v1", "max_tokens": 128, "top_p": 0.9, "top_k": 0},
        },
    }
    config_path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    result = GithubSyncManager(load_config(config_path)).sync()
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "-z"],
        cwd=tmp_path,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.decode().split("\0")

    assert result["ok"] is True
    assert "data/notes/douyin/测试博主/中文 标题.md" in staged
    assert "docs/notes/测试博主/中文 标题.html" in staged


def test_feishu_business_error_is_not_treated_as_success():
    response = SimpleNamespace(
        status_code=200,
        text='{"code":19024,"msg":"Key Words Not Found"}',
        json=lambda: {"code": 19024, "msg": "Key Words Not Found"},
    )

    with pytest.raises(RuntimeError, match="Key Words Not Found"):
        _raise_for_feishu_error(response)


def test_feishu_zero_code_is_success():
    response = SimpleNamespace(
        status_code=200,
        text='{"code":0,"msg":"success"}',
        json=lambda: {"code": 0, "msg": "success"},
    )

    _raise_for_feishu_error(response)


def test_research_card_keeps_url_only_in_button(monkeypatch):
    sent_payloads = []

    class Config:
        feishu_webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

        @staticmethod
        def get(key, default=None):
            return True if key == "notification.enabled" else default

    class Database:
        @staticmethod
        def insert_push_log(*args, **kwargs):
            return None

    monkeypatch.setattr(
        "kenradar.notification.feishu.send_feishu_card",
        lambda webhook_url, payload: sent_payloads.append(payload),
    )
    url = "https://example.github.io/KenRadar/batch-notes/job-0001/index.html"

    assert FeishuPusher(Config(), Database()).push_research_summary(
        1,
        "测试博主",
        {"fetched": 143, "processed": 143, "skipped": 0, "failed": 0, "batch_notes_url": url},
    )

    payload = sent_payloads[0]
    body = payload["card"]["elements"][0]["text"]["content"]
    button = payload["card"]["elements"][1]["actions"][0]
    assert url not in body
    assert button["url"] == url


def test_research_card_normalizes_unicode_url_before_rendering(monkeypatch):
    sent_payloads = []

    class Config:
        feishu_webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

        @staticmethod
        def get(key, default=None):
            return True if key == "notification.enabled" else default

    class Database:
        @staticmethod
        def insert_push_log(*args, **kwargs):
            return None

    monkeypatch.setattr(
        "kenradar.notification.feishu.send_feishu_card",
        lambda webhook_url, payload: sent_payloads.append(payload),
    )
    raw_url = "https://example.github.io/KenRadar/batch-notes/job-0010-中产财富说/index.html"
    normalized_url = "https://example.github.io/KenRadar/batch-notes/job-0010-%E4%B8%AD%E4%BA%A7%E8%B4%A2%E5%AF%8C%E8%AF%B4/index.html"

    assert FeishuPusher(Config(), Database()).push_research_summary(
        10,
        "中产财富说",
        {"fetched": 163, "processed": 163, "skipped": 0, "failed": 0, "batch_notes_url": raw_url},
    )

    button = sent_payloads[0]["card"]["elements"][1]["actions"][0]
    assert button["url"] == normalized_url


def test_funasr_failure_skips_disabled_qwen_and_uses_whisper(tmp_path, monkeypatch):
    values = {
        "ai.whisper.enabled": True,
        "ai.funasr.enabled": True,
        "ai.funasr.fallback_to_qwen_asr": False,
        "ai.qwen_asr.enabled": False,
        "ai.whisper.backend": "faster-whisper",
        "ai.whisper.model": "large-v3-turbo",
        "ai.whisper.device": "cpu",
        "ai.whisper.language": "zh",
        "transcribe.model": "large-v3-turbo",
        "transcribe.device": "cpu",
        "ai.transcript_correction.enabled": False,
    }

    class Config:
        @staticmethod
        def get(key, default=None):
            return values.get(key, default)

    class Database:
        records = []

        def upsert_transcript(self, *args, **kwargs):
            self.records.append((args, kwargs))

    transcriber = Transcriber.__new__(Transcriber)
    transcriber.config = Config()
    transcriber.database = Database()
    transcriber.gpu = SimpleNamespace(
        choose_whisper_device=lambda device: device,
        prepare_turbo_whisper_phase=lambda: None,
    )

    async def failed_funasr(*args, **kwargs):
        return {"status": "failed", "error": "quality failed"}

    async def unexpected_qwen(*args, **kwargs):
        raise AssertionError("disabled Qwen3-ASR must not be called")

    async def unchanged_text(text, metadata):
        return text

    monkeypatch.setattr(transcriber, "_try_funasr", failed_funasr)
    monkeypatch.setattr(transcriber, "_try_qwen_asr", unexpected_qwen)
    monkeypatch.setattr(
        transcriber,
        "_transcribe_with_fallback",
        lambda *args: {"text": "这是一段足够长的中文 Whisper 测试转录文本。", "duration": 10},
    )
    monkeypatch.setattr(transcriber, "_correct_text", unchanged_text)
    monkeypatch.setattr(transcriber, "_save_transcript_files", lambda *args: (None, None))
    monkeypatch.setattr(transcriber, "_compute_type", lambda device: "int8")
    monkeypatch.setattr(transcriber, "_cpu_threads", lambda: 1)
    monkeypatch.setattr(transcriber, "_vad_enabled", lambda: False)
    monkeypatch.setattr(transcriber, "_batch_size", lambda device: 1)

    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"test")
    result = asyncio.run(transcriber.transcribe("123", video_path, {}))

    assert result["status"] == "success"
    assert result["model"] == "large-v3-turbo"


def test_funasr_quality_accepts_short_complete_clip_near_duration_threshold():
    values = {
        "ai.funasr.quality_min_chars": 20,
        "ai.funasr.quality_min_chars_per_minute": 25,
        "ai.funasr.quality_duration_tolerance_ratio": 0.8,
    }

    class Config:
        @staticmethod
        def get(key, default=None):
            return values.get(key, default)

    transcriber = Transcriber.__new__(Transcriber)
    transcriber.config = Config()

    transcriber._validate_asr_quality("这是一段长度刚好足够的简短中文口播内容文本", {"duration": 60}, "FunASR")

    with pytest.raises(ValueError, match="min_chars=20"):
        transcriber._validate_asr_quality("这段内容仍然太短不足以通过", {"duration": 60}, "FunASR")


def test_cleanup_uses_database_path_when_video_filename_has_truncated_id(tmp_path):
    download_root = tmp_path / "data" / "Downloaded"
    video_path = download_root / "测试博主" / "超长标题_75811923.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")

    class Config:
        download_dir = download_root

        @staticmethod
        def get(key, default=None):
            return True if key == "ai.whisper.cleanup_video" else default

    class Database:
        cleared = []

        @staticmethod
        def get_aweme_local_path(aweme_id):
            assert aweme_id == "7581192389931547301"
            return str(video_path)

        def clear_transcript_paths(self, aweme_id):
            self.cleared.append(aweme_id)

    workflow = Workflow.__new__(Workflow)
    workflow.config = Config()
    workflow.database = Database()
    workflow.alerts = SimpleNamespace(warning=lambda *args, **kwargs: None)

    removed = workflow._cleanup_download_artifacts("7581192389931547301")

    assert removed == 1
    assert not video_path.exists()
    assert workflow.database.cleared == ["7581192389931547301"]


def test_research_target_is_added_to_monitoring_config(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "app": {"data_dir": "./data"},
                "schedule": {"times": ["10:00"]},
                "bloggers": [
                    {
                        "platform": "douyin",
                        "url": "https://www.douyin.com/user/existing",
                        "sec_uid": "existing",
                        "name": "已有博主",
                        "category": "财经",
                        "enabled": False,
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)

    class Database:
        calls = []

        def upsert_blogger(self, **kwargs):
            self.calls.append(kwargs)
            return 1

    workflow = Workflow.__new__(Workflow)
    workflow.config = config
    workflow.database = Database()

    assert workflow._ensure_research_target_monitored(
        BloggerTarget(1, "new-creator", "新研究博主", "https://www.douyin.com/user/new-creator")
    )
    assert workflow._ensure_research_target_monitored(
        BloggerTarget(2, "existing", "已有博主新名称", "https://www.douyin.com/user/existing")
    )

    bloggers = yaml.safe_load(config_path.read_text(encoding="utf-8"))["bloggers"]
    assert len(bloggers) == 2
    existing = next(item for item in bloggers if item["sec_uid"] == "existing")
    added = next(item for item in bloggers if item["sec_uid"] == "new-creator")
    assert existing["enabled"] is True
    assert existing["category"] == "财经"
    assert existing["name"] == "已有博主新名称"
    assert added["enabled"] is True
    assert workflow.database.calls[-1]["enabled"] is True
