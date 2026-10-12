"""Resolve the failed recovery attempt only after verifying its actual results."""
import json
from pathlib import Path
from sqlalchemy import update
from kenradar.core.config import load_config
from kenradar.storage import create_database
from kenradar.storage.sqlite_database import utc_now
from kenradar.web.run_center import load_run_center
from scripts.verify_creator_recovery import main as verify


def main():
    verify()
    config = load_config('config/config.yaml')
    db = create_database(config)
    with db.connect() as conn:
        task = dict(conn.execute('SELECT * FROM task_run WHERE id=9').fetchone())
        assert task['task_type'] == 'summarize_existing' and task['status'] == 'failed'
        payload = task['payload_json']
        ids = (json.loads(payload) if isinstance(payload, str) else payload)['content_ids']
        assert set(ids) == {'7654201343392910643', '7055981437790555392'}
        for content_id in ids:
            row = conn.execute("SELECT a.status,n.note_path,t.status AS transcript_status FROM content_item c JOIN ai_analysis a ON a.content_item_id=c.id AND a.analysis_type='summary' JOIN content_note n ON n.content_item_id=c.id AND n.note_type='content' JOIN transcript t ON t.content_item_id=c.id WHERE c.content_id=?", (content_id,)).fetchone()
            assert row and row['status'] == 'success' and row['transcript_status'] == 'success'
            assert Path(row['note_path']).is_file()
    snapshot = config.resolve_path('data/test-migration/recovery-129/task-9-before-resolution.json')
    if not snapshot.exists():
        snapshot.write_text(json.dumps(task, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
    if task['error_code'] != 'RESOLVED':
        t = db.table('task_run')
        with db.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == 9, t.c.status == 'failed').values(error_code='RESOLVED', updated_at=utc_now()))
        db.insert_state_transition('task_run', 9, 'failed', 'resolved',
            reason='Verified both scoped content items have successful transcripts, AI analyses and real notes; superseded by successful recovery task 10.', actor='cli')
    print(json.dumps(load_run_center(config, section='attention'), ensure_ascii=True, default=str))


if __name__ == '__main__':
    main()
