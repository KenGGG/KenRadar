"""Final three review blockers; fixture-only boundary regressions."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
import pytest
from test_hermes_v1 import db, seed_content


def test_s1_weekly_excludes_persisted_private_without_hiding_library(db):
    from kenradar.web.queries import load_content_rows, generate_weekly_brief
    from kenradar.publishing.static_site import StaticSitePublisher
    from kenradar.publishing.github_sync import GithubSyncManager
    for external_id, private, label in [('123', True, 'PRIVATE_SENTINEL'), ('456', False, 'PUBLIC_SENTINEL')]:
        cid, note = seed_content(db, external_id=external_id)
        content = db.find_content_item('douyin', external_id)
        db.upsert_content_item('douyin', external_id, content['creator_id'],
            publish_time=datetime.now().astimezone(), extra={'hermes_private': private})
        db.upsert_summary(external_id, json.dumps({'brief_title': label + '_TITLE',
            'brief_summary': label + '_SUMMARY', 'value_score': 5}), str(note), 'fixture', 'success')
    db.config.raw['output'] = {'obsidian_root': str(db.config.data_dir / 'public')}
    db.config.raw['publishing'] = {'github_pages': {'enabled': True, 'output_dir': str(db.config.data_dir / 'pages')},
        'github_sync': {'enabled': True, 'include_markdown_notes': True, 'include_html_docs': True}}
    assert len(load_content_rows(db.config)) == 2
    brief = generate_weekly_brief(db.config)
    text = brief.read_text(encoding='utf-8')
    assert 'PRIVATE_SENTINEL' not in text
    assert 'PUBLIC_SENTINEL_SUMMARY' in text
    publisher = StaticSitePublisher(db.config)
    publisher.publish_markdown(brief)
    publisher.write_index()
    candidates = GithubSyncManager(db.config).collect_candidates()
    assert candidates
    for path in [publisher.html_path_for(brief), db.config.data_dir / 'pages/index.html'] + [c.path for c in candidates]:
        assert 'PRIVATE_SENTINEL' not in path.read_text(encoding='utf-8')


@pytest.mark.parametrize('backend', ['qwen', 'openai', 'faster-whisper'])
def test_l4_preparation_blocks_qwen_start_and_isolates_missing_models(db, monkeypatch, backend):
    import sys
    import yaml
    from scripts.prepare_hermes_v1 import prepare
    from kenradar.core.config import load_config
    from kenradar.core.transcriber import Transcriber
    outside = db.config.data_dir / 'production-cache'
    db.config.raw['ai'] = {'qwen_asr': {'start_on_fallback': True, 'container_name': 'production-container'},
        'whisper': {'download_root': str(outside)}}
    db.config.raw['gpu_scheduler'] = {'lock': {'enabled': True, 'scope': 'file'}}
    db.config.raw['ai']['organizer'] = {'rate_limit_dir': str(outside / 'shared-rates')}
    db.config.path.write_text(yaml.safe_dump(db.config.raw), encoding='utf-8')
    target = db.config.data_dir / 'prepared'
    config = load_config(str(prepare(str(db.config.path), str(target))))
    transcriber = Transcriber(config, db)
    calls = []
    health = iter([SimpleNamespace(ok=False), SimpleNamespace(ok=True)])
    monkeypatch.setattr('kenradar.core.transcriber.requests.get', lambda *a, **k: next(health))
    monkeypatch.setattr('kenradar.core.transcriber.subprocess.run', lambda *a, **k: calls.append(a))
    if backend == 'qwen':
        transcriber._ensure_qwen_asr_available()
        assert calls == []
        assert config.get('ai.qwen_asr.start_on_fallback') is False
        return
    assert config.get('gpu_scheduler.lock') == {'enabled': True, 'scope': 'file'}
    assert config.get('ai.organizer.rate_limit_dir') == str(outside / 'shared-rates')
    class ModelUnavailable(Exception): pass
    def loader(*args, **kwargs):
        # The actual transcriber must constrain the dependency's missing-model write boundary.
        from pathlib import Path
        assert kwargs.get('download_root'), 'missing models would use an unisolated default cache'
        assert Path(kwargs['download_root']).resolve().is_relative_to(target.resolve())
        raise ModelUnavailable()
    monkeypatch.setitem(sys.modules, 'whisper', SimpleNamespace(load_model=loader))
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=loader, BatchedInferencePipeline=loader))
    with pytest.raises(ModelUnavailable):
        transcriber._transcribe_sync('123', target / 'missing.wav', 'missing-model', 'cpu', 'zh', backend)
    assert not outside.exists()


@pytest.mark.parametrize('second_id', ['456', None, '123 '])
def test_l5_second_detail_identity_before_media_boundaries(db, monkeypatch, second_id):
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow, ContractError, receipt
    from kenradar.integrations import safe_network as net
    from kenradar.core.downloader import Downloader
    from test_hermes_v1 import request
    db.config.raw['integrations'] = {'hermes_v1': {'safe_network': True}}
    first = {'aweme_id': '123', 'create_time': 1791907200, 'desc': 'requested', 'author': {'sec_uid': 'fixture-author'},
        'video': {'play_addr': {'url_list': ['https://cdn.example/requested.mp4']}}}
    second = {**first, 'aweme_id': second_id}
    class Response:
        status = 200
        headers = {}
        def __init__(self, body): self.body = body
        def stream(self, *a, **k): yield self.body
        def close(self): pass
        def release_conn(self): pass
    responses = [Response(json.dumps({'aweme_detail': first}).encode()),
        Response(json.dumps({'aweme_detail': second}).encode()), Response(b'wrong fixture media')]
    requests = []
    class Pool:
        def __init__(self, *a, **k): pass
        def request(self, *a, **k):
            requests.append((a, k))
            return responses.pop(0)
        def close(self): pass
    import kenradar.integrations.guarded_douyin
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    monkeypatch.setattr(net.urllib3, 'HTTPSConnectionPool', Pool)
    media_builds, path_builds = [], []
    build_media, build_path = Downloader._build_video_download, Downloader._build_save_path
    def media(self, *a):
        media_builds.append(a)
        return build_media(self, *a)
    def path(self, *a):
        path_builds.append(a)
        return build_path(self, *a)
    monkeypatch.setattr(Downloader, '_build_video_download', media)
    monkeypatch.setattr(Downloader, '_build_save_path', path)
    payload = request('https://www.douyin.com/video/123')
    submit(db, payload)
    run = db.claim_next_task_run('fixture')
    workflow = private_workflow(db.config, db)
    async def forbidden(*a, **k): raise RuntimeError('wrong identity reached ASR')
    workflow.transcriber.transcribe = forbidden
    with db.lease_scope(run), pytest.raises(ContractError) as error:
        asyncio.run(execute(workflow, {**run['payload_json'], 'task_id': run['id']}))
    assert error.value.code == 'SOURCE_IDENTITY_MISMATCH'
    assert len(requests) == 2
    assert media_builds == []
    assert path_builds == []
    content = db.find_content_item('douyin', '123')
    assert not content.get('local_path')
    assert not list(db.config.data_dir.rglob('*.mp4'))
    result = receipt(db.get_task_run(run['id']))
    assert result['delivery_status'] == 'failed'
    assert result['error']['code'] == 'SOURCE_IDENTITY_MISMATCH'


@pytest.mark.parametrize('second_id', ['456', None, '123 '])
def test_l5_ordinary_second_detail_also_fails_closed(db, monkeypatch, second_id):
    from kenradar.sources.douyin.connector import DouyinConnector
    from kenradar.core.downloader import Downloader
    class Client:
        def __init__(self, *a): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get_video_detail(self, requested):
            assert requested == '123'
            return {'aweme_id': second_id, 'desc': 'wrong'}
    monkeypatch.setattr('kenradar.core.downloader.DouyinAPIClient', Client)
    builds = []
    def build(*a):
        builds.append(a)
        return None
    monkeypatch.setattr(Downloader, '_build_video_download', build)
    connector = DouyinConnector(db.config)
    item = connector.map_content({'aweme_id': '123', 'desc': 'requested'})
    result = asyncio.run(connector.download(item, db.config.data_dir / 'media'))
    assert result.success is False
    assert result.error_code == 'SOURCE_IDENTITY_MISMATCH'
    assert builds == []
