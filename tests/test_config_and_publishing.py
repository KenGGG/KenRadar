from __future__ import annotations

from pathlib import Path

import yaml

from kenradar.core.ai_json import fallback_analysis, parse_ai_json
from kenradar.core.config import load_config, save_config
from kenradar.core.workflow import Workflow
from kenradar.publishing import GithubSyncManager, StaticSitePublisher


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


def test_ai_json_parser_handles_fenced_and_plain_fallback():
    parsed = parse_ai_json('```json\n{"brief_summary": "半导体景气度改善", "value_score": 4.2}\n```')
    assert parsed
    assert parsed["brief_summary"] == "半导体景气度改善"

    fallback = fallback_analysis("半导体订单超预期，行业进入补库存周期。")
    assert fallback["brief_summary"]
    assert fallback["value_score"] >= 3.0


def test_static_site_publisher_generates_html_and_public_url(tmp_path):
    config_path = tmp_path / "config" / "config.yaml"
    config_path.parent.mkdir()
    data_dir = tmp_path / "data"
    note = data_dir / "notes" / "douyin" / "tester" / "sample.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\ntype: video_note\n---\n# 样例笔记\n\n> [!summary]\n> 一句话。\n\n"
        "## 三、分段原文\n\n### 1. 行业变化\n\n这是纠错后的博主原文。\n\n"
        "## 四、视频原始转录\n\n这是原始转录。\n\n[[半导体]]",
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

    collection_url = StaticSitePublisher(config).publish_research_collection(7, "测试博主", [note])
    assert collection_url == "https://example.github.io/KenRadar/batch-notes/job-0007-测试博主/index.html"
    collection = tmp_path / "docs" / "batch-notes" / "job-0007-测试博主"
    assert (collection / "index.html").exists()
    assert (collection / "sample.html").exists()
    assert "批量转化笔记" in (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")


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
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, stdout=subprocess.PIPE)
    config = load_config(config_path)

    result = GithubSyncManager(config).sync(dry_run=True)

    assert result["ok"] is True
    assert "docs/index.html" in result["files"]
    assert "data/notes/douyin/tester/sample.md" in result["files"]
    assert "data/briefs/brief.md" in result["files"]
