"""Explicit one-time handoff to the existing durable worker; restartable enqueue."""
import json
from pathlib import Path

from kenradar.core.config import load_config
from kenradar.storage import create_database
from scripts.podcast_batch import completed, save


def prepare(config, manifest):
    db = create_database(config)
    records = json.loads(manifest.read_text(encoding='utf8'))['items']
    result = {'transcribe': [], 'codex': [], 'skipped': [], 'replaced': []}
    try:
        ids = {r['task_id'] for r in records if r.get('task_id')}
        if any(t['id'] in ids and t['status'] == 'running' for t in db.list_task_runs(limit=10000)):
            raise RuntimeError('Wait for the current original podcast task to finish before handoff')
        for row in records:
            external = row['item']['content_id']
            if completed(db, external):
                result['skipped'].append(external)
            else:
                payload = {'item': row['item'], 'platform': 'xiaoyuzhou', 'external_content_id': external,
                           'subscription_id': row['subscription_id'], 'push': False,
                           'batch_label': 'houxue-terra-20261026', 'original_task_id': row.get('task_id')}
                if not db.get_successful_transcript(external, platform='xiaoyuzhou'):
                    task = db.enqueue_task_run('podcast_transcribe', payload,
                        message=f"GPU 转录｜{row['show']}｜{row['item']['original_title']}", requested_by='user',
                        priority=200, idempotency_key=f'houxue-gpu-20261026:{external}', max_attempts=2)
                    result['transcribe'].append(task['id'])
                task = db.enqueue_task_run('podcast_codex', payload,
                    message=f"Terra 整理｜{row['show']}｜{row['item']['original_title']}", requested_by='user',
                    priority=80, idempotency_key=f'houxue-terra-20261026:{external}', max_attempts=2)
                result['codex'].append(task['id'])
            if row.get('task_id'):
                old = db.get_task_run(row['task_id'])
                if old and old['status'] in {'queued', 'retry_wait', 'paused'}:
                    db.request_task_cancel(old['id'], '已转入独立 GPU 转录 / Codex Terra 阶段，保留原任务审计')
                    result['replaced'].append(old['id'])
        (config.data_dir / 'runtime').mkdir(parents=True, exist_ok=True)
        save(config.data_dir / 'runtime' / 'podcast-terra-stages.json', result)
        return {key: len(value) for key, value in result.items()}
    finally:
        db.close()


if __name__ == '__main__':
    print(json.dumps(prepare(load_config('config/config.yaml'),
        Path('data/fresh/runtime/podcast-batch-20261026.json')), ensure_ascii=False))
