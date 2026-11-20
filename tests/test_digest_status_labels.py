from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.notification.daily import DailySummaryService


def test_digest_distinguishes_processing_publication_retry_and_pause(sqlite_db):
    db, path = sqlite_db
    sub = db.upsert_source_subscription(platform='douyin',source_type='creator',source_key='fixture',display_name='fixture')
    ids = []
    for index, kind in enumerate(['process_url','publish_content','process_url','process_url']):
        task = db.enqueue_task_run(kind, {'subscription_id': sub, 'platform':'douyin','external_content_id':str(index)}, 'fixture', priority=100 if index==3 else 50)
        ids.append(task['id'])
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed): db.fail_task_run(claimed['id'], 'temporary', retryable=True)
    db.request_task_pause(ids[2])
    result = DailySummaryService(db,load_config(path)).build('2026-11-05',task_ids=ids)
    assert result['pending'] == 4
    assert result['processing_pending'] == 2
    assert result['publication_pending'] == 1
    assert result['paused_count'] == 1
    assert result['retrying_count'] == 1
    assert result['failed_content'] == 0
