import pytest
from sqlalchemy import update
from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.web.run_center import load_run_center


def test_only_later_verified_scan_resolves_same_day_failure(sqlite_db):
    db, path = sqlite_db
    old = db.enqueue_task_run('scan_sources', {'day': '2026-11-01'}, 'old')
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):
        db.fail_task_run(old['id'], 'RSS timeout', retryable=False)
    later = db.enqueue_task_run('scan_sources', {'day': '2026-11-01'}, 'later')
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):
        db.complete_task_run(later['id'], {'source_verified': False})
    assert load_run_center(load_config(path), section='attention')['total'] == 1
    table = db.table('task_run')
    with db.connect(write=True) as conn:
        conn.execute(update(table).where(table.c.id == later['id']).values(stats_json='{"source_verified":true}'))
    assert load_run_center(load_config(path), section='attention')['total'] == 0
    assert db.get_task_run(old['id'])['last_error'] == 'RSS timeout'


def test_rss_retries_transport_but_not_permanent_http_error(monkeypatch):
    import requests
    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise requests.Timeout('temporary')
        response = requests.Response()
        response.status_code = 200
        response._content = b'<rss>fixture</rss>'
        return response
    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr('time.sleep', lambda _: None)
    assert XiaoyuzhouConnector(None)._fetch_text('https://example.invalid/rss') == '<rss>fixture</rss>'
    assert len(calls) == 3
    def denied(*args, **kwargs):
        response = requests.Response()
        response._content_consumed = True
        response.status_code = 403
        return response
    monkeypatch.setattr(requests, 'get', denied)
    with pytest.raises(requests.HTTPError):
        XiaoyuzhouConnector(None)._fetch_text('https://example.invalid/rss')


def test_each_slot_enqueues_one_digest_and_uses_distinct_delivery_keys(sqlite_db, monkeypatch):
    import asyncio
    from datetime import datetime
    from kenradar.scheduler import scheduler
    from kenradar.notification.daily import DailyDigestDelivery
    db, path = sqlite_db
    config = load_config(path)
    config.raw['schedule'].update(mode='subscription_daily', notification_mode='every_slot', times=['09:00', '12:00', '15:00', '18:00', '21:00'])
    monkeypatch.setattr(scheduler, 'create_database', lambda _: db)
    monkeypatch.setattr(scheduler, '_now_in_tz', lambda _: datetime(2026, 11, 4, 12))
    for slot in ('09:00', '12:00', '12:00'):
        asyncio.run(scheduler._trigger_due_run(config, slot, grace_minutes=10, use_persistent_queue=True))
    rows = db.list_task_runs(limit=20)
    assert len(rows) == 4
    assert {r['payload_json']['due_time'] for r in rows if r['task_type'] == 'daily_summary'} == {'09:00', '12:00'}
    class Response:
        status_code = 200
        def json(self): return {'code': 0}
    calls = []
    service = DailyDigestDelivery(db, lambda payload: calls.append(payload) or Response())
    for slot in ('09:00', '12:00', '12:00'):
        service.deliver('2026-11-04', {}, due_time=slot)
    assert len(calls) == 2


def test_podcast_ai_recovery_uses_retained_asr_and_original_creator_once(sqlite_db, tmp_path):
    from kenradar.core.source_monitor import SourceMonitorService
    from kenradar.storage.sqlite_database import utc_now
    db, path = sqlite_db
    config = load_config(path)
    config.raw['schedule'].update(mode='subscription_daily', recovery_cooldown_minutes=0)
    db.config = config
    creator = db.upsert_creator('xiaoyuzhou', 'original-show', 'Original show', '')
    db.upsert_content_item('xiaoyuzhou', 'episode', creator, title='Episode')
    db.upsert_transcript('episode', 'retained ASR', '', '', 'fixture', 'success', platform='xiaoyuzhou')
    db.upsert_summary('episode', '', '', 'fixture', 'failed', error_message='HTTP 502', platform='xiaoyuzhou')
    old = db.enqueue_task_run('process_url', {'platform':'xiaoyuzhou', 'external_content_id':'episode', 'discovery_source':'monitor'}, 'old')
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed): db.fail_task_run(old['id'], 'HTTP 502', retryable=False)
    monitor = SourceMonitorService(db, {})
    assert monitor._enqueue_failed_stage_recovery('xiaoyuzhou', 'episode', 3)
    assert not monitor._enqueue_failed_stage_recovery('xiaoyuzhou', 'episode', 3)
    recovery = next(r for r in db.list_task_runs(limit=20) if r['task_type'] == 'podcast_organize')
    assert recovery['payload_json']['item']['creator_id'] == 'original-show'
    assert recovery['payload_json']['item']['creator'] == 'Original show'
    assert db.get_successful_transcript('episode', platform='xiaoyuzhou')['text_content'] == 'retained ASR'


def test_publication_service_routes_single_article_without_bulk_sync(sqlite_db, tmp_path, monkeypatch):
    from kenradar.publishing.service import PublicationService
    from kenradar.publishing.static_site import StaticSitePublisher
    from kenradar.publishing.github_sync import GithubSyncManager
    db, path = sqlite_db
    config = load_config(path)
    config.raw['publishing'] = {'github_pages': {'enabled': True, 'output_dir': str(tmp_path / 'site'), 'public_base_url': 'https://example.invalid'}, 'github_sync': {'enabled': True}}
    creator = db.upsert_creator('douyin', 'fixture', 'Fixture', '')
    cid = db.upsert_content_item('douyin', 'episode', creator)
    note = tmp_path / 'note.md'
    note.write_text('# Fixture', encoding='utf8')
    db.upsert_summary('episode', '{"brief_summary":"fixture"}', str(note), 'fixture', 'success')
    n = db.table('content_note')
    with db.connect(write=True) as conn: conn.execute(update(n).values(content_sha256='a'*64))
    events = []
    publisher = StaticSitePublisher(config)
    html = tmp_path / 'article.html'
    def render(*args, **kwargs):
        assert kwargs['update_index'] is False
        html.write_text('<html>fixture</html>', encoding='utf8')
    monkeypatch.setattr(publisher, 'publish_markdown', render)
    monkeypatch.setattr(publisher, 'html_path_for', lambda _: html)
    monkeypatch.setattr(publisher, 'public_url_for', lambda _: 'https://example.invalid/article')
    monkeypatch.setattr(GithubSyncManager, 'sync_single_article', lambda *args: events.append('single') or {'pushed':True, 'artifact_sha256':'b'*64})
    def bulk(): raise AssertionError('Must not publish unrelated local commits')
    PublicationService(db, publisher, bulk).publish_content(cid)
    receipt = db.publications.find_success(cid, 'a'*64)
    assert receipt['idempotency_key'].endswith(':html:' + 'b'*64)
    assert events == ['single']
