import pytest
from sqlalchemy import update

from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.notification.daily import DailySummaryService


@pytest.mark.parametrize('status', ['queued', 'running', 'retry_wait', 'paused', 'failed', 'success'])
@pytest.mark.parametrize('privacy', ['database', 'snapshot', 'payload', 'note'])
def test_private_content_never_enters_digest(sqlite_db, status, privacy):
    db, path = sqlite_db
    source = db.upsert_subscription(platform='xiaoyuzhou', source_key='fixture', display_name='fixture', source_url='')
    creator = db.upsert_creator('xiaoyuzhou', 'fixture', 'fixture', '')
    cid = db.upsert_content_item('xiaoyuzhou', 'private-fixture', creator, content_type='audio',
                                extra={'hermes_private': privacy == 'database'})
    if privacy == 'note':
        note = path.parent.parent / 'copied-note.md'
        note.write_text('---\nhermes_private: true\n---\nPrivate fixture', encoding='utf8')
        db.replace_analysis_and_note(cid, {'status': 'success', 'result_json': {}}, {'note_path': str(note)})
    payload = {'platform': 'xiaoyuzhou', 'external_content_id': 'private-fixture',
               'subscription_id': source, 'day': '2099-01-01'}
    if privacy == 'snapshot':
        payload['item'] = {'raw_metadata': {'hermes_private': True}}
    if privacy == 'payload':
        payload['hermes_private'] = True
    row = db.enqueue_task_run('process_url', payload, 'fixture')
    table = db.table('task_run')
    with db.connect(write=True) as conn:
        conn.execute(update(table).where(table.c.id == row['id']).values(status=status))
    result = DailySummaryService(db, load_config(path)).build('2099-01-01')
    assert 'private-fixture' not in str(result)
    assert result['pending'] == result['failed_content'] == result['verified_count'] == 0
    assert result['failure_details'] == []


@pytest.mark.parametrize('stage', ['podcast_transcribe', 'podcast_organize', 'podcast_codex'])
@pytest.mark.parametrize('status', ['queued', 'running', 'retry_wait', 'paused', 'failed'])
def test_public_podcast_stages_are_reported(sqlite_db, stage, status):
    db, path = sqlite_db
    source = db.upsert_subscription(platform='xiaoyuzhou', source_key='fixture', display_name='fixture', source_url='')
    row = db.enqueue_task_run(stage, {'platform': 'xiaoyuzhou', 'external_content_id': 'public-fixture',
                                    'subscription_id': source, 'day': '2099-01-01'}, 'fixture')
    table = db.table('task_run')
    with db.connect(write=True) as conn:
        conn.execute(update(table).where(table.c.id == row['id']).values(status=status))
    result = DailySummaryService(db, load_config(path)).build('2099-01-01')
    if status == 'failed':
        assert result['failed_content'] == 1
        assert result['failure_details'][0]['external_id'] == 'public-fixture'
    else:
        assert result['pending'] == 1
        assert result['paused_count'] == (status == 'paused')
        assert result['processing_pending'] == (status != 'paused')
        assert result['retrying_count'] == (status == 'retry_wait')


def test_private_retry_cannot_expose_older_failure_in_send(sqlite_db, monkeypatch):
    db, path = sqlite_db
    source = db.upsert_subscription(platform='xiaoyuzhou', source_key='fixture', display_name='fixture', source_url='')
    payload = {'platform': 'xiaoyuzhou', 'external_content_id': 'private-retry-fixture',
               'subscription_id': source, 'day': '2099-01-01'}
    old = db.enqueue_task_run('process_url', payload, 'old fixture')
    new = db.enqueue_task_run('podcast_organize', {**payload, 'item': {'raw_metadata': {'hermes_private': True}}}, 'private retry')
    table = db.table('task_run')
    with db.connect(write=True) as conn:
        conn.execute(update(table).where(table.c.id == old['id']).values(status='failed', updated_at='2099-01-01T00:00:00Z'))
        conn.execute(update(table).where(table.c.id == new['id']).values(status='failed', updated_at='2099-01-01T01:00:00Z'))
    config = load_config(path)
    config.raw['notification'] = {'enabled': True, 'channels': {'feishu': {'enabled': True}}}
    sent = []
    class Response:
        status_code = 200
        def json(self):
            return {'code': 0}
    def capture(url, card, **kwargs):
        sent.append(card)
        return Response()
    monkeypatch.setattr('kenradar.notification.feishu._post_feishu_json_with_retry', capture)
    result = DailySummaryService(db, config).send('2099-01-01')
    assert len(sent) == 1
    assert 'private-retry-fixture' not in str(sent)
    assert result['reported_failed'] == 0 and result['api_accepted']
