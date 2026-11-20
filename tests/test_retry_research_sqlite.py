from types import SimpleNamespace
from test_sqlite_v2 import sqlite_db
from kenradar.core.retry import RetryManager


def test_sqlite_recovery_updates_research_counts_without_touching_skipped(sqlite_db):
    db, _ = sqlite_db
    creator = db.upsert_blogger('https://www.douyin.com/user/fixture', 'fixture', 'fixture')
    for identity in ('001', '002'):
        db.insert_aweme(creator, {'aweme_id': identity, 'desc': 'fixture', 'create_time': 1790000000})
    job = db.create_research_job('douyin', creator, 'fixture', 0, None, None, False, False)
    db.upsert_research_job_item(job, '001', 'failed', 'old error')
    db.upsert_research_job_item(job, '002', 'skipped')
    db.update_research_job(job, status='partial_failed', failed_count=1, last_error='old error')
    RetryManager(SimpleNamespace(database=db)).sync_research_items_after_retry('001', True)
    result = db.get_research_job(job)
    assert result['status'] == 'completed'
    assert (result['total_count'], result['success_count'], result['skipped_count'], result['failed_count']) == (2, 1, 1, 0)
    assert result['last_error'] == ''
    assert {x['aweme_id']: x['status'] for x in db.list_research_job_items(job)} == {'001': 'success', '002': 'skipped'}
