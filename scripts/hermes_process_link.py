"""Hermes command adapter: durable processing in KenRadar, one JSON result."""
import argparse
import json
import time
import uuid
import sys
from kenradar.core.config import load_config
from kenradar.storage import create_database
from kenradar.sources.registry import connector_for_url


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('--config',default='config/config.yaml')
    parser.add_argument('--timeout',type=int,default=1800)
    parser.add_argument('--retry',action='store_true',help='Create a fresh durable attempt; successful analysis is still reused')
    args=parser.parse_args()
    if connector_for_url(args.url) is None: parser.error('Unsupported source URL')
    db=create_database(load_config(args.config))
    task=db.enqueue_task_run('process_url',{'url':args.url,'push':False,'force':False,'requested_by':'hermes'},
        message='Hermes link research and GitHub Pages publication',requested_by='hermes',priority=100,
        idempotency_key='hermes-process-url:'+args.url+(':'+uuid.uuid4().hex if args.retry else ''))
    deadline=time.monotonic()+args.timeout
    while time.monotonic()<deadline:
        row=db.get_task_run(task['id'])
        if row['status'] in ('success','failed','cancelled','paused'):
            stats=row.get('stats_json') or {}
            if isinstance(stats,str): stats=json.loads(stats)
            ready=bool(stats.get('public_url_ready')) and bool(stats.get('public_url')) and bool(stats.get('github_synced'))
            result={'ok':row['status']=='success' and ready,'task_id':task['id'],
                'task_status':row['status'],'title':stats.get('title'),
                'public_url':stats.get('public_url',''),'public_url_ready':ready,
                'github_synced':bool(stats.get('github_synced')),
                'error':row.get('last_error') or ('' if ready else 'Public page not ready; inspect task result'),
                'result_endpoint':f'/api/task-run?id={task["id"]}'}
            print(json.dumps(result,ensure_ascii=False))
            raise SystemExit(0 if result['ok'] else 1)
        time.sleep(3)
    print(json.dumps({'ok':False,'task_id':task['id'],'task_status':row['status'],
        'error':'Wait timed out; durable task remains available','result_endpoint':f'/api/task-run?id={task["id"]}'}))
    raise SystemExit(1)

if __name__=='__main__': main()
