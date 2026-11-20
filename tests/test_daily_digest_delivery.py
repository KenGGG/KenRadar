import pytest
from test_sqlite_v2 import sqlite_db


def test_daily_delivery_is_durable_and_checks_explicit_business_receipt(sqlite_db):
    from kenradar.notification.daily import DailyDigestDelivery
    db=sqlite_db[0]; calls=[]
    class Response:
        status_code=200
        def json(self): return {'code':0,'msg':'success'}
    def send(payload): calls.append(payload); return Response()
    payload={'msg_type':'interactive','card':{'header':{'template':'blue'}}}
    first=DailyDigestDelivery(db,send).deliver('2026-10-25',payload)
    second=DailyDigestDelivery(db,send).deliver('2026-10-25',payload)
    assert len(calls)==1
    assert first['api_accepted'] and first['receipt']['code']==0
    assert first['message_id'] is None and not first['recipient_visible_verified']
    assert second['skipped']


def test_daily_business_rejection_retries_delivery_only(sqlite_db):
    from kenradar.notification.daily import DailyDigestDelivery
    db=sqlite_db[0]; calls=[]
    class Response:
        status_code=200
        def json(self): return {'code':100 if len(calls)==1 else 0}
    def send(payload): calls.append(payload); return Response()
    service=DailyDigestDelivery(db,send)
    with pytest.raises(RuntimeError,match='REJECTED'):
        service.deliver('2026-10-25',{'msg_type':'interactive'})
    assert service.deliver('2026-10-25',{'msg_type':'interactive'})['api_accepted']
    assert len(calls)==2


def test_empty_daily_summary_does_not_claim_no_updates_without_a_verified_scan(sqlite_db):
    from kenradar.notification.daily import DailySummaryService
    from kenradar.core.config import load_config
    db,path=sqlite_db
    result=DailySummaryService(db,load_config(path)).build('2026-10-25')
    assert result['source_verified'] is False
    text=str(result['payload'])
    assert '未取得成功的来源扫描' in text
    assert '本时段暂无更新' not in text
    assert result['verified_count']==0


def test_daily_summary_reports_pending_and_failures_without_failing_delivery_again(sqlite_db,monkeypatch):
    from kenradar.notification import daily
    from kenradar.core.config import load_config
    db,path=sqlite_db; config=load_config(path)
    config.raw['notification']={'enabled':True,'channels':{'feishu':{'enabled':True,'webhook_url':'https://example.invalid/test'}}}
    service=daily.DailySummaryService(db,config)
    monkeypatch.setattr(service,'build',lambda *a,**k:{'pending':1,'failed':1,'verified_count':0,'source_verified':False,'items':[],'payload':{'msg_type':'interactive'}})
    class Response:
        status_code=200
        def json(self):return {'code':0}
    monkeypatch.setattr('kenradar.notification.feishu._post_feishu_json_with_retry',lambda *a,**k:Response())
    result=service.send('2026-10-25')
    assert result['api_accepted'] and result['reported_failed']==1 and result['pending']==1
    assert result.get('failed',0)==0


def test_recovered_item_is_not_success_until_exact_public_artifact_verified(sqlite_db,monkeypatch):
    from kenradar.notification.daily import DailySummaryService
    from kenradar.core.config import load_config
    db,path=sqlite_db;config=load_config(path)
    old=db.enqueue_task_run('process_url',{'aweme_id':'1234567890123456789','platform':'douyin'},'isolated prior failure',idempotency_key='isolated-original')
    claimed=db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):db.fail_task_run(old['id'],'fixture failure',retryable=False)
    row=db.enqueue_task_run('retry_summary',{'aweme_id':'1234567890123456789','platform':'douyin'},'isolated recovery',idempotency_key='isolated-recovered')
    claimed=db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):db.complete_task_run(row['id'],{'status':'success'})
    monkeypatch.setattr(db,'find_content_item',lambda *a:{'id':900})
    monkeypatch.setattr(db,'get_current_bundle',lambda *a:{'content':{'content_id':'1234567890123456789'},'analysis':{'analysis_status':'success','result_json':{'brief_summary':'fixture summary'}},'note':{'note_path':str(path.parent.parent/'notes/douyin/fixture/note.md')}})
    service=DailySummaryService(db,config)
    monkeypatch.setattr(service,'verify_publication',lambda *a:{'verified':False})
    result=service.build('2026-10-25',task_ids=[old['id'],row['id']])
    assert result['verified_count']==0 and result['pending']==1
