from types import SimpleNamespace
from test_sqlite_v2 import sqlite_db
from kenradar.core.workflow import Workflow


def test_research_queues_only_successful_current_notes_idempotently(sqlite_db, tmp_path):
    db, _ = sqlite_db
    creator = db.upsert_creator('douyin', 'fixture', 'fixture', '')
    job = db.create_research_job('douyin', creator, 'fixture', 0, None, None, False, False)
    for identity, state in [('001', 'success'), ('002', 'failed')]:
        db.upsert_content_item('douyin', identity, creator)
        note = tmp_path / (identity + '.md')
        note.write_text('verified note ' + identity, encoding='utf-8')
        db.upsert_summary(identity, '{"brief_summary":"verified"}', str(note), 'fixture', 'success')
        db.upsert_research_job_item(job, identity, state)
    w = object.__new__(Workflow)
    w.database = db
    w.config = SimpleNamespace(get=lambda key, default=None: True if key == 'publishing.github_sync.enabled' else default)
    first = w.publish_research_job(job)
    second = w.publish_research_job(job)
    assert first['publication_task_ids'] == second['publication_task_ids']
    assert len(first['publication_task_ids']) == 1
    assert not first['github_synced']
    task = db.get_task_run(first['publication_task_ids'][0])
    assert task['task_type'] == 'publish_content'
    assert task['payload_json']['push'] is False
    assert task['payload_json']['content_item_id'] == db.find_content_item('douyin', '001')['id']
