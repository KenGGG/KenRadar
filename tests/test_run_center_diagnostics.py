from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.web.run_center import load_run_center
import pytest
import json


def test_saved_ai_error_explains_generic_task_failure_without_rewriting_audit(sqlite_db):
    db, config_path = sqlite_db
    creator = db.upsert_creator('xiaoyuzhou', 'fixture-show', 'Fixture', '')
    external = '000000000000000000000001'
    db.upsert_content_item('xiaoyuzhou', external, creator)
    db.upsert_summary(external, 'degraded', '', 'fixture', 'failed',
                      error_message='provider: retained source quote mismatch', platform='xiaoyuzhou')
    db.enqueue_task_run('process_url', {'platform':'xiaoyuzhou','external_content_id':external}, 'fixture')
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):
        db.fail_task_run(claimed['id'], '任务返回失败状态', retryable=False)
    result = load_run_center(load_config(config_path), section='attention')
    assert result['total'] == 1
    row = result['items'][0]
    assert row['last_error'] == '任务返回失败状态'
    assert row['diagnostic_error'] == 'provider: retained source quote mismatch'
    assert db.get_task_run(claimed['id'])['last_error'] == '任务返回失败状态'


def test_later_success_moves_old_failure_to_history_without_rewriting_it(sqlite_db, tmp_path):
    from sqlalchemy import update
    from kenradar.storage.sqlite_database import utc_now
    db, config_path = sqlite_db
    creator = db.upsert_creator('xiaoyuzhou', 'show', 'Show', '')
    db.upsert_content_item('xiaoyuzhou', 'episode', creator)
    task = db.enqueue_task_run('process_url', {'platform':'xiaoyuzhou','external_content_id':'episode'}, 'old')
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):
        db.fail_task_run(task['id'], 'old AI error', retryable=False)
    note = tmp_path/'success.md'
    note.write_text('# Success', encoding='utf8')
    db.upsert_summary('episode', '{"brief_summary":"success"}', str(note), 'fixture', 'success', platform='xiaoyuzhou')
    a = db.table('ai_analysis')
    with db.connect(write=True) as conn:
        conn.execute(update(a).values(updated_at=utc_now(-86400), completed_at=utc_now(1)))
    history = load_run_center(load_config(config_path), section='history')['items']
    assert next(row for row in history if row['id'] == task['id'])['display_status'] == 'resolved'
    assert db.get_task_run(task['id'])['status'] == 'failed'
    assert db.get_task_run(task['id'])['last_error'] == 'old AI error'


def test_published_current_hash_is_resolved_but_running_and_stale_hash_are_not(sqlite_db, tmp_path):
    from sqlalchemy import update
    db, config_path = sqlite_db
    creator = db.upsert_creator('xiaoyuzhou', 'show', 'Show', '')
    cid = db.upsert_content_item('xiaoyuzhou', 'episode', creator)
    note = tmp_path/'success.md'
    note.write_text('# Success', encoding='utf8')
    db.upsert_summary('episode', '{"brief_summary":"success"}', str(note), 'fixture', 'success', platform='xiaoyuzhou')
    n = db.table('content_note')
    with db.connect(write=True) as conn:
        conn.execute(update(n).values(content_sha256='a'*64))
    current = db.get_current_bundle(cid)['note']
    record = db.publications.start(cid, current['content_sha256'], 'fixture')
    db.publications.complete(record['id'], 'https://example.test/note')
    first = db.enqueue_task_run('publish_content', {'content_item_id':cid}, 'running publication')
    db.claim_next_task_run('fixture')
    second = db.enqueue_task_run('publish_content', {'content_item_id':cid}, 'queued duplicate')
    active = load_run_center(load_config(config_path), section='active')['items']
    assert next(row for row in active if row['id'] == first['id'])['display_status'] == 'running'
    assert second['id'] not in {row['id'] for row in active}
    n = db.table('content_note')
    with db.connect(write=True) as conn:
        conn.execute(update(n).values(content_sha256='f'*64))
    active = load_run_center(load_config(config_path), section='active')['items']
    assert second['id'] in {row['id'] for row in active}


@pytest.mark.parametrize('recovered_platform,expected', [('douyin', 'resolved'), ('xiaoyuzhou', 'failed')])
def test_url_only_failure_uses_retained_identity_and_platform_for_recovery(sqlite_db, tmp_path, recovered_platform, expected):
    from sqlalchemy import update
    from kenradar.storage.sqlite_database import utc_now
    db, config_path = sqlite_db
    external = '7704508019052137768'
    creator = db.upsert_creator(recovered_platform, 'fixture', 'Fixture', '')
    db.upsert_content_item(recovered_platform, external, creator)
    task = db.enqueue_task_run('process_url', {'url':'https://v.douyin.com/fixture/'}, 'URL only')
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):
        db.fail_task_run(task['id'], 'retained ASR failure', retryable=False)
    t = db.table('task_run')
    with db.connect(write=True) as conn:
        conn.execute(update(t).where(t.c.id == task['id']).values(
            progress_json=json.dumps({'failed_result': {'aweme_id':external, 'status':'failed'}})))
    before = db.get_task_run(task['id'])
    assert task['id'] in {r['id'] for r in load_run_center(load_config(config_path), section='attention')['items']}
    note = tmp_path/'recovered.md'
    note.write_text('# Recovered', encoding='utf8')
    db.upsert_summary(external, '{"brief_summary":"recovered"}', str(note), 'fixture', 'success', platform=recovered_platform)
    with db.connect(write=True) as conn:
        conn.execute(update(db.table('ai_analysis')).values(completed_at=utc_now(1)))
    section = 'history' if expected == 'resolved' else 'attention'
    rows = load_run_center(load_config(config_path), section=section)['items']
    assert next(r for r in rows if r['id'] == task['id'])['display_status'] == expected
    assert db.get_task_run(task['id']) == before
