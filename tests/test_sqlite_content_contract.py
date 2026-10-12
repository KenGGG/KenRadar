from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest
from test_sqlite_v2 import sqlite_db


def test_current_result_keeps_structured_conclusion(sqlite_db):
    from kenradar.core.workflow import Workflow
    from kenradar.web.queries import _enrich_aweme_row
    db, _ = sqlite_db
    creator = db.upsert_creator('douyin', 'structured-source', 'fixture', '')
    cid = db.upsert_content_item('douyin', 'structured-item', creator)
    result = {'one_sentence': '一句简洁结论', 'brief_summary': '正文摘要', 'value_score': 4}
    text = json.dumps(result, ensure_ascii=False)
    db.upsert_summary('structured-item', text, '/local/success.md', 'model', 'success')
    workflow = object.__new__(Workflow)
    workflow.database = db
    workflow._record_current_result('douyin', 'structured-item', text, 'success', '/local/success.md', '原文')
    assert db.get_current_bundle(cid)['analysis']['result_json'] == result
    legacy = _enrich_aweme_row({'summary_json': {'summary': text}})
    assert legacy['one_sentence_conclusion'] == '一句简洁结论'


def test_scoped_summary_does_not_process_other_creators(sqlite_db):
    import asyncio
    from kenradar.core.workflow import Workflow
    db, _ = sqlite_db
    for aid in ('selected', 'outside'):
        creator = db.upsert_creator('douyin', aid, aid, '')
        db.upsert_content_item('douyin', aid, creator)
        db.upsert_transcript(aid, '真实文件库中的转录样本', '', '', 'fixture', 'success')
    called = []
    workflow = object.__new__(Workflow)
    workflow.database = db
    def summarize(row, **kwargs):
        called.append(row['aweme_id'])
        return {'status': 'success'}
    workflow._summarize_transcript_row = summarize
    result = asyncio.run(workflow.summarize_existing(limit=1, content_ids=['selected']))
    assert called == ['selected']
    assert result['found'] == 1


def test_failed_analysis_retains_note_without_becoming_success(sqlite_db):
    db, _ = sqlite_db
    creator = db.upsert_creator("douyin", "failure-source", "fixture", "https://example.test")
    cid = db.upsert_content_item("douyin", "failure-item", creator)
    db.upsert_summary("failure-item", '{"brief_summary":"服务不可用"}', '/local/failure.md', 'model', 'failed', 'TLS failure')
    bundle = db.get_current_bundle(cid)
    assert bundle['analysis']['status'] == 'failed'
    assert bundle['note']['note_path'] == '/local/failure.md'
    assert bundle['content']['status'] != 'completed'


def test_v2_chain_contract_preserves_success_and_platform_identity(sqlite_db):
    db, _ = sqlite_db
    creator = db.upsert_creator("douyin", "0001", "fixture", "https://example.test", extra={"old": 1})
    assert db.upsert_creator("douyin", "0001", "fixture", None, extra={"new": 2}) == creator
    assert db.get_creator(creator)["extra"] == {"old": 1, "new": 2}
    db.insert_aweme(creator, {"aweme_id": "000000000000002", "create_time": 1700000000,
        "desc": "国债与算力", "local_path": "fixture.mp4"}, "done")
    db.insert_aweme(creator, {"aweme_id": "000000000000002", "desc": "国债与算力"})
    row = db.find_content_item("douyin", "000000000000002")
    assert row["download_status"] == "done" and row["local_path"] == "fixture.mp4"
    db.upsert_transcript("000000000000002", "保留原始转录", "fixture.txt", "fixture.json", "fixture", "success", segments_json=[])
    db.upsert_transcript("000000000000002", "", "", "", "fixture", "failed", "fixture failure")
    assert db.get_successful_transcript("000000000000002")["segments_json"] == []
    db.upsert_summary("000000000000002", json.dumps({"value_score": 4}), "notes/fixture.md", "fixture", "success")
    assert db.is_aweme_fully_processed("000000000000002")
    db.upsert_summary("000000000000002", "", "", "fixture", "failed", "failed candidate")
    assert db.get_summary("000000000000002")["status"] == "success"
    db.clear_transcript_paths("000000000000002")
    assert db.get_successful_transcript("000000000000002")["text_content"] == "保留原始转录"
    other = db.upsert_creator("xiaoyuzhou", "0001", "podcast fixture", "")
    db.upsert_content_item("xiaoyuzhou", "000000000000002", other, title="podcast fixture")
    db.upsert_transcript("000000000000002", "节目原始文本", "", "", "fixture", "success", platform="xiaoyuzhou")
    assert db.get_successful_transcript("000000000000002", "xiaoyuzhou")["text_content"] == "节目原始文本"


def test_subscription_scan_confirm_execute_and_delivery_audit(sqlite_db):
    db, _ = sqlite_db
    sid = db.upsert_subscription(platform="douyin", source_key="001", display_name="fixture", source_url="https://example.test")
    assert db.find_subscription_by_id(sid)["platform"] == "douyin"
    assert db.list_due_subscriptions()[0]["id"] == sid
    db.set_source_subscription_enabled(sid, False)
    db.upsert_subscription(platform="douyin", source_key="001", display_name="fixture renamed", source_url="")
    assert not db.get_source_subscription(sid)["enabled"]
    db.record_subscription_scan(sid, success=False, next_check_at=datetime.now(timezone.utc) + timedelta(hours=1), last_error="fixture")
    assert db.get_source_subscription(sid)["consecutive_failures"] == 1
    repo = db.research_jobs
    job = repo.create_scan_job(platform="douyin", source_subscription_id=sid, scan_scope="recent", history_capability="partial")
    repo.add_discovered_item(job_id=job["id"], external_content_id="0002", title="fixture", url="https://example.test", published_at=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="尚未确认"):
        repo.mark_executed(job["id"])
    repo.set_item_review(job["id"], "0002", "approved")
    repo.confirm_job(job["id"], confirmed_by="fixture", approve=True)
    repo.mark_executed(job["id"])
    item = repo.claim_next_approved_item(job["id"])
    assert repo.claim_next_approved_item(job["id"]) is None
    assert repo.finish_backfill_item(job["id"], item["id"], success=True)["success"] == 1
    assert repo.get_job(job["id"])["status"] == "completed"
    creator = db.upsert_creator("douyin", "001", "fixture", "")
    cid = db.upsert_content_item("douyin", "0002", creator, title="fixture")
    record = db.publications.start(cid, "fixture-hash", "fixture-publish")
    assert db.publications.start(cid, "fixture-hash", "fixture-publish")["id"] == record["id"]
    db.publications.complete(record["id"], "https://example.test")
    notify = db.publications.start_notification(cid, "0002", "fixture-hash")
    db.publications.complete_notification(notify["id"])
    assert len(db.publications.list_operations(cid)) == 2
    assert db.publications.find_success(cid, "fixture-hash")
    assert db.publications.find_notification_success(cid, "fixture-hash")
    alert = db.insert_alert_log("error", "fixture", "fixture failure")
    again = db.insert_alert_log("error", "fixture", "fixture failure")
    assert alert["id"] == again["id"] and again["occurrence_count"] == 2
    assert not again["should_notify"]
