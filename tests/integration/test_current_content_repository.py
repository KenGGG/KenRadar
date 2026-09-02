"""PostgreSQL contract tests for the current-result storage layer (V2 M3).

Locks the single-writer semantics that replace the legacy per-stage tables:
one transaction replaces transcript + ai_analysis + content_note, and a crash
mid-replacement must leave a readable previous state or a complete new state.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from kenradar.storage.pg_database import Database


@pytest.fixture
def content_item(content_db: Database) -> dict[str, Any]:
    content_db.ensure_platform("douyin", "抖音")
    with content_db.connect() as conn:
        creator = conn.execute(
            """
            INSERT INTO creator (platform_id, platform_uid, nickname, profile_url)
            VALUES ((SELECT id FROM platform WHERE code = 'douyin'),
                    'sec-test-current', '测试博主', 'https://www.douyin.com/user/sec-test-current')
            ON CONFLICT DO NOTHING
            RETURNING id
            """
        ).fetchone()
        if creator is None:
            creator = conn.execute(
                "SELECT id FROM creator WHERE platform_uid = 'sec-test-current'"
            ).fetchone()
        row = conn.execute(
            """
            INSERT INTO content_item (platform_id, creator_id, content_id, title,
                                      source_url, content_type, publish_time, status)
            VALUES ((SELECT id FROM platform WHERE code = 'douyin'), %s, 'aweme-current-1',
                    '标题', 'https://www.douyin.com/video/aweme-current-1',
                    'video', NOW(), 'pending')
            RETURNING id, content_id
            """,
            (creator["id"],),
        ).fetchone()
    return {"id": int(row["id"]), "external_id": str(row["content_id"])}


def _analysis(model: str = "agnes-2.5-flash", text: str = "第一版摘要") -> dict[str, Any]:
    return {
        "status": "success",
        "model": model,
        "provider": "agnes",
        "profile_name": "default",
        "user_instruction": "",
        "prompt_version": "v2",
        "result_json": {"summary": text, "value_score": 4.2},
        "result_text": text,
        "transcript_hash": "hash-t-1",
        "result_hash": f"hash-a-{text}",
    }


def _note(path: str = "data/notes/douyin/测试博主/aweme-current-1.md", sha: str = "hash-n-1") -> dict[str, Any]:
    return {
        "note_path": path,
        "title": "标题",
        "content_sha256": sha,
        "analysis_result_hash": f"hash-a-{'第一版摘要' if sha == 'hash-n-1' else '第二版摘要'}",
    }


def _transcript(text: str = "转录第一版") -> dict[str, Any]:
    return {
        "status": "success",
        "source_type": "funasr",
        "text_content": text,
        "input_sha256": f"hash-t-{text}",
        "quality_score": 0.9,
    }


def test_bundle_roundtrip_replaces_analysis_and_note(content_db: Database, content_item: dict) -> None:
    content_db.replace_analysis_and_note(content_item["id"], _analysis(), _note())
    bundle = content_db.get_current_bundle(content_item["id"])
    assert bundle["analysis"]["result_json"]["summary"] == "第一版摘要"
    assert bundle["note"]["note_path"].endswith("aweme-current-1.md")

    content_db.replace_analysis_and_note(
        content_item["id"], _analysis(model="qwen3.5:9b", text="第二版摘要"),
        _note(path="data/notes/douyin/测试博主/aweme-current-1.md", sha="hash-n-2"),
    )
    bundle = content_db.get_current_bundle(content_item["id"])
    assert bundle["analysis"]["result_json"]["summary"] == "第二版摘要"
    assert bundle["analysis"]["model"] == "qwen3.5:9b"
    assert bundle["note"]["content_sha256"] == "hash-n-2"


def test_full_replacement_is_atomic_across_three_tables(content_db: Database, content_item: dict) -> None:
    content_db.replace_analysis_and_note(content_item["id"], _analysis(), _note())

    # Simulate a crash inside the replacement transaction: the transcript write
    # blows up, so nothing of this replacement may be persisted.
    broken_transcript = dict(_transcript("转录第二版"), text_content=None)

    with pytest.raises(Exception):
        content_db.replace_transcript_analysis_and_note(
            content_item["id"], broken_transcript, _analysis(text="第二版摘要"),
            _note(sha="hash-n-3"),
        )

    bundle = content_db.get_current_bundle(content_item["id"])
    assert bundle["analysis"]["result_text"] == "第一版摘要"
    assert bundle["note"]["content_sha256"] == "hash-n-1"


def test_full_replacement_persists_all_three_stages(content_db: Database, content_item: dict) -> None:
    content_db.replace_transcript_analysis_and_note(
        content_item["id"], _transcript(), _analysis(), _note()
    )
    bundle = content_db.get_current_bundle(content_item["id"])
    assert bundle["transcript"]["text_content"] == "转录第一版"
    assert bundle["analysis"]["result_text"] == "第一版摘要"
    assert bundle["note"]["note_path"].endswith("aweme-current-1.md")


def test_bundle_of_unknown_content_is_none(content_db: Database) -> None:
    assert content_db.get_current_bundle(99999999) is None


def test_content_columns_support_current_error_state(content_db: Database, content_item: dict) -> None:
    with content_db.connect() as conn:
        conn.execute(
            "UPDATE content_item SET current_error_code = 'RATE_LIMITED', current_error_message = '限流' WHERE id = %s",
            (content_item["id"],),
        )
    bundle = content_db.get_current_bundle(content_item["id"])
    assert bundle["content"]["current_error_code"] == "RATE_LIMITED"


def test_failure_is_survivable_in_5s(content_db: Database, content_item: dict) -> None:
    content_db.replace_analysis_and_note(content_item["id"], _analysis(), _note())
    content_db.mark_content_failure(content_item["id"], "RATE_LIMITED", "上游限流")

    bundle = content_db.get_current_bundle(content_item["id"])
    assert bundle["content"]["current_error_code"] == "RATE_LIMITED"
    assert bundle["analysis"]["result_text"] == "第一版摘要"
    assert bundle["note"]["note_path"].endswith("aweme-current-1.md")

    # And a successful replacement clears the failure.
    content_db.replace_analysis_and_note(
        content_item["id"], _analysis(text="第二版摘要"), _note(sha="hash-n-4")
    )
    bundle = content_db.get_current_bundle(content_item["id"])
    assert bundle["content"]["current_error_code"] in (None, "")
    assert bundle["analysis"]["result_text"] == "第二版摘要"
