"""Recover retained ASR inputs and failed analyses, without publishing or sending."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
from pathlib import Path
import shutil
import sqlite3

from kenradar.core.config import AppConfig, load_config
from kenradar.core.workflow import Workflow
from kenradar.jobs.worker import TaskWorker


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    base = load_config('config/config.yaml')
    raw = deepcopy(base.raw)
    raw['notification']['enabled'] = False
    raw['notification']['channels']['feishu']['enabled'] = False
    raw['publishing']['github_pages']['enabled'] = False
    raw['publishing']['github_sync']['enabled'] = False
    raw['ai'].setdefault('whisper', {})['cleanup_video'] = False
    config = AppConfig(raw=raw, path=base.path)
    root = config.resolve_path('data/test-migration/recovery-129')
    root.mkdir(parents=True, exist_ok=True)
    database_path = config.data_dir / 'db/kenradar.sqlite3'
    if not (root / 'before.sqlite3').exists():
        with sqlite3.connect(database_path) as src, sqlite3.connect(root / 'before.sqlite3') as dst:
            src.backup(dst)
        shutil.copytree(config.data_dir / 'notes', root / 'notes-before', dirs_exist_ok=True)
    workflow = Workflow(config)
    creator_uid = 'MS4wLjABAAAA_C2VXT1FT00QgTcH9v14uws4BQRaUXjKMP6JOD-UvWA'
    with workflow.database.connect() as conn:
        scope = [str(row['content_id']) for row in conn.execute("SELECT ci.content_id FROM content_item ci JOIN creator cr ON cr.id=ci.creator_id LEFT JOIN ai_analysis a ON a.content_item_id=ci.id AND a.analysis_type='summary' WHERE cr.platform_uid=? AND (a.status IS NULL OR a.status<>'success')", (creator_uid,)).fetchall()]
    if len(scope) > 45:
        raise RuntimeError('Unexpected scope greater than 45 failed items')
    (root / 'selected-content-ids.json').write_text(json.dumps(scope, indent=2), encoding='utf-8')
    with workflow.database.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT ci.content_id,ci.title,ci.local_path,ci.extra,ci.creator_id,cr.nickname FROM content_item ci JOIN creator cr ON cr.id=ci.creator_id LEFT JOIN transcript t ON t.content_item_id=ci.id WHERE cr.platform_uid=? AND (t.status IS NULL OR t.status<>'success')",
            ('MS4wLjABAAAA_C2VXT1FT00QgTcH9v14uws4BQRaUXjKMP6JOD-UvWA',)).fetchall()]
    results = []
    for row in rows:
        aweme = json.loads(row['extra']) if isinstance(row['extra'], str) else row['extra']
        metadata = workflow._video_metadata(aweme, row['nickname'], row['creator_id'])
        result = asyncio.run(workflow.transcriber.transcribe(row['content_id'], Path(row['local_path']), metadata))
        results.append({'id': row['content_id'], 'status': result.get('status'), 'chars': len(result.get('text') or ''), 'error': result.get('error'), 'no_speech': result.get('no_speech', False)})
        (root / 'transcripts.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print('RECOVERY_TRANSCRIPT', json.dumps(results[-1], ensure_ascii=True), flush=True)
    task = workflow.database.enqueue_task_run('summarize_existing', {'limit': 45, 'content_ids': scope}, 'Recover only selected failed Quantgirl analyses from retained transcripts', requested_by='cli', priority=70, max_attempts=1)
    record = workflow.database.claim_next_task_run('recovery-129', lease_seconds=300)
    if not record or record['id'] != task['id']:
        raise RuntimeError('Unexpected queued task; no concurrent recovery allowed')
    with workflow.database.lease_scope(record):
        TaskWorker(str(base.path), worker_name='recovery-129')._execute(config, workflow.database, record)
    print('RECOVERY_TASK', task['id'], flush=True)
    with workflow.database.connect() as conn:
        status = conn.execute('SELECT status FROM task_run WHERE id=?', (task['id'],)).fetchone()['status']
    if status != 'success':
        raise SystemExit(f'Recovery task {task["id"]} ended with status={status}; inspect its persisted error.')


if __name__ == '__main__':
    main()
