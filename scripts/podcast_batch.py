"""Queue an authorized RSS backfill and prefetch audio for the existing worker.

This finite helper only downloads media. ASR, AI, delivery and task leases stay
with KenRadar's persistent worker. Its manifest permits restart after failure.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import time

from sqlalchemy import select, update

from kenradar.core.config import load_config
from kenradar.storage import create_database
from kenradar.storage.sqlite_database import utc_now
from kenradar.sources.base import ContentItem
from kenradar.sources.xiaoyuzhou.adapter import XiaoyuzhouAdapter
from kenradar.sources.xiaoyuzhou.audio_downloader import AudioDownloader


def save(path, value):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf8')
    temporary.replace(path)


def completed(db, external_id):
    content = db.find_content_item('xiaoyuzhou', external_id)
    if not content:
        return False
    bundle = db.get_current_bundle(content['id'])
    return ((bundle.get('analysis') or {}).get('status') == 'success'
            and Path((bundle.get('note') or {}).get('note_path') or '').is_file())


def prepare(config, subscriptions, manifest):
    db = create_database(config)
    old_tasks = db.list_task_runs(limit=10000)
    tasks = {}
    for task in reversed(old_tasks):
        payload = task.get('payload_json') or {}
        if payload.get('platform') == 'xiaoyuzhou' and payload.get('external_content_id'):
            tasks[str(payload['external_content_id'])] = task
    rows, seen = [], set()
    for sid in subscriptions:
        source = db.get_source_subscription(sid)
        if not source or source['platform'] != 'xiaoyuzhou':
            raise ValueError('Expected an existing podcast subscription')
        items = XiaoyuzhouAdapter(config).resolve_source(source['feed_url'])
        for item in items:
            external = str(item.content_id)
            if external in seen:
                continue
            seen.add(external)
            done = completed(db, external)
            task = tasks.get(external)
            if not done:
                if task and task['status'] in {'failed', 'paused'}:
                    db.resume_task_run(task['id'])
                elif task and task['status'] == 'retry_wait':
                    table = db.table('task_run')
                    with db.connect(write=True) as conn:
                        conn.execute(update(table).where(table.c.id == task['id'], table.c.status == 'retry_wait').values(
                            available_at=utc_now(), updated_at=utc_now()))
                elif not task or task['status'] in {'success', 'cancelled', 'skipped'}:
                    suffix = ':authorized-repair-20261026' if task else ''
                    task = db.enqueue_task_run('process_url', {
                        'url': item.source_url, 'platform': 'xiaoyuzhou', 'external_content_id': external,
                        'subscription_id': sid, 'discovery_source': 'authorized_history',
                        'push': False, 'force': False, 'batch_label': 'houxue-both-20261026'},
                        message=f'{source["display_name"]}：{item.original_title}', requested_by='user', priority=85,
                        idempotency_key='process-url:' + item.source_url + suffix)
            rows.append({'subscription_id': sid, 'show': source['display_name'], 'item': asdict(item),
                         'completed_before_batch': done, 'task_id': task['id'] if task else None,
                         'download_status': 'completed_note' if done else 'pending'})
    result = {'created_at': utc_now(), 'download_workers': 4, 'items': rows}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    save(manifest, result)
    return {'episodes': len(rows), 'already_completed': sum(r['completed_before_batch'] for r in rows),
            'shows': dict(Counter(r['show'] for r in rows))}


def download_one(config, row):
    if row['completed_before_batch']:
        return {'download_status': 'completed_note'}
    data = dict(row['item'])
    if data.get('published_at'):
        data['published_at'] = datetime.fromisoformat(data['published_at'])
    item = ContentItem(**data)
    db = create_database(config)
    try:
        if completed(db, item.content_id):
            return {'download_status': 'completed_note'}
        if db.get_successful_transcript(item.content_id, platform='xiaoyuzhou'):
            return {'download_status': 'transcript_ready'}
        # An older worker may still download without the new per-ID lock.
        task = db.get_task_run(row['task_id']) if row['task_id'] else None
    finally:
        db.close()
    if task and task['status'] == 'running':
        return {'download_status': 'active_worker'}
    downloader = AudioDownloader(config)
    for attempt in range(3):
        path = downloader.download(item)
        if path:
            return {'download_status': 'downloaded', 'audio_path': str(path), 'audio_bytes': path.stat().st_size}
        time.sleep(attempt + 1)
    return {'download_status': 'failed', 'error': item.failure_reason}


def download(config, manifest, workers=4, retry_failed=False):
    state = json.loads(manifest.read_text(encoding='utf8'))
    candidates = [row for row in state['items'] if not retry_failed or row['download_status'] in {'failed', 'pending', 'active_worker'}]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix='podcast-prefetch') as pool:
        pending = {pool.submit(download_one, config, row): row for row in candidates}
        for index, future in enumerate(as_completed(pending), 1):
            row = pending[future]
            try:
                row.update(future.result())
            except Exception as exc:
                row.update(download_status='failed', error=str(exc))
            row['checked_at'] = utc_now()
            record_prefetch_progress(config, row)
            save(manifest, state)
            print(json.dumps({'finished': index, 'total': len(pending), 'show': row['show'],
                              'external_id': row['item']['content_id'], 'status': row['download_status']}, ensure_ascii=False), flush=True)
    return dict(Counter(row['download_status'] for row in state['items']))


def record_prefetch_progress(config, row):
    """Expose ready artifacts without falsely marking a queued task as running."""
    status = row.get('download_status')
    if status not in {'downloaded', 'transcript_ready'} or not row.get('task_id'):
        return
    db = create_database(config)
    table = db.table('task_run')
    try:
        with db.connect(write=True) as conn:
            task = conn.execute(select(table).where(table.c.id == row['task_id'])).fetchone()
            if not task or task['status'] not in {'queued', 'retry_wait', 'paused'}:
                return
            if str((task['payload_json'] or {}).get('external_content_id') or '') != str(row['item']['content_id']):
                return
            progress = dict(task['progress_json'] or {})
            progress['prefetch'] = {'status': status, 'checked_at': row.get('checked_at') or utc_now()}
            conn.execute(update(table).where(table.c.id == row['task_id']).values(progress_json=json.dumps(progress,ensure_ascii=False)))
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'download'])
    parser.add_argument('--config', default='config/config.yaml')
    parser.add_argument('--subscriptions', nargs='+', type=int, default=[2, 3])
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=[1, 2, 3, 4], default=4)
    parser.add_argument('--retry-failed', action='store_true')
    args = parser.parse_args()
    config = load_config(args.config)
    result = (prepare(config, args.subscriptions, args.manifest) if args.action == 'prepare'
              else download(config, args.manifest, args.workers, args.retry_failed))
    print(json.dumps(result, ensure_ascii=False))
