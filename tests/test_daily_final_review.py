import asyncio
from pathlib import Path
from kenradar.core.config import load_config
from kenradar.core.source_monitor import SourceMonitorService
from test_sqlite_v2 import sqlite_db


def test_failed_publication_recovers_only_delivery_once_and_leaves_historical_notes_alone(sqlite_db):
    db,path=sqlite_db
    c=load_config(path);c.raw['schedule'].update(mode='subscription_daily',recovery_cooldown_minutes=0);db.config=c
    blogger=db.upsert_blogger(url='https://www.douyin.com/user/fixture',name='fixture',sec_uid='fixture',enabled=True)
    eid='1234567890123456789'
    db.insert_aweme(blogger,{'aweme_id':eid,'create_time':1792838124,'desc':'fixture'},status='done')
    item=db.find_content_item('douyin',eid)
    note=path.parent.parent/'note.md';note.write_text('# Retained fixture',encoding='utf8')
    db.upsert_transcript(eid,'retained ASR','','','fixture-asr','success')
    db.replace_analysis_and_note(item['id'],{'status':'success','model':'fixture','result_json':{'brief_summary':'fixture'}},{'note_path':str(note),'content_sha256':'abc'})
    service=SourceMonitorService(db,{})
    assert service._enqueue_failed_stage_recovery('douyin',eid,1) is False
    pub=db.publications.start(item['id'],'abc','publish:fixture');db.publications.fail(pub['id'],'push failed')
    assert service._enqueue_failed_stage_recovery('douyin',eid,1) is True
    assert service._enqueue_failed_stage_recovery('douyin',eid,1) is False
    rows=db.list_task_runs(limit=20)
    assert len(rows)==1 and rows[0]['task_type']=='publish_content'
    assert rows[0]['payload_json']['content_item_id']==item['id']
    assert db.get_successful_transcript(eid)['text_content']=='retained ASR'


def test_failed_source_backoff_does_not_turn_retry_into_successful_zero_scan(sqlite_db,monkeypatch):
    from types import SimpleNamespace
    from kenradar.jobs.handlers import execute_task_run
    db,path=sqlite_db;c=load_config(path);db.config=c
    db.upsert_subscription(platform='douyin',source_key='fixture',display_name='fixture',source_url='')
    class Denied:
        async def list_recent(self,*args,**kwargs):raise RuntimeError('SOURCE_DENIED')
    monkeypatch.setattr('kenradar.sources.registry.connectors_for_config',lambda config:{'douyin':Denied()})
    workflow=SimpleNamespace(database=db,config=c)
    first=asyncio.run(execute_task_run(workflow,'scan_sources',{'day':'2026-10-25'}))
    second=asyncio.run(execute_task_run(workflow,'scan_sources',{'day':'2026-10-25'}))
    assert first['failed']==1
    assert second['scanned']==0 and second['failed']==1
    assert second['source_verified'] is False
    assert db.list_source_subscriptions()[0]['consecutive_failures']==1


def test_digest_uses_scan_business_day_for_tasks_executed_across_midnight(sqlite_db):
    from kenradar.notification.daily import DailySummaryService
    db,path=sqlite_db;c=load_config(path)
    source=db.upsert_subscription(platform='douyin',source_key='fixture',display_name='fixture',source_url='')
    db.enqueue_task_run('process_url',{'platform':'douyin','aweme_id':'1234567890123456789','subscription_id':source,'day':'2099-01-01'},'fixture delayed across midnight')
    result=DailySummaryService(db,c).build('2099-01-01')
    assert result['pending']==1
    assert DailySummaryService(db,c).build('2099-01-02')['pending']==0


def test_scan_propagates_business_day_to_new_content_and_stage_recovery(sqlite_db,monkeypatch):
    from types import SimpleNamespace
    from kenradar.jobs.handlers import execute_task_run
    from kenradar.sources.contracts import ContentPage,ContentDescriptor
    db,path=sqlite_db;c=load_config(path);db.config=c
    db.upsert_subscription(platform='douyin',source_key='fixture',display_name='fixture',source_url='')
    class Connector:
        async def list_recent(self,*args,**kwargs):
            return ContentPage(items=[ContentDescriptor('douyin','1234567890123456789','fixture','fixture',None,'video','https://www.douyin.com/video/1234567890123456789')])
    monkeypatch.setattr('kenradar.sources.registry.connectors_for_config',lambda config:{'douyin':Connector()})
    asyncio.run(execute_task_run(SimpleNamespace(database=db,config=c),'scan_sources',{'day':'2099-01-01'}))
    assert db.list_task_runs(limit=10)[0]['payload_json']['day']=='2099-01-01'


def test_partial_source_scan_cannot_certify_backing_off_failed_subscription(sqlite_db,monkeypatch):
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace
    from kenradar.jobs.handlers import execute_task_run
    from kenradar.sources.contracts import ContentPage
    db,path=sqlite_db;c=load_config(path);db.config=c
    first=db.upsert_subscription(platform='douyin',source_key='bad',display_name='bad',source_url='')
    db.record_subscription_scan(first,success=False,next_check_at=datetime.now(timezone.utc)+timedelta(hours=2),last_error='denied')
    db.upsert_subscription(platform='douyin',source_key='good',display_name='good',source_url='')
    class Good:
        async def list_recent(self,*a,**k):return ContentPage(items=[])
    monkeypatch.setattr('kenradar.sources.registry.connectors_for_config',lambda c:{'douyin':Good()})
    result=asyncio.run(execute_task_run(SimpleNamespace(database=db,config=c),'scan_sources',{'day':datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d')}))
    assert result['scanned']==1 and result['source_verified'] is False and result['failed']==1


def test_publication_only_recovery_is_counted_in_daily_digest(sqlite_db):
    from kenradar.notification.daily import DailySummaryService
    db,path=sqlite_db;c=load_config(path)
    source=db.upsert_subscription(platform='douyin',source_key='fixture',display_name='fixture',source_url='')
    db.enqueue_task_run('publish_content',{'platform':'douyin','aweme_id':'1234567890123456789','subscription_id':source,'day':'2099-01-01','trigger':'monitor_recovery'},'fixture publication recovery')
    assert DailySummaryService(db,c).build('2099-01-01')['pending']==1


def test_obsolete_public_artifact_cannot_certify_new_unpublished_analysis(sqlite_db,monkeypatch):
    import hashlib
    from kenradar.notification.daily import DailySummaryService
    db,path=sqlite_db;c=load_config(path)
    note=path.parent.parent/'current.md';note.write_text('# New unpublished analysis',encoding='utf8')
    row=db.enqueue_task_run('process_url',{'aweme_id':'1234567890123456789'},'fixture')
    claimed=db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):db.complete_task_run(row['id'],{'status':'success'})
    monkeypatch.setattr(db,'find_content_item',lambda *a:{'id':900})
    monkeypatch.setattr(db,'get_current_bundle',lambda *a:{'content':{'id':900},'analysis':{'analysis_status':'success','result_json':{'brief_summary':'NEW analysis'}},'note':{'note_path':str(note),'content_sha256':hashlib.sha256(note.read_bytes()).hexdigest()}})
    monkeypatch.setattr(db.publications,'find_success',lambda *a:None)
    service=DailySummaryService(db,c)
    monkeypatch.setattr(service,'verify_publication',lambda *a:{'verified':True,'http':200})
    result=service.build('2026-10-25',task_ids=[row['id']])
    assert result['verified_count']==0 and result['pending']==1


def test_scheduler_uses_captured_slot_day_even_if_execution_crosses_midnight(sqlite_db,monkeypatch):
    from datetime import datetime
    from kenradar.scheduler import scheduler
    from kenradar.core.config import AppConfig
    db,path=sqlite_db
    c=AppConfig({'app':{'timezone':'Asia/Shanghai'},'schedule':{'mode':'subscription_daily','times':['09:00','21:00']}},path)
    monkeypatch.setattr(scheduler,'create_database',lambda config:db)
    monkeypatch.setattr(scheduler,'_now_in_tz',lambda config:datetime(2026,10,26,0,0))
    asyncio.run(scheduler._trigger_due_run(c,'21:00',grace_minutes=10,use_persistent_queue=True,business_day='2026-10-25'))
    assert {r['payload_json']['day'] for r in db.list_task_runs(limit=10)}=={'2026-10-25'}


def test_daily_process_success_durably_enqueues_publication_receipt_stage(sqlite_db):
    from types import SimpleNamespace
    from kenradar.jobs.handlers import execute_task_run
    db,path=sqlite_db;c=load_config(path);c.raw['schedule']['mode']='subscription_daily';db.config=c
    blogger=db.upsert_blogger(url='https://www.douyin.com/user/fixture',name='fixture',sec_uid='fixture',enabled=True)
    eid='1234567890123456789';db.insert_aweme(blogger,{'aweme_id':eid,'create_time':1792838124,'desc':'fixture'},status='done')
    item=db.find_content_item('douyin',eid);note=path.parent.parent/'current.md';note.write_text('# Retained note',encoding='utf8')
    db.upsert_transcript(eid,'retained ASR','','','fixture','success')
    db.replace_analysis_and_note(item['id'],{'status':'success','result_json':{'brief_summary':'fixture'}},{'note_path':str(note)})
    async def process(**kwargs):return {'status':'success','processed':1,'aweme_id':eid}
    workflow=SimpleNamespace(database=db,config=c,process_single_url=process)
    payload={'url':f'https://www.douyin.com/video/{eid}','platform':'douyin','external_content_id':eid,'subscription_id':1,'day':'2099-01-01','push':False,'force':False}
    for _ in range(2):asyncio.run(execute_task_run(workflow,'process_url',payload))
    tasks=db.list_task_runs(limit=10)
    assert len(tasks)==1 and tasks[0]['task_type']=='publish_content'
    assert tasks[0]['payload_json']['day']=='2099-01-01'
    assert db.get_current_bundle(item['id'])['note']['content_sha256']
    assert db.get_successful_transcript(eid)['text_content']=='retained ASR'


def test_publication_worker_uses_claimed_database_without_second_workflow(sqlite_db,monkeypatch):
    from kenradar.jobs import worker
    db,path=sqlite_db
    row=db.enqueue_task_run('publish_content',{'content_item_id':900},'isolated publication')
    def forbidden(config):raise AssertionError('No unfenced Workflow for publication')
    class Publication:
        def __init__(self,database,publisher,sync):
            assert database._lease.get()['id']==row['id']
        def publish_content(self,content_id):return {'status':'success'}
    monkeypatch.setattr(worker,'Workflow',forbidden)
    monkeypatch.setattr('kenradar.publishing.service.PublicationService',Publication)
    worker.TaskWorker(str(path)).run_once()
    assert db.get_task_run(row['id'])['status']=='success'


def test_acceptance_send_refuses_incomplete_preview_before_any_webhook(sqlite_db,monkeypatch):
    from kenradar.notification.daily import DailySummaryService
    db,path=sqlite_db;c=load_config(path);c.raw['notification']={'enabled':True,'channels':{'feishu':{'enabled':True}}}
    service=DailySummaryService(db,c)
    monkeypatch.setattr(service,'build',lambda *a,**k:{'source_verified':True,'verified_count':8,'pending':1,'failed':0,'payload':{'msg_type':'interactive'}})
    def forbidden(*a,**k):raise AssertionError('Must not contact webhook')
    monkeypatch.setattr('kenradar.notification.feishu._post_feishu_json_with_retry',forbidden)
    import pytest
    with pytest.raises(RuntimeError,match='ACCEPTANCE_INCOMPLETE'):service.send('2026-10-25',task_ids=list(range(37,46)),acceptance=True)
