from __future__ import annotations

from scripts.verify_v2_media_radar import compare_snapshot


def test_verifier_reports_identity_and_result_mismatches() -> None:
    report = compare_snapshot(
        {
            "legacy_sources": {"douyin:creator-a", "xiaoyuzhou:pod-a"},
            "subscriptions": {"douyin:creator-a"},
            "legacy_content": {"douyin:v1", "xiaoyuzhou:e1"},
            "content_items": {"douyin:v1"},
            "legacy_results": {"douyin:v1"},
            "current_results": set(),
        }
    )

    assert report["source_mismatches"] == ["xiaoyuzhou:pod-a"]
    assert report["content_mismatches"] == ["xiaoyuzhou:e1"]
    assert report["result_mismatches"] == ["douyin:v1"]
