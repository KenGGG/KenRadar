"""Contract tests use file SQLite, never the production database."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'data/test-migration/hermes-v1'


def test_capabilities_only_offer_implemented_delivery():
    from kenradar.integrations.hermes_v1 import capabilities
    caps = capabilities()
    assert caps['contract_versions'] == ['1.0']
    assert caps['supported_platforms'] == ['douyin', 'xiaoyuzhou']
    assert caps['publish_targets'] == []
    assert caps['notification_channels'] == []
    assert caps['supported_purposes'] == ['knowledge_note']


@pytest.fixture
def db():
    from kenradar.core.config import load_config
    from kenradar.storage import create_database
    from kenradar.storage.migrate import upgrade_database
    import yaml
    folder = ROOT / 'tests' / uuid4().hex
    folder.mkdir(parents=True)
    config_path = folder / 'config.yaml'
    config_path.write_text(yaml.safe_dump({'app': {'data_dir': str(folder), 'database_url': 'sqlite:///' + (folder / 'db.sqlite').as_posix()}, 'schedule': {'enabled': False}}), encoding='utf-8')
    upgrade_database(str(config_path))
    database = create_database(load_config(str(config_path)))
    yield database
    database.close()


def request(url='https://www.douyin.com/video/7694252203724262682'):
    return {'contract_version': '1.0', 'request_id': str(uuid4()), 'operation': 'process_content',
            'source': {'url': url}, 'purpose': 'knowledge_note',
            'delivery': {'visibility': 'private', 'publish': 'none', 'notify': 'none'},
            'execution': {'reuse_existing': True}}


def test_submit_is_durable_idempotent_and_conflict_safe(db):
    from kenradar.integrations.hermes_v1 import submit, ContractError
    payload = request()
    first = submit(db, payload)
    assert first['task_status'] == 'queued'
    assert first['delivery_status'] == 'pending'
    assert submit(db, payload)['task_id'] == first['task_id']
    stored = db.get_task_run(first['task_id'])
    assert stored['task_type'] == 'hermes_content_v1'
    assert stored['payload_json']['request'] == payload
    altered = json.loads(json.dumps(payload))
    altered['source']['url'] = 'https://www.douyin.com/video/7694252203724262683'
    with pytest.raises(ContractError) as error:
        submit(db, altered)
    assert error.value.code == 'REQUEST_ID_CONFLICT'
    assert error.value.status == 409
    assert len(db.list_task_runs()) == 1


@pytest.mark.parametrize('change,code', [
    ({'extra': True}, 'INVALID_REQUEST'),
    ({'contract_version': '2.0'}, 'INVALID_REQUEST'),
    ({'request_id': 'not-a-uuid'}, 'INVALID_REQUEST'),
    ({'execution': {'reuse_existing': 'false'}}, 'INVALID_REQUEST'),
    ({'execution': {'reuse_existing': False}}, 'CAPABILITY_UNAVAILABLE'),
    ({'source': {'url': 'http://127.0.0.1/video/123'}}, 'UNSAFE_SOURCE_URL'),
    ({'source': {'url': 'https://evildouyin.com/video/123'}}, 'UNSUPPORTED_SOURCE'),
    ({'source': {'url': 'https://www.douyin.com/user/123'}}, 'UNSUPPORTED_SOURCE'),
    ({'source': {'url': 'https://www.xiaoyuzhoufm.com/podcast/123'}}, 'UNSUPPORTED_SOURCE'),
    ({'source': {'url': 'https://user:pass@www.douyin.com/video/123'}}, 'UNSAFE_SOURCE_URL'),
    ({'source': {'url': 'https://www.douyin.com:8080/video/123'}}, 'UNSAFE_SOURCE_URL'),
    ({'delivery': {'visibility': 'private', 'publish': 'github_pages', 'notify': 'none'}}, 'POLICY_CONFLICT'),
    ({'delivery': {'visibility': 'public', 'publish': 'github_pages', 'notify': 'none'}}, 'CAPABILITY_UNAVAILABLE'),
    ({'delivery': {'visibility': 'private', 'publish': 'none', 'notify': 'feishu'}}, 'CAPABILITY_UNAVAILABLE'),
    ({'purpose': 'transcript'}, 'CAPABILITY_UNAVAILABLE'),
    ({'instructions': 'custom instructions'}, 'CAPABILITY_UNAVAILABLE'),
])
def test_invalid_policy_rejected_before_queue(db, change, code):
    from kenradar.integrations.hermes_v1 import submit, ContractError
    payload = request()
    payload.update(change)
    with pytest.raises(ContractError) as error:
        submit(db, payload)
    assert error.value.code == code
    assert db.list_task_runs() == []


def seed_content(db, platform='douyin', external_id='7694252203724262682', organized=True):
    creator = db.upsert_creator(platform, 'test-author', 'Test author', '', enabled=False)
    cid = db.upsert_content_item(platform, external_id, creator, title='Test title', download_status='done')
    db.upsert_transcript(external_id, '真实测试文本' * 30, '', '', 'test-asr', 'success', platform=platform)
    note = db.config.data_dir / (external_id + '.md')
    if organized:
        note.write_text('# Test note\nEvidence', encoding='utf-8')
        db.upsert_summary(external_id, json.dumps({'brief_summary': 'test summary'}), str(note), 'test', 'success', platform=platform)
    return cid, note


def test_worker_reuses_content_identity_without_publication(db, monkeypatch):
    from types import SimpleNamespace
    from kenradar.integrations.hermes_v1 import submit, receipt
    from kenradar.jobs.handlers import execute_task_run
    from kenradar.sources.contracts import ContentDescriptor
    cid, note = seed_content(db)
    item = ContentDescriptor(platform='douyin', external_content_id='7694252203724262682',
        external_source_id='test-author', title='Test title', published_at=None, media_type='video', url=request()['source']['url'])
    class Connector:
        async def resolve_content(self, url):
            return item
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submitted = submit(db, request('https://v.douyin.com/aliasA/'))
    run = db.claim_next_task_run('test-worker')
    with db.lease_scope(run):
        stats = asyncio.run(execute_task_run(SimpleNamespace(database=db, config=db.config), 'hermes_content_v1', {'request': run['payload_json']['request'], 'task_id': run['id']}))
        db.complete_task_run(run['id'], stats)
    result = receipt(db.get_task_run(submitted['task_id']))
    assert result['delivery_status'] == 'complete'
    assert result['content_identity'] == {'platform': 'douyin', 'external_content_id': item.external_content_id}
    assert all(result['stages'][stage]['status'] == 'reused' for stage in ('download', 'transcribe', 'organize', 'note'))
    assert result['stages']['publish']['status'] == 'skipped'
    assert result['result']['note']['kind'] == 'local_artifact'
    assert str(note) not in json.dumps(result)
    assert db.publications.list_operations(cid) == []


@pytest.mark.parametrize('platform,external_id,url', [
    ('douyin', '7694252203724262682', 'https://www.douyin.com/video/7694252203724262682'),
    ('xiaoyuzhou', '6ace3c3a195d838e2af15f95', 'https://www.xiaoyuzhoufm.com/episode/6ace3c3a195d838e2af15f95'),
])
def test_private_pipeline_writes_real_note_and_durable_stages(db, monkeypatch, platform, external_id, url):
    from kenradar.integrations.hermes_v1 import submit, receipt, private_workflow
    from kenradar.jobs.handlers import execute_task_run
    from kenradar.sources.contracts import ContentDescriptor, DownloadResult
    workflow = private_workflow(db.config, db)
    calls = []
    item = ContentDescriptor(platform=platform, external_content_id=external_id, external_source_id='author',
        title='Test title', published_at=None, media_type='audio' if platform == 'xiaoyuzhou' else 'video', url=url)
    class Connector:
        async def resolve_content(self, source):
            calls.append('resolve')
            return item
        async def download(self, content, target):
            calls.append('download')
            target.mkdir(parents=True, exist_ok=True)
            path = target / (external_id + '.mp4')
            path.write_bytes(b'test media fixture')
            return DownloadResult(success=True, path=path)
    class ASR:
        async def transcribe(self, content_id, path, metadata):
            calls.append('transcribe')
            assert metadata['platform'] == platform
            db.upsert_transcript(content_id, '测试转录' * 100, '', '', 'fixture-asr', 'success', platform=platform)
            return {'status': 'success', 'text': '测试转录' * 100, 'model': 'fixture-asr'}
    class Organizer:
        last_error = ''
        last_result = {'status': 'success', 'provider': 'fixture-provider', 'model': 'fixture-organizer'}
        def organize(self, title, text, metadata):
            calls.append('organize')
            return json.dumps({'brief_title': 'Test title', 'brief_summary': 'A summary',
                'one_sentence_conclusion': 'A conclusion', 'corrected_transcript': text, 'value_score': 4.0})
    workflow.transcriber, workflow.organizer = ASR(), Organizer()
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submitted = submit(db, request(url))
    run = db.claim_next_task_run('test-worker')
    with db.lease_scope(run):
        stats = asyncio.run(execute_task_run(workflow, 'hermes_content_v1', {**run['payload_json'], 'task_id': run['id']}))
        db.complete_task_run(run['id'], stats)
    result = receipt(db.get_task_run(submitted['task_id']))
    assert result['delivery_status'] == 'complete'
    assert all(result['stages'][s]['status'] == 'success' for s in ('resolve', 'download', 'transcribe', 'organize', 'note'))
    content = db.find_content_item(platform, external_id)
    bundle = db.get_current_bundle(content['id'])
    note_path = Path(bundle['note']['note_path'])
    assert note_path.is_file()
    assert note_path.is_relative_to(db.config.data_dir / 'hermes-private')
    assert '测试转录' in note_path.read_text(encoding='utf-8')
    assert db.publications.list_operations(content['id']) == []
    assert calls == ['resolve', 'download', 'transcribe', 'organize']
    assert result['stages']['transcribe']['model'] == 'fixture-asr'
    assert result['stages']['organize']['model'] == 'fixture-organizer'
    assert result['stages']['organize']['provider'] == 'fixture-provider'
    assert bundle['analysis']['provider'] == 'fixture-provider'
    assert content['extra']['hermes_private'] is True
    assert caps_private_verified()


def caps_private_verified():
    from kenradar.integrations.hermes_v1 import capabilities
    return capabilities()['private_processing'] is True


@pytest.mark.parametrize('failure_mode', ['provider_error', 'local_fallback'])
def test_actual_worker_records_failed_organizer_without_public_alerts(db, monkeypatch, failure_mode):
    from kenradar.integrations.hermes_v1 import submit, receipt, private_workflow
    from kenradar.jobs.worker import TaskWorker
    from kenradar.sources.contracts import ContentDescriptor
    from kenradar.core.workflow import Workflow
    seed_content(db, organized=False)
    url = request()['source']['url']
    item = ContentDescriptor('douyin', '7694252203724262682', 'author', 'Test title', None, 'video', url)
    class Connector:
        async def resolve_content(self, source):
            return item
    class Organizer:
        last_error = 'secret must not escape' if failure_mode == 'provider_error' else None
        last_result = {'status': 'degraded', 'model': 'local-fallback', 'provider': 'local'}
        def organize(self, *args):
            return json.dumps({'brief_summary': '降级内容', 'brief_title': 'Degraded title'})
    def make(config, database):
        workflow = private_workflow(config, database)
        workflow.organizer = Organizer()
        return workflow
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    monkeypatch.setattr('kenradar.integrations.hermes_v1.private_workflow', make)
    monkeypatch.setattr(Workflow, '__init__', lambda *a: pytest.fail('legacy workflow constructed'))
    monkeypatch.setattr('kenradar.jobs.worker.AlertManager', lambda *a: pytest.fail('private worker created notification alert'))
    submitted = submit(db, request())
    worker = object.__new__(TaskWorker)
    worker.config_path = str(db.config.path)
    worker.worker_name = 'test-worker'
    assert worker.run_once()
    row = db.get_task_run(submitted['task_id'])
    result = receipt(row)
    assert row['status'] == 'retry_wait'
    assert result['delivery_status'] == 'partial_failed'
    assert result['stages']['organize']['status'] == 'failed'
    assert result['stages']['note']['status'] == 'success'
    assert result['error']['code'] == 'ORGANIZER_FAILED'
    assert result['error']['retryable'] is True
    assert 'secret must not escape' not in json.dumps(result)
    assert Path(db.get_current_bundle(db.find_content_item('douyin', item.external_content_id)['id'])['note']['note_path']).is_file()


def test_private_artifacts_block_delivery_and_index_fallbacks(db):
    from kenradar.publishing.service import PublicationService
    from kenradar.notification.service import NotificationService
    from kenradar.publishing.static_site import StaticSitePublisher
    from kenradar.publishing.github_sync import GithubSyncManager
    from kenradar.core.config import AppConfig
    from types import SimpleNamespace
    cid, old_note = seed_content(db)
    private_note = db.config.data_dir / 'hermes-private/notes/douyin/author/private.md'
    private_note.parent.mkdir(parents=True)
    private_note.write_text('# Private note\nDo not publish', encoding='utf-8')
    content = db.find_content_item('douyin', '7694252203724262682')
    db.upsert_content_item('douyin', content['content_id'], content['creator_id'], extra={'hermes_private': True})
    db.upsert_summary(content['content_id'], '{}', str(private_note), 'test', 'success')
    forbidden = lambda *a, **k: pytest.fail('public side effect')
    for service in (PublicationService(db, SimpleNamespace(publish_markdown=forbidden), forbidden),
                    NotificationService(db, SimpleNamespace(push=forbidden))):
        with pytest.raises(ValueError, match='PRIVATE_CONTENT'):
            (service.publish_content if isinstance(service, PublicationService) else service.notify_content)(cid)
    raw = json.loads(json.dumps(db.config.raw))
    raw['publishing'] = {'github_pages': {'enabled': True, 'output_dir': str(db.config.data_dir / 'pages')},
        'github_sync': {'include_markdown_notes': True, 'include_html_docs': False, 'include_transcripts': True}}
    raw['output'] = {'obsidian_root': str(db.config.data_dir / 'hermes-private')}
    config = AppConfig(raw, db.config.path)
    publisher = StaticSitePublisher(config)
    with pytest.raises(ValueError, match='PRIVATE_CONTENT'):
        publisher.publish_markdown(private_note)
    publisher.write_index()
    assert 'Private note' not in (db.config.data_dir / 'pages/index.html').read_text(encoding='utf-8')
    assert GithubSyncManager(config).collect_candidates() == []


def test_retry_failed_organizer_preserves_transcript_and_resolved_identity(db, monkeypatch):
    from dataclasses import asdict
    from kenradar.integrations.hermes_v1 import submit, receipt, retry, private_workflow, ContractError
    from kenradar.sources.contracts import ContentDescriptor
    from kenradar.jobs.handlers import execute_task_run
    seed_content(db, organized=False)
    payload = request()
    original = submit(db, payload)
    run = db.claim_next_task_run('test-worker')
    item = ContentDescriptor('douyin', '7694252203724262682', 'author', 'Test title', None, 'video', payload['source']['url'])
    result = receipt(run)
    result['content_identity'] = {'platform': 'douyin', 'external_content_id': item.external_content_id}
    for stage in ('resolve', 'download', 'transcribe'):
        result['stages'][stage] = {'status': 'success'}
    result['stages']['organize'] = {'status': 'failed'}
    result['error'] = {'code': 'ORGANIZER_FAILED', 'stage': 'organize', 'message': 'failed', 'retryable': True}
    result['result']['evidence'] = {'kind': 'stored_transcript', 'locator': 'transcript:1'}
    with db.lease_scope(run):
        db.heartbeat_task_run(run['id'], progress={'hermes': result, 'resolved_content': asdict(item)})
        db.fail_task_run(run['id'], 'AUTH_REQUIRED')  # existing permanent failure stops automatic retries
    retry_payload = {'request_id': str(uuid4()), 'stage': 'organize'}
    resumed = retry(db, original['task_id'], retry_payload)
    assert retry(db, original['task_id'], retry_payload)['task_id'] == resumed['task_id']
    with pytest.raises(ContractError):
        retry(db, original['task_id'], {'request_id': str(uuid4()), 'stage': 'transcribe'})
    with pytest.raises(ContractError) as conflict:
        retry(db, original['task_id'], {**retry_payload, 'stage': 'note'})
    assert conflict.value.code == 'REQUEST_ID_CONFLICT'
    calls = []
    class Organizer:
        last_error = ''
        def organize(self, *args):
            calls.append('organize')
            return json.dumps({'brief_summary': 'Recovered', 'brief_title': 'Recovered title'})
    workflow = private_workflow(db.config, db)
    workflow.organizer = Organizer()
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: pytest.fail('retry resolved source again'))
    run = db.claim_next_task_run('test-worker')
    with db.lease_scope(run):
        stats = asyncio.run(execute_task_run(workflow, run['task_type'], {**run['payload_json'], 'task_id': run['id']}))
        db.complete_task_run(run['id'], stats)
    result = receipt(db.get_task_run(resumed['task_id']))
    assert result['delivery_status'] == 'complete'
    assert result['stages']['transcribe']['status'] == 'reused'
    assert calls == ['organize']
    assert receipt(db.get_task_run(original['task_id']))['delivery_status'] == 'partial_failed'


def test_versioned_http_submit_status_retry_and_loopback_boundary(db):
    import threading
    import requests
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlsplit
    from kenradar.web.router import init_routes
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if not self._dispatch_route(urlsplit(self.path).path, method='GET', config_path=str(db.config.path)):
                self.send_error(404)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            if not self._dispatch_route(urlsplit(self.path).path, method='POST', config_path=str(db.config.path), data=body):
                self.send_error(404)
        def log_message(self, *a):
            pass
    init_routes(Handler)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}/api/integrations/hermes/v1'
    try:
        caps = requests.get(base + '/capabilities')
        assert caps.status_code == 200
        assert caps.json()['private_processing'] is True
        created = requests.post(base + '/content-tasks', json=request())
        assert created.status_code == 202
        task_id = created.json()['task_id']
        read = requests.get(base + f'/tasks/{task_id}')
        assert read.status_code == 200
        assert read.json()['request_id'] == created.json()['request_id']
        assert requests.get(base + '/tasks/999999').status_code == 404
        rejected = requests.post(base + f'/tasks/{task_id}/retry', json={'request_id': str(uuid4()), 'stage': 'organize'})
        assert rejected.status_code == 409
        cross_origin = requests.post(base + '/content-tasks', json=request(), headers={'Origin': 'https://attacker.example'})
        assert cross_origin.status_code == 403
        spoof = requests.get(base + '/capabilities', headers={'Host': 'attacker.example'})
        assert spoof.status_code == 403
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize('addresses', [['127.0.0.1'], ['169.254.169.254'], ['8.8.8.8', '10.0.0.1']])
def test_safe_network_rejects_nonpublic_dns_before_connect(monkeypatch, addresses):
    from kenradar.integrations.safe_network import safe_get
    from kenradar.integrations.hermes_v1 import ContractError
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', (ip, 443)) for ip in addresses])
    with pytest.raises(ContractError) as error:
        with safe_get('https://www.douyin.com/video/123'):
            pytest.fail('unsafe connection accepted')
    assert error.value.code == 'UNSAFE_SOURCE_URL'


def test_safe_network_checks_redirect_before_connect_and_pins_tls(monkeypatch):
    from kenradar.integrations.safe_network import safe_get
    from kenradar.integrations.hermes_v1 import ContractError
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr('socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('8.8.8.8', 443))])
    class Pool:
        def __init__(self, host, port, **kwargs):
            calls.append((host, kwargs.get('server_hostname'), kwargs.get('assert_hostname')))
        def request(self, *args, **kwargs):
            assert kwargs['redirect'] is False
            return SimpleNamespace(status=302, headers={'Location': 'http://169.254.169.254/latest/meta-data'}, close=lambda: None, release_conn=lambda: None)
        def close(self):
            pass
    monkeypatch.setattr('urllib3.HTTPSConnectionPool', Pool)
    with pytest.raises(ContractError) as error:
        with safe_get('https://www.douyin.com/video/123'):
            pytest.fail('unsafe redirect accepted')
    assert error.value.code == 'UNSAFE_SOURCE_URL'
    assert calls == [('8.8.8.8', 'www.douyin.com', 'www.douyin.com')]


def test_private_xiaoyuzhou_fetch_and_media_use_guarded_transport(db, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from kenradar.integrations.hermes_v1 import private_workflow
    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector
    from kenradar.sources.xiaoyuzhou.audio_downloader import AudioDownloader
    from kenradar.sources.base import ContentItem
    config = private_workflow(db.config, db).config
    calls = []
    @contextmanager
    def guarded(url, **kwargs):
        calls.append((url, kwargs))
        yield SimpleNamespace(text='safe page', raise_for_status=lambda: None, iter_content=lambda **k: [b'real fixture bytes'])
    monkeypatch.setattr('kenradar.integrations.safe_network.safe_get', guarded)
    monkeypatch.setattr('requests.get', lambda *a, **k: pytest.fail('unguarded request'))
    connector = XiaoyuzhouConnector(config)
    assert connector._fetch_text('https://www.xiaoyuzhoufm.com/episode/6ace3c3a195d838e2af15f95') == 'safe page'
    item = ContentItem(platform='xiaoyuzhou', creator='author', creator_id='author', content_id='id', source_url='', original_title='title', published_at=None, media_type='audio', duration=None, description='', cover_url='', media_url='https://cdn.example/audio.mp3')
    path = AudioDownloader(config).download(item)
    assert path.read_bytes() == b'real fixture bytes'
    assert calls[0][1]['source'] is True
    assert calls[1][0] == item.media_url


def test_private_douyin_shortlink_and_media_use_guarded_transport(db, monkeypatch):
    # Import guarded adapter before monkeypatching its transport dependency.
    import kenradar.integrations.guarded_douyin
    from contextlib import contextmanager
    from types import SimpleNamespace
    from kenradar.integrations.hermes_v1 import private_workflow, ContractError
    from kenradar.sources.douyin.connector import DouyinConnector
    from kenradar.sources.contracts import ContentDescriptor
    config = private_workflow(db.config, db).config
    calls = []
    @contextmanager
    def guarded(url, **kwargs):
        calls.append(url)
        if url.startswith('https://v.douyin.com/'):
            yield SimpleNamespace(url='https://www.douyin.com/video/123')
        else:
            raise ContractError('UNSAFE_SOURCE_URL', 'unsafe media')
    async def resolve(config, url):
        assert url == 'https://www.douyin.com/video/123'
        return SimpleNamespace(aweme={'aweme_id': '123'}, aweme_id='123')
    class API:
        def __init__(self, *a):
            self.policy = None
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            pass
        async def get_video_detail(self, *a):
            return {'aweme_id': '123'}
    monkeypatch.setattr('kenradar.integrations.safe_network.safe_get', guarded)
    monkeypatch.setattr('kenradar.core.source_resolver.resolve_douyin_video', resolve)
    monkeypatch.setattr('kenradar.integrations.guarded_douyin.GuardedDouyinAPIClient', API)
    monkeypatch.setattr('kenradar.core.downloader.Downloader._build_video_download', lambda *a: ('http://127.0.0.1/video.mp4', {}))
    connector = DouyinConnector(config)
    assert asyncio.run(connector.resolve_content('https://v.douyin.com/alias/')).external_content_id == '123'
    item = ContentDescriptor('douyin', '123', 'author', 'title', None, 'video', 'https://www.douyin.com/video/123')
    result = asyncio.run(connector.download(item, config.download_dir))
    assert result.success is False
    assert result.error_code == 'UNSAFE_SOURCE_URL'
    assert calls == ['https://v.douyin.com/alias/', 'http://127.0.0.1/video.mp4']


def test_content_lock_prevents_concurrent_processing(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, private_workflow, execute, ContractError, receipt
    from kenradar.sources.contracts import ContentDescriptor
    seed_content(db)
    item = ContentDescriptor('douyin', '7694252203724262682', 'author', 'title', None, 'video', request()['source']['url'])
    class Connector:
        async def resolve_content(self, url):
            return item
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submit(db, request())
    run = db.claim_next_task_run('test-worker')
    key = 'hermes-content:douyin:7694252203724262682'
    assert db.acquire_resource_lease(key, 'another-worker')
    with db.lease_scope(run):
        with pytest.raises(ContractError) as error:
            asyncio.run(execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']}))
    assert error.value.code == 'CONTENT_BUSY'
    assert receipt(db.get_task_run(run['id']))['delivery_status'] != 'complete'
    db.release_resource_lease(key, 'another-worker')
    with db.lease_scope(run):
        result = asyncio.run(execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']}))
    assert result['hermes']['delivery_status'] == 'complete'
    assert db.acquire_resource_lease(key, 'another-worker')


def test_organizer_receipt_tracks_actual_fallback_provider(db, monkeypatch):
    from kenradar.core.organizer import ContentOrganizer
    organizer = ContentOrganizer(db.config)
    providers = [{'name': 'primary', 'model': 'primary-model'},
                 {'name': 'fallback', 'model': 'fallback-model'}]
    monkeypatch.setattr(organizer, '_organizer_providers', lambda: providers)
    monkeypatch.setattr(organizer, '_provider_api_key', lambda p: 'fixture')
    def call(provider, *a):
        if provider['name'] == 'primary':
            raise RuntimeError('network failure')
        return json.dumps({'brief_summary': '真实测试摘要', 'corrected_transcript': '测试转录' * 100})
    monkeypatch.setattr(organizer, '_organize_with_provider', call)
    monkeypatch.setattr(organizer, '_validate_provider_output', lambda *a: None)
    organizer.organize('Title', '测试转录' * 100)
    assert organizer.last_result == {'status': 'success', 'provider': 'fallback', 'model': 'fallback-model'}
    monkeypatch.setattr(organizer, '_organizer_providers', lambda: [])
    organizer.organize('Title', '测试转录' * 100)
    assert organizer.last_result['status'] == 'degraded'
    assert organizer.last_result['model'] == 'local-fallback'


def test_isolated_config_preparation_and_shared_provider_lock(db, monkeypatch):
    from scripts.prepare_hermes_v1 import prepare
    from kenradar.core.config import load_config
    from kenradar.core.organizer import ContentOrganizer
    folder = db.config.data_dir / 'acceptance'
    import yaml
    raw = json.loads(json.dumps(db.config.raw))
    raw['ai'] = {'organizer': {'providers': [{'name': 'primary', 'env_var': 'HERMES_FIXTURE_KEY', 'model': 'test', 'endpoint': 'https://api.example/v1'}]}}
    db.config.path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    monkeypatch.setenv('HERMES_FIXTURE_KEY', 'fixture-not-a-secret')
    prepared = prepare(str(db.config.path), str(folder), port=8876)
    config = load_config(str(prepared))
    assert config.get('ai.organizer.providers')[0]['api_key'] == 'fixture-not-a-secret'
    assert config.database_url != db.config.database_url
    assert config.data_dir == folder
    assert config.get('schedule.enabled') is False
    assert config.get('notification.enabled') is False
    assert config.get('publishing.github_pages.enabled') is False
    assert config.get('publishing.github_sync.enabled') is False
    assert config.download_dir.is_relative_to(folder)
    shared = db.config.data_dir / 'runtime/rate_limits'
    assert config.get('ai.organizer.rate_limit_dir') == str(shared)
    organizer = ContentOrganizer(config)
    assert organizer._wait_for_shared_rate_limit(19, 'isolated-fixture')
    assert list(shared.glob('ai_*.json'))
    assert not (folder / 'runtime/rate_limits').exists()


@pytest.mark.parametrize('error_code', ['UNSAFE_SOURCE_URL', 'SOURCE_PARSE_CHANGED'])
def test_permanent_source_failure_stops_worker_retries(db, monkeypatch, error_code):
    from kenradar.integrations.hermes_v1 import submit, receipt, ContractError
    from kenradar.sources.contracts import SourceParseChanged
    from kenradar.jobs.worker import TaskWorker
    class Connector:
        async def resolve_content(self, url):
            if error_code == 'SOURCE_PARSE_CHANGED':
                raise SourceParseChanged('source body contains sensitive test content')
            raise ContractError(error_code, 'unsafe')
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    monkeypatch.setattr('kenradar.jobs.worker.AlertManager', lambda *a: pytest.fail('private failure triggered notification'))
    result = submit(db, request())
    worker = object.__new__(TaskWorker)
    worker.worker_name, worker.config_path = 'test-worker', str(db.config.path)
    worker.run_once()
    row = db.get_task_run(result['task_id'])
    assert row['status'] == 'failed'
    result = receipt(row)
    assert result['error']['code'] == error_code
    assert result['error']['retryable'] is False
    assert 'sensitive test content' not in json.dumps(result)


def test_status_reports_historical_publication_and_missing_artifact_truthfully(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, receipt, execute, private_workflow
    from kenradar.sources.contracts import ContentDescriptor
    cid, note = seed_content(db)
    publication = db.publications.start(cid, 'historical-hash', 'historical-fixture')
    db.publications.complete(publication['id'], 'https://example.org/previous.html')
    class Connector:
        async def resolve_content(self, url):
            return ContentDescriptor('douyin', '7694252203724262682', 'author', 'title', None, 'video', url)
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submit(db, request())
    run = db.claim_next_task_run('test-worker')
    with db.lease_scope(run):
        stats = asyncio.run(execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']}))
        db.complete_task_run(run['id'], stats)
    result = receipt(db.get_task_run(run['id']), db)
    assert result['delivery_status'] == 'complete'
    assert result['result']['historical_publication']['status'] == 'recorded'
    assert result['result']['historical_publication']['verified'] is False
    assert 'existing_publication_not_retracted' in result['warnings']
    assert 'public_url' not in result['result']
    note.unlink()
    result = receipt(db.get_task_run(run['id']), db)
    assert result['delivery_status'] == 'partial_failed'
    assert result['stages']['note']['status'] == 'failed'
    assert result['error']['code'] == 'ARTIFACT_MISSING'


def test_unsafe_xiaoyuzhou_media_keeps_permanent_error_code(db, monkeypatch):
    from contextlib import contextmanager
    from kenradar.integrations.hermes_v1 import private_workflow, ContractError
    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector
    from kenradar.sources.contracts import ContentDescriptor
    @contextmanager
    def reject(*a, **k):
        raise ContractError('UNSAFE_SOURCE_URL', 'unsafe')
        yield
    monkeypatch.setattr('kenradar.integrations.safe_network.safe_get', reject)
    config = private_workflow(db.config, db).config
    connector = XiaoyuzhouConnector(config)
    item = ContentDescriptor('xiaoyuzhou', '6ace3c3a195d838e2af15f95', 'author', 'title', None, 'audio',
        'https://www.xiaoyuzhoufm.com/episode/6ace3c3a195d838e2af15f95', media_url='http://127.0.0.1/audio.mp3')
    result = asyncio.run(connector.download(item, config.download_dir))
    assert result.error_code == 'UNSAFE_SOURCE_URL'


def test_resolved_content_cannot_expand_requested_episode_scope(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import private_workflow, submit, execute, ContractError
    from kenradar.sources.contracts import ContentDescriptor
    url = 'https://www.xiaoyuzhoufm.com/episode/6ace3c3a195d838e2af15f95'
    class Connector:
        async def resolve_content(self, source):
            return ContentDescriptor('xiaoyuzhou', '6ace3c3a195d838e2af15f96', 'author', 'title', None, 'audio',
                'https://www.xiaoyuzhoufm.com/episode/6ace3c3a195d838e2af15f96')
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submit(db, request(url))
    run = db.claim_next_task_run('test-worker')
    with db.lease_scope(run), pytest.raises(ContractError) as error:
        asyncio.run(execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']}))
    assert error.value.code == 'SOURCE_IDENTITY_MISMATCH'
    assert db.find_content_item('xiaoyuzhou', '6ace3c3a195d838e2af15f96') is None


def test_expired_worker_lease_recovers_checkpoint_without_redownload(db, monkeypatch):
    from dataclasses import asdict
    from sqlalchemy import update
    from kenradar.storage.sqlite_database import utc_now, LeaseLost
    from kenradar.integrations.hermes_v1 import submit, receipt, execute, private_workflow
    from kenradar.sources.contracts import ContentDescriptor
    seed_content(db)
    submit(db, request())
    old = db.claim_next_task_run('crashed-worker')
    item = ContentDescriptor('douyin', '7694252203724262682', 'author', 'title', None, 'video', request()['source']['url'])
    key = 'hermes-content:douyin:7694252203724262682'
    result = receipt(old)
    result['stages']['transcribe'] = {'status': 'success'}
    with db.lease_scope(old):
        db.acquire_resource_lease(key, old['lease_token'])
        db.heartbeat_task_run(old['id'], progress={'hermes': result, 'resolved_content': asdict(item), 'content_lock': {'key': key, 'owner': old['lease_token']}})
    with db.connect(write=True) as conn:
        conn.execute(update(db.table('task_run')).where(db.table('task_run').c.id == old['id']).values(lease_expires_at=utc_now(-10)))
        conn.execute(update(db.table('resource_lease')).where(db.table('resource_lease').c.resource_key == key).values(lease_expires_at=utc_now(-10)))
    replacement = db.claim_next_task_run('replacement-worker')
    assert replacement['id'] == old['id']
    assert replacement['attempt'] == old['attempt'] + 1
    with db.lease_scope(old), pytest.raises(LeaseLost):
        db.heartbeat_task_run(old['id'])
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: pytest.fail('checkpoint recovery restarted source resolution'))
    with db.lease_scope(replacement):
        stats = asyncio.run(execute(private_workflow(db.config, db), {**replacement['payload_json'], 'task_id': replacement['id']}))
        db.complete_task_run(replacement['id'], stats)
    result = receipt(db.get_task_run(old['id']), db)
    assert result['delivery_status'] == 'complete'
    assert all(result['stages'][s]['status'] == 'reused' for s in ('resolve', 'download', 'transcribe', 'organize', 'note'))


def test_rebuilding_missing_note_preserves_stored_model_provenance(db, monkeypatch):
    import yaml
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow
    from kenradar.sources.contracts import ContentDescriptor
    cid, note = seed_content(db)
    note.unlink()
    class Connector:
        async def resolve_content(self, url):
            return ContentDescriptor('douyin', '7694252203724262682', 'author', 'title', None, 'video', url)
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submit(db, request())
    run = db.claim_next_task_run('test-worker')
    with db.lease_scope(run):
        stats = asyncio.run(execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']}))
    bundle = db.get_current_bundle(cid)
    path = Path(bundle['note']['note_path'])
    frontmatter = yaml.safe_load(path.read_text(encoding='utf-8').split('---')[1])
    assert frontmatter['ai_model'] == 'test'
    assert bundle['analysis']['model'] == 'test'
    assert stats['hermes']['stages']['organize']['status'] == 'reused'


def test_private_worker_timeout_persists_retryable_stage_without_cancel_deadlock(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, receipt
    from kenradar.jobs.worker import TaskWorker
    from kenradar.jobs import worker as module
    submitted = submit(db, request())
    async def timed_out(workflow, task_type, payload, **kwargs):
        result = receipt(workflow.database.get_task_run(payload['task_id']))
        result['stages']['transcribe'] = {'status': 'running'}
        workflow.database.heartbeat_task_run(payload['task_id'], progress={'hermes': result})
        raise asyncio.TimeoutError()
    monkeypatch.setattr(module, 'execute_task_run', timed_out)
    monkeypatch.setattr(module, 'AlertManager', lambda *a: pytest.fail('timeout sent private alert'))
    worker = object.__new__(TaskWorker)
    worker.worker_name, worker.config_path = 'test-worker', str(db.config.path)
    assert worker.run_once()
    row = db.get_task_run(submitted['task_id'])
    result = receipt(row)
    assert row['status'] == 'failed'
    assert row['cancel_requested_at'] is None
    assert result['stages']['transcribe']['status'] == 'failed'
    assert result['error']['code'] == 'TASK_TIMEOUT'
    assert result['error']['retryable'] is True
