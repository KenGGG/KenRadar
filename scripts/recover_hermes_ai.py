"""Recover the identified failed AI item without publication or notifications."""
from copy import deepcopy
from pathlib import Path
import sqlite3
import shutil
import logging
from kenradar.core.config import AppConfig,load_config
from kenradar.core.workflow import Workflow
from kenradar.jobs.worker import TaskWorker

def main():
    logging.basicConfig(level=logging.INFO)
    base=load_config('config/config.yaml')
    root=base.resolve_path('data/test-migration/hermes-ai-repair')
    root.mkdir(parents=True,exist_ok=True)
    if not (root/'before.sqlite3').exists():
        with sqlite3.connect(base.data_dir/'db/kenradar.sqlite3') as src, sqlite3.connect(root/'before.sqlite3') as dst: src.backup(dst)
    raw=deepcopy(base.raw)
    raw['notification']['enabled']=False
    raw['publishing']['github_pages']['enabled']=False
    raw['publishing']['github_sync']['enabled']=False
    config=AppConfig(raw=raw,path=base.path)
    workflow=Workflow(config)
    original_normalize=workflow.organizer._normalize_provider_json_output
    def capture_output(text, provider_name=''):
        (root/'latest-provider-output.txt').write_text(text,encoding='utf-8')
        return original_normalize(text,provider_name)
    workflow.organizer._normalize_provider_json_output=capture_output
    original_post=workflow.organizer._post_with_retry
    def capture_response(url, **kwargs):
        response=original_post(url,**kwargs)
        import json
        data=response.json()
        (root/'latest-response-metadata.json').write_text(json.dumps({'usage':data.get('usage'),'finish_reasons':[x.get('finish_reason') for x in data.get('choices',[])]}),encoding='utf-8')
        return response
    workflow.organizer._post_with_retry=capture_response
    db=workflow.database
    aid='7694252203724262682'
    with db.connect() as conn:
        row=conn.execute("SELECT n.note_path FROM content_note n JOIN content_item c ON c.id=n.content_item_id WHERE c.content_id=?",(aid,)).fetchone()
    if row and Path(row['note_path']).exists() and not (root/'note-before.md').exists(): shutil.copy2(row['note_path'],root/'note-before.md')
    task=db.enqueue_task_run('summarize_existing',{'limit':1,'content_ids':[aid]},'Recover Hermes AI TLS failure',requested_by='cli',max_attempts=1,priority=70)
    record=db.claim_next_task_run('hermes-ai-repair',lease_seconds=300)
    assert record and record['id']==task['id']
    with db.lease_scope(record): TaskWorker(str(base.path),worker_name='hermes-ai-repair')._execute(config,db,record)
    with db.connect() as conn:
        row=conn.execute("SELECT a.status,n.note_path,t.text_content FROM content_item c JOIN ai_analysis a ON a.content_item_id=c.id JOIN content_note n ON n.content_item_id=c.id JOIN transcript t ON t.content_item_id=c.id WHERE c.content_id=?",(aid,)).fetchone()
    assert row['status']=='success', 'Real AI recovery remains incomplete'
    text=Path(row['note_path']).read_text(encoding='utf-8')
    assert row['text_content'].strip() in text and '> [!summary]' in text
    from sqlalchemy import update
    table=db.table('task_run')
    with db.connect(write=True) as conn: conn.execute(update(table).where(table.c.id==12,table.c.status=='failed').values(error_code='RESOLVED'))
    db.insert_state_transition('task_run',12,'failed','resolved',reason=f'Actual AI analysis and note verified after recovery task {task["id"]}',actor='cli')
    print(f'Real AI and note recovered for {aid}; task {task["id"]}; previous task 12 resolved.')

if __name__=='__main__': main()
