import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from test_sqlite_v2 import sqlite_db
from test_organizer_failover import valid
from kenradar.core.config import load_config
from kenradar.core.organizer import ContentOrganizer
from kenradar.core.workflow import Workflow
from kenradar.jobs.podcast_stages import execute_podcast_stage


def test_transcription_stage_reuses_text_without_ai_or_note_writes(sqlite_db):
    db, path = sqlite_db
    creator = db.upsert_creator('xiaoyuzhou', 'show', 'Show', '')
    db.upsert_content_item('xiaoyuzhou', 'episode', creator)
    db.upsert_transcript('episode', 'retained original', '', '', 'fixture', 'success', platform='xiaoyuzhou')
    workflow = object.__new__(Workflow)
    workflow.config = load_config(path)
    workflow.database = workflow.delivery_database = db
    workflow.transcriber = SimpleNamespace(database=db)
    item = dict(platform='xiaoyuzhou', creator='Show', creator_id='show', content_id='episode', source_url='https://example.test', original_title='Episode', published_at='2026-10-20 22:00:00', media_type='audio', duration=0, description='', cover_url=None, raw_metadata={})
    result = asyncio.run(execute_podcast_stage(workflow, 'podcast_transcribe', {'item': item}))
    assert result['stage'] == 'transcript_ready'
    assert not db.get_current_bundle(db.find_content_item('xiaoyuzhou', 'episode')['id']).get('analysis')


def test_optional_metadata_repairs_do_not_invent_high_rating():
    data = valid()
    for key in ['brief_title', 'tags', 'value_score', 'recommendation_reason']:
        del data[key]
    data['importance_score'] = '3'
    normalized = ContentOrganizer._normalize_provider_json_output(json.dumps(data), 'codex', '原标题')
    ContentOrganizer._validate_strict_output(normalized, '原文不能保持头脑清醒')
    result = json.loads(normalized)
    assert result['brief_title'] == '原标题'
    assert result['value_score'] == 1 and result['recommended_action'] == 'review'


def test_short_quoted_term_and_opposing_source_context_are_not_rejected():
    data = valid()
    source = '这个模型不能分开。另一个模型能分开好坏消息。原文不能保持头脑清醒'
    data['corrected_transcript_sections'][0]['content'] = source + '提到“风险平价”术语。'
    ContentOrganizer._validate_strict_output(json.dumps(data), source)


def test_stage_queue_is_idempotent_and_gpu_claims_first(sqlite_db, tmp_path):
    from scripts.stage_podcast_batch import prepare
    db, path = sqlite_db
    original = db.enqueue_task_run('process_url', {'platform': 'xiaoyuzhou', 'external_content_id': 'new'}, 'original')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'items': [{'item': {'content_id': 'new', 'original_title': 'New'},
        'show': 'Show', 'subscription_id': 2, 'task_id': original['id']}]}), encoding='utf8')
    first = prepare(load_config(path), manifest)
    second = prepare(load_config(path), manifest)
    assert first['transcribe'] == second['transcribe'] == 1
    assert first['codex'] == second['codex'] == 1
    assert db.get_task_run(original['id'])['status'] == 'cancelled'
    claimed = db.claim_next_task_run('test-worker')
    assert claimed['task_type'] == 'podcast_transcribe'
    with db.lease_scope(claimed):
        db.complete_task_run(claimed['id'], {'transcribed': 1})
    assert db.claim_next_task_run('test-worker')['task_type'] == 'podcast_codex'


def test_codex_waits_for_gpu_backoff_but_not_other_batches(sqlite_db):
    from sqlalchemy import update
    from kenradar.storage.sqlite_database import utc_now
    db, _ = sqlite_db
    asr = db.enqueue_task_run('podcast_transcribe', {'batch_label': 'one'}, 'ASR', priority=200)
    db.enqueue_task_run('podcast_codex', {'batch_label': 'one'}, 'blocked AI', priority=80)
    other = db.enqueue_task_run('podcast_codex', {'batch_label': 'two'}, 'independent AI', priority=70)
    t = db.table('task_run')
    with db.connect(write=True) as conn:
        conn.execute(update(t).where(t.c.id == asr['id']).values(status='retry_wait', available_at=utc_now(300)))
    claimed = db.claim_next_task_run('test-worker')
    assert claimed['id'] == other['id']
    with db.lease_scope(claimed):
        db.complete_task_run(claimed['id'], {})
    assert db.claim_next_task_run('test-worker') is None
