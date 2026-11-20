from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import json
import time

from test_sqlite_v2 import sqlite_db
from kenradar.core.config import AppConfig, load_config
from kenradar.sources.base import ContentItem
from kenradar.sources.xiaoyuzhou.audio_downloader import AudioDownloader
from scripts.podcast_batch import prepare


def item(external='000000000000000000000001', title='title'):
    return ContentItem(platform='xiaoyuzhou',creator='Show',creator_id='show',content_id=external,
                       source_url='https://www.xiaoyuzhoufm.com/episode/'+external, original_title=title,
                       published_at=None, media_type='audio',duration=1,description='',cover_url=None,
                       media_url='https://example.test/audio.m4a')


def test_parallel_download_deduplicates_by_id_across_title_changes(tmp_path, monkeypatch):
    import requests
    calls=[]
    class Response:
        headers={'Content-Length':'5'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,**kwargs):
            time.sleep(.05)
            yield b'audio'
    def get(*args,**kwargs):
        calls.append(1)
        return Response()
    monkeypatch.setattr(requests,'get',get)
    cfg=AppConfig({'sources':{'xiaoyuzhou':{'audio_temp_dir':str(tmp_path/'audio')}}},tmp_path/'config.yaml')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(AudioDownloader(cfg).download,item(title=title)) for title in ['RSS title','page title']]
        paths=[f.result() for f in futures]
    assert paths[0]==paths[1] and len(calls)==1
    assert paths[0].read_bytes()==b'audio'
    assert not list((tmp_path/'audio').glob('*.tmp'))


def test_batch_uses_existing_queue_and_skips_success_without_asr(sqlite_db,tmp_path,monkeypatch):
    from scripts import podcast_batch
    db,config_path=sqlite_db
    cfg=load_config(config_path)
    sid=db.upsert_source_subscription(platform='xiaoyuzhou',source_type='feed',source_key='show',
        display_name='Show',source_url='https://example.test/rss',feed_url='https://example.test/rss')
    creator=db.upsert_creator('xiaoyuzhou','show','Show','')
    complete=item(); pending=item('000000000000000000000002')
    db.upsert_content_item('xiaoyuzhou',complete.content_id,creator)
    note=tmp_path/'existing.md';note.write_text('keep',encoding='utf8')
    db.upsert_summary(complete.content_id,'summary',str(note),'old','success',platform='xiaoyuzhou')
    monkeypatch.setattr(podcast_batch,'XiaoyuzhouAdapter',lambda config:SimpleNamespace(resolve_source=lambda url:[complete,pending]))
    manifest=tmp_path/'batch.json'
    first=prepare(cfg,[sid],manifest);second=prepare(cfg,[sid],manifest)
    assert first==second and first['already_completed']==1
    assert len(db.list_task_runs(limit=100))==1
    record=json.loads(manifest.read_text(encoding='utf8'))['items'][1]
    assert record['task_id'] and note.read_text(encoding='utf8')=='keep'
    record['download_status']='downloaded'
    podcast_batch.record_prefetch_progress(cfg,record)
    queued=db.get_task_run(record['task_id'])
    assert queued['status']=='queued'
    assert queued['progress_json']['prefetch']['status']=='downloaded'
    claimed=db.claim_next_task_run('fixture')
    assert claimed['id']==record['task_id']
    record['download_status']='transcript_ready'
    podcast_batch.record_prefetch_progress(cfg,record)
    assert db.get_task_run(record['task_id'])['progress_json']['prefetch']['status']=='downloaded'


def test_truncated_download_is_not_promoted_to_audio_cache(tmp_path,monkeypatch):
    import requests
    class Response:
        headers={'Content-Length':'100'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def raise_for_status(self):pass
        def iter_content(self,**kwargs):yield b'short'
    monkeypatch.setattr(requests,'get',lambda *args,**kwargs:Response())
    cfg=AppConfig({'sources':{'xiaoyuzhou':{'audio_temp_dir':str(tmp_path/'audio')}}},tmp_path/'config.yaml')
    episode=item()
    assert AudioDownloader(cfg).download(episode) is None
    assert episode.failure_reason=='downloaded_audio_incomplete'
    assert not list((tmp_path/'audio').glob('*.m4a'))
    assert not list((tmp_path/'audio').glob('*.tmp'))
