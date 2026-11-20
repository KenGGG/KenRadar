import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.core.source_monitor import SourceMonitorService
from kenradar.sources.contracts import ContentDescriptor, ContentPage


def test_rss_discovery_persists_audio_and_dispatches_without_web_reresolution(sqlite_db, monkeypatch):
    from kenradar.jobs.handlers import _execute_task_run_raw
    db, path = sqlite_db
    sub = db.upsert_source_subscription(platform='xiaoyuzhou', source_type='feed', source_key='feed',
        display_name='fixture', source_url='https://feed.example/podcast.xml', feed_url='https://feed.example/podcast.xml')
    item = ContentDescriptor('xiaoyuzhou', 'rss-guid-0001', 'feed', 'episode', None, 'audio',
        'https://publisher.example/episode', media_url='https://media.example/audio.mp3')
    class Connector:
        async def list_recent(self, *args, **kwargs):
            return ContentPage(items=[item], has_more=False)
    monitor = SourceMonitorService(db, {'xiaoyuzhou': Connector()})
    asyncio.run(monitor._scan_one(Connector(), db.get_source_subscription(sub)))
    asyncio.run(monitor._scan_one(Connector(), db.get_source_subscription(sub)))
    tasks = db.list_task_runs(limit=10)
    assert len(tasks) == 1
    payload = tasks[0]['payload_json']
    assert payload['item']['media_url'] == item.media_url
    assert payload['item']['content_id'] == item.external_content_id
    assert payload['push'] is False
    stage = AsyncMock(return_value={'status': 'success'})
    monkeypatch.setattr('kenradar.jobs.podcast_stages.execute_podcast_stage', stage)
    asyncio.run(_execute_task_run_raw(SimpleNamespace(), 'process_url', payload))
    assert stage.call_args.args[1] == 'podcast_process'


@pytest.mark.parametrize('failure_stage', ['download', 'transcript', 'missing_analysis'])
def test_failed_subscribed_rss_download_gets_bounded_snapshot_recovery(sqlite_db, failure_stage):
    db, path = sqlite_db
    config = load_config(path)
    config.raw['schedule'].update(mode='subscription_daily', recovery_cooldown_minutes=0)
    db.config = config
    creator = db.upsert_creator('xiaoyuzhou', 'feed', 'fixture', '')
    cid = db.upsert_content_item('xiaoyuzhou', 'rss-failure', creator, content_type='audio',
        download_status='failed', source_url='https://publisher.example/episode', media_url='https://media.example/audio.mp3')
    if failure_stage != 'download':
        db.upsert_transcript('rss-failure', 'verified transcript' if failure_stage == 'missing_analysis' else '', '', '', 'fixture', 'success' if failure_stage == 'missing_analysis' else 'failed', platform='xiaoyuzhou')
    task = db.enqueue_task_run('process_url', {'platform':'xiaoyuzhou','external_content_id':'rss-failure','discovery_source':'monitor'}, 'initial')
    claimed = db.claim_next_task_run('fixture')
    with db.lease_scope(claimed):
        db.fail_task_run(task['id'], 'download failure', retryable=False)
    monitor = SourceMonitorService(db, {})
    assert monitor._enqueue_failed_stage_recovery('xiaoyuzhou', 'rss-failure', 1)
    assert not monitor._enqueue_failed_stage_recovery('xiaoyuzhou', 'rss-failure', 1)
    recovered = [x for x in db.list_task_runs(limit=10) if x['id'] != task['id']][0]
    assert recovered['task_type'] == ('podcast_organize' if failure_stage == 'missing_analysis' else 'process_url')
    assert recovered['payload_json']['item']['media_url'] == 'https://media.example/audio.mp3'


def test_podcast_snapshot_rejects_identity_mismatch_before_processing():
    from kenradar.jobs.podcast_stages import execute_podcast_stage
    with pytest.raises(ValueError, match='identity mismatch'):
        asyncio.run(execute_podcast_stage(SimpleNamespace(), 'podcast_process',
            {'external_content_id':'expected','item':{'platform':'xiaoyuzhou','content_id':'other'}}))


def test_private_podcast_snapshot_never_enters_external_processing(sqlite_db):
    from kenradar.jobs.podcast_stages import execute_podcast_stage
    db, path = sqlite_db
    w = SimpleNamespace(database=db, transcriber=SimpleNamespace(), config=load_config(path))
    item = {'platform':'xiaoyuzhou','creator':'fixture','creator_id':'feed','content_id':'private',
        'source_url':'https://publisher.example/private','original_title':'fixture','published_at':None,
        'media_type':'audio','duration':10,'description':'','cover_url':'',
        'raw_metadata':{'hermes_private':True}}
    with pytest.raises(ValueError, match='PRIVATE_CONTENT'):
        asyncio.run(execute_podcast_stage(w, 'podcast_process', {'external_content_id':'private','item':item}))
