import asyncio
from datetime import datetime
from pathlib import Path
from kenradar.core.config import AppConfig
from kenradar.scheduler import scheduler
from test_sqlite_v2 import sqlite_db


def test_missed_slots_catch_up_only_latest_slot_and_keep_original_times():
    times={'09:00','12:00','15:00','18:00','21:00'}
    assert scheduler._due_subscription_slot(datetime(2026,10,25,16,30),times)=='15:00'
    assert scheduler._due_subscription_slot(datetime(2026,10,25,8,30),times) is None
    assert scheduler._due_subscription_slot(datetime(2026,10,25,23,30),times)=='21:00'



def test_subscription_slots_use_one_durable_scan_authority_and_one_daily_digest(sqlite_db, monkeypatch):
    db=sqlite_db[0]
    c=AppConfig({'app':{'timezone':'Asia/Shanghai'},'schedule':{'mode':'subscription_daily','times':['09:00','12:00','15:00','18:00','21:00']}},Path('config/config.yaml'))
    monkeypatch.setattr(scheduler,'create_database',lambda config:db)
    monkeypatch.setattr(scheduler,'_now_in_tz',lambda config:datetime(2026,10,25,21,0))
    for _ in range(2):
        assert asyncio.run(scheduler._trigger_due_run(c,'21:00',grace_minutes=10,use_persistent_queue=True))=='queued'
    rows=db.list_task_runs(limit=50)
    assert sorted(r['task_type'] for r in rows)==['daily_summary','scan_sources']
    assert all(r['payload_json'].get('push') is False for r in rows if r['task_type']=='scan_sources')
    assert asyncio.run(scheduler._maybe_scan_sources(c,None)) is None


def test_scan_task_runs_existing_monitor_and_records_no_fake_success(sqlite_db):
    from types import SimpleNamespace
    from kenradar.jobs.handlers import execute_task_run
    db=sqlite_db[0]
    workflow=SimpleNamespace(database=db,config=db.config)
    result=asyncio.run(execute_task_run(workflow,'scan_sources',{'day':'2026-10-25','scan_scope':'full','push':False}))
    assert result['scanned']==0 and result['failed']==0
    assert result['source_verified'] is False


def test_incomplete_full_walk_never_enqueues_partial_discovery(sqlite_db):
    from kenradar.core.source_monitor import SourceMonitorService
    from kenradar.sources.contracts import ContentPage,ContentDescriptor
    db=sqlite_db[0]
    db.upsert_subscription(platform='douyin',source_key='fixture',display_name='fixture',source_url='')
    class Incomplete:
        async def list_recent(self,source,cursor=None):
            return ContentPage(items=[ContentDescriptor(platform='douyin',external_content_id='1234567890123456789',external_source_id='fixture',title='fixture',published_at=None,media_type='video',url='https://www.douyin.com/video/1234567890123456789')],has_more=True,next_cursor='same')
    result=asyncio.run(SourceMonitorService(db,{'douyin':Incomplete()}).scan_due_subscriptions(scan_scope='full'))
    assert result['failed']==1
    assert 'SOURCE_INCOMPLETE' in db.list_source_subscriptions()[0]['last_error']
    assert db.list_task_runs(limit=50)==[]


def test_daily_summary_task_honors_notification_off_without_sending(sqlite_db):
    from types import SimpleNamespace
    from kenradar.core.config import load_config
    from kenradar.jobs.handlers import execute_task_run
    db,path=sqlite_db
    result=asyncio.run(execute_task_run(SimpleNamespace(database=db,config=load_config(path)), 'daily_summary', {'day':'2026-10-25'}))
    assert result['api_accepted'] is False
    assert result['reason']=='notification_disabled'


def test_scan_worker_uses_claimed_database_not_unfenced_workflow(sqlite_db,monkeypatch):
    from kenradar.jobs import worker
    db,path=sqlite_db
    row=db.enqueue_task_run('scan_sources',{'day':'2026-10-25'},'isolated scan',idempotency_key='isolated-scan')
    def forbidden(config):
        raise AssertionError('New unfenced Workflow must not be created for delivery/scanning')
    monkeypatch.setattr(worker,'Workflow',forbidden)
    assert worker.TaskWorker(str(path)).run_once()
    updated=db.get_task_run(row['id'])
    assert updated['status']=='success'


def test_failed_summary_is_retried_once_without_download_or_asr(sqlite_db):
    from kenradar.core.source_monitor import SourceMonitorService
    from kenradar.core.config import load_config
    from kenradar.sources.contracts import ContentPage,ContentDescriptor
    db,path=sqlite_db
    config=load_config(path); config.raw['schedule'].update(mode='subscription_daily',recovery_cooldown_minutes=0)
    db.config=config
    blogger=db.upsert_blogger(url='https://www.douyin.com/user/fixture',name='fixture',sec_uid='fixture',enabled=True)
    aid='1234567890123456789'
    db.insert_aweme(blogger,{'aweme_id':aid,'create_time':1792838124,'desc':'fixture'},status='done')
    db.upsert_transcript(aid,'retained original ASR','','','fixture-asr','success')
    db.upsert_summary(aid,'','','fixture-organizer','failed','quality gate failed')
    class Connector:
        async def list_recent(self,source,cursor=None):
            return ContentPage(items=[ContentDescriptor('douyin',aid,'fixture','fixture',None,'video',f'https://www.douyin.com/video/{aid}')])
    service=SourceMonitorService(db,{'douyin':Connector()})
    for _ in range(2):
        asyncio.run(service._scan_one(Connector(),{'platform':'douyin','source_key':'fixture','id':1},scan_scope='full'))
    rows=db.list_task_runs(limit=50)
    assert len(rows)==1 and rows[0]['task_type']=='retry_summary'
    assert rows[0]['max_attempts']==3
    assert db.get_successful_transcript(aid)['text_content']=='retained original ASR'
