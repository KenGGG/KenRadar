"""Independent-review corrections: real SQLite and isolated files, no external delivery."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_hermes_v1 import db, request, seed_content


def test_s1_failed_private_content_cannot_enter_legacy_recovery(db, monkeypatch):
    from kenradar.core.workflow import Workflow
    cid, _ = seed_content(db, organized=False)
    content = db.find_content_item('douyin', '7694252203724262682')
    db.upsert_content_item('douyin', content['content_id'], content['creator_id'], extra={'hermes_private': True})
    workflow = object.__new__(Workflow)
    workflow.config, workflow.database = db.config, db
    forbidden = lambda *a, **k: pytest.fail('private legacy side effect')
    workflow.organizer = SimpleNamespace(organize=forbidden)
    workflow.alerts = SimpleNamespace(error=forbidden)
    workflow._publish_markdown = forbidden
    rows = db.list_transcripts_missing_summary()
    assert rows == []
    assert asyncio.run(workflow.summarize_existing())['found'] == 0
    with pytest.raises(ValueError, match='PRIVATE_CONTENT'):
        workflow._summarize_transcript_row({'aweme_id': content['content_id'], 'text_content': 'private'}, 'recovery')


def test_s1_private_rendering_alerts_and_copied_artifact_delivery(db, monkeypatch):
    from kenradar.core.workflow import Workflow
    from kenradar.integrations.hermes_v1 import private_workflow
    from kenradar.notification.alert import AlertManager
    from kenradar.publishing.static_site import StaticSitePublisher
    from kenradar.publishing.github_sync import GithubSyncManager
    cid, _ = seed_content(db, organized=False)
    content = db.find_content_item('douyin', '7694252203724262682')
    db.upsert_content_item('douyin', content['content_id'], content['creator_id'], extra={'hermes_private': True})
    legacy = object.__new__(Workflow)
    legacy.config, legacy.database = db.config, db
    with pytest.raises(ValueError, match='PRIVATE_CONTENT'):
        legacy._write_item_summary(content['content_id'], 'Private', '{}', 'private')
    workflow = private_workflow(db.config, db)
    note = workflow._write_item_summary(content['content_id'], 'Private', '{}', 'private')
    assert 'hermes_private: true' in note.read_text(encoding='utf-8')
    alerts = AlertManager(db.config, db)
    monkeypatch.setattr(alerts, '_send_feishu', lambda *a: pytest.fail('private alert delivery'))
    monkeypatch.setattr(alerts, '_enabled', lambda: True)
    alerts.error('organizer', 'private', aweme_id=content['content_id'])
    alerts.recovered('organizer', 'private', aweme_id=content['content_id'])
    assert db.list_recent_alerts() == []
    copied = db.config.data_dir / 'notes/douyin/copied.md'
    copied.parent.mkdir(parents=True, exist_ok=True)
    copied.write_text(note.read_text(encoding='utf-8'), encoding='utf-8')
    db.config.raw['output'] = {'obsidian_root': str(db.config.data_dir)}
    db.config.raw['publishing'] = {'github_pages': {'enabled': True, 'output_dir': str(db.config.data_dir / 'pages')},
        'github_sync': {'include_markdown_notes': True, 'include_html_docs': False}}
    publisher = StaticSitePublisher(db.config)
    with pytest.raises(ValueError, match='PRIVATE_CONTENT'):
        publisher.publish_markdown(copied)
    publisher.write_index()
    assert 'Private' not in (db.config.data_dir / 'pages/index.html').read_text(encoding='utf-8')
    assert copied not in [candidate.path for candidate in GithubSyncManager(db.config).collect_candidates()]


def test_l3_private_new_content_preserves_known_creator(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow
    from kenradar.sources.contracts import ContentDescriptor, DownloadResult
    creator = db.upsert_creator('douyin', 'known', 'Real nickname', 'https://www.douyin.com/user/known', enabled=True, extra={'custom': 'keep'})
    before = db.get_creator(creator)
    item = ContentDescriptor('douyin', '7694252203724262682', 'known', 'title', None, 'video', request()['source']['url'])
    class Connector:
        async def resolve_content(self, url): return item
        async def download(self, item, target): return DownloadResult(False, error_code='DOWNLOAD_FAILED')
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submit(db, request())
    run = db.claim_next_task_run('worker')
    with db.lease_scope(run), pytest.raises(ValueError):
        asyncio.run(execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']}))
    assert db.get_creator(creator) == before


def test_l4_prepared_config_never_launches_managed_funasr(db, monkeypatch):
    import yaml
    from scripts.prepare_hermes_v1 import prepare
    from kenradar.core.config import load_config
    from kenradar.core.funasr_service import FunASRServiceManager
    raw = db.config.raw
    outside = db.config.data_dir / 'production-runtime'
    raw['ai'] = {'funasr': {'managed': True, 'endpoint': 'http://127.0.0.1:18002/v1',
        'startup_lock_path': str(outside / 'start.lock')}}
    raw['schedule'] = {'enabled': True, 'source_radar_enabled': True}
    db.config.path.write_text(yaml.safe_dump(raw), encoding='utf-8')
    config = load_config(str(prepare(str(db.config.path), str(db.config.data_dir / 'isolated'))))
    assert config.get('ai.funasr.managed') is False
    assert config.get('schedule.source_radar_enabled') is False
    manager = FunASRServiceManager(config, health_check=lambda u: False,
        process_runner=lambda p: pytest.fail('isolated preparation launched production service'))
    manager.ensure_available()
    assert not outside.exists()


def test_l2_late_organizer_cannot_delete_replacement_artifact(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow
    from kenradar.sources.contracts import ContentDescriptor
    from kenradar.storage.sqlite_database import LeaseLost, utc_now
    from sqlalchemy import update
    cid, _ = seed_content(db, organized=False)
    item = ContentDescriptor('douyin', '7694252203724262682', 'test-author', 'title', None, 'video', request()['source']['url'])
    class Connector:
        async def resolve_content(self, url): return item
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    submit(db, request())
    old = db.claim_next_task_run('old')
    stale = private_workflow(db.config, db)
    replacement_paths = []
    def replacement_during_organizer(*args):
        with db.connect(write=True) as conn:
            conn.execute(update(db.table('task_run')).where(db.table('task_run').c.id == old['id']).values(lease_expires_at=utc_now(-10)))
            conn.execute(update(db.table('resource_lease')).values(lease_expires_at=utc_now(-10)))
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            new = pool.submit(db.claim_next_task_run, 'replacement').result()
        winner = private_workflow(db.config, db)
        winner.organizer = SimpleNamespace(last_error=None, last_result={'model': 'fixture', 'status': 'success'},
            organize=lambda *a: json.dumps({'brief_title': 'Winner', 'brief_summary': 'Winner'}))
        def run_replacement():
            with db.lease_scope(new):
                return asyncio.run(execute(winner, {**new['payload_json'], 'task_id': new['id']}))
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(run_replacement).result()
        path = Path(db.get_current_bundle(cid)['note']['note_path'])
        replacement_paths.append((path, path.read_bytes()))
        return json.dumps({'brief_title': 'Stale', 'brief_summary': 'Stale'})
    stale.organizer = SimpleNamespace(last_error='degraded', last_result={'model': 'fixture', 'status': 'degraded'}, organize=replacement_during_organizer)
    with db.lease_scope(old), pytest.raises(LeaseLost):
        asyncio.run(execute(stale, {**old['payload_json'], 'task_id': old['id']}))
    path, expected = replacement_paths[0]
    assert path.is_file(), 'stale writer deleted current note'
    assert path.read_bytes() == expected
    assert db.get_current_bundle(cid)['note']['note_path'] == str(path)
    assert old['lease_token'] not in str(path)


def test_l2_live_task_cannot_commit_after_content_lease_takeover(db):
    from kenradar.integrations.hermes_v1 import submit
    from kenradar.storage.sqlite_database import LeaseLost
    from sqlalchemy import update
    cid, _ = seed_content(db)
    submit(db, request())
    run = db.claim_next_task_run('worker')
    key = 'hermes-content:douyin:7694252203724262682'
    with db.lease_scope(run):
        assert db.acquire_resource_lease(key, run['lease_token'])
        db.heartbeat_task_run(run['id'], progress={'content_lock': {'key': key, 'owner': run['lease_token']}})
    with db.connect(write=True) as conn:
        conn.execute(update(db.table('resource_lease')).where(db.table('resource_lease').c.resource_key == key).values(owner='replacement'))
    with db.lease_scope(run), pytest.raises(LeaseLost):
        db.upsert_summary('7694252203724262682', '{}', 'stale.md', 'stale', 'success')


def test_l2_failed_resource_heartbeat_is_lease_loss():
    from kenradar.jobs.worker import renew_content_lease
    from kenradar.storage.sqlite_database import LeaseLost
    fake = SimpleNamespace(get_task_run=lambda r: {'progress_json': {'content_lock': {'key': 'key', 'owner': 'token'}}},
        acquire_resource_lease=lambda *a, **k: False)
    with pytest.raises(LeaseLost):
        renew_content_lease(fake, {'id': 1, 'lease_token': 'token'})


def test_l2_rejected_renewal_fences_all_later_database_writes(db, monkeypatch):
    from kenradar.jobs.worker import renew_content_lease
    from kenradar.integrations.hermes_v1 import submit
    from kenradar.storage.sqlite_database import LeaseLost
    seed_content(db)
    submit(db, request())
    run = db.claim_next_task_run('worker')
    key = 'hermes-content:douyin:7694252203724262682'
    with db.lease_scope(run):
        assert db.acquire_resource_lease(key, run['lease_token'])
        db.heartbeat_task_run(run['id'], progress={'content_lock': {'key': key, 'owner': run['lease_token']}})
    monkeypatch.setattr(db, 'acquire_resource_lease', lambda *a, **k: False)
    with pytest.raises(LeaseLost):
        renew_content_lease(db, run)
    with db.lease_scope(run), pytest.raises(LeaseLost):
        db.upsert_summary('7694252203724262682', '{}', 'stale.md', 'stale', 'success')


def test_s1_private_failure_on_existing_content_persists_policy(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow, ContractError
    from kenradar.sources.contracts import ContentDescriptor
    cid, _ = seed_content(db, organized=False)
    item = ContentDescriptor('douyin', '7694252203724262682', 'test-author', 'title', None, 'video', request()['source']['url'])
    class Connector:
        async def resolve_content(self, url): return item
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    workflow = private_workflow(db.config, db)
    workflow.organizer = SimpleNamespace(last_error='failure', last_result={'status': 'degraded'}, organize=lambda *a: '{}')
    submit(db, request())
    run = db.claim_next_task_run('worker')
    with db.lease_scope(run), pytest.raises(ContractError, match='ORGANIZER_FAILED'):
        asyncio.run(execute(workflow, {**run['payload_json'], 'task_id': run['id']}))
    assert db.find_content_item('douyin', item.external_content_id)['extra']['hermes_private'] is True
    assert db.list_transcripts_missing_summary() == []


def test_s1_persisted_policy_blocks_unmarked_legacy_note_exports(db):
    from kenradar.publishing.static_site import StaticSitePublisher
    from kenradar.publishing.github_sync import GithubSyncManager
    cid, old = seed_content(db)
    content = db.find_content_item('douyin', '7694252203724262682')
    note = db.config.data_dir / 'notes/douyin/legacy.md'
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_bytes(old.read_bytes())
    db.upsert_summary(content['content_id'], '{}', str(note), 'test', 'success')
    db.upsert_content_item('douyin', content['content_id'], content['creator_id'], extra={'hermes_private': True})
    db.config.raw['output'] = {'obsidian_root': str(db.config.data_dir)}
    db.config.raw['publishing'] = {'github_pages': {'enabled': True, 'output_dir': str(db.config.data_dir / 'pages')},
        'github_sync': {'include_markdown_notes': True, 'include_html_docs': False}}
    publisher = StaticSitePublisher(db.config)
    with pytest.raises(ValueError, match='PRIVATE_CONTENT'):
        publisher.publish_markdown(note)
    publisher.write_index()
    assert 'Test note' not in (db.config.data_dir / 'pages/index.html').read_text(encoding='utf-8')
    assert note not in [candidate.path for candidate in GithubSyncManager(db.config).collect_candidates()]
    from kenradar.publishing.github_sync import SyncCandidate, GithubSyncError
    manager = GithubSyncManager(db.config)
    manager.repo_dir = db.config.data_dir
    with pytest.raises(GithubSyncError):
        manager._guard_sensitive_files([manager._rel(note)], [SyncCandidate(note, 'manual')])


def test_l2_reused_media_is_copied_before_writing_asr_sidecars(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow
    from kenradar.sources.contracts import ContentDescriptor
    external = '7694252203724262682'
    creator = db.upsert_creator('douyin', 'test-author', 'author', '', enabled=False)
    original = db.config.data_dir / 'shared-media.mp4'
    original.write_bytes(b'fixture media')
    sidecar = original.with_suffix('.transcript.txt')
    sidecar.write_text('original evidence', encoding='utf-8')
    db.upsert_content_item('douyin', external, creator, local_path=str(original), download_status='done')
    item = ContentDescriptor('douyin', external, 'test-author', 'title', None, 'video', request()['source']['url'])
    class Connector:
        async def resolve_content(self, url): return item
    class Transcriber:
        async def transcribe(self, external, media, metadata):
            media.with_suffix('.transcript.txt').write_text('new sidecar', encoding='utf-8')
            db.upsert_transcript(external, 'fixture text', '', '', 'fixture', 'success')
            return {'status': 'success', 'text': 'fixture text', 'model': 'fixture'}
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    workflow = private_workflow(db.config, db)
    workflow.transcriber = Transcriber()
    workflow.organizer = SimpleNamespace(last_error=None, last_result={'status': 'success', 'model': 'fixture'}, organize=lambda *a: '{}')
    submit(db, request())
    run = db.claim_next_task_run('worker')
    with db.lease_scope(run):
        asyncio.run(execute(workflow, {**run['payload_json'], 'task_id': run['id']}))
    assert sidecar.read_text(encoding='utf-8') == 'original evidence'
    assert original.read_bytes() == b'fixture media'


def test_l1_crash_after_analysis_write_preserves_degraded_pair_until_retry(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow, receipt
    from kenradar.sources.contracts import ContentDescriptor
    cid, old_note = seed_content(db, organized=False)
    external = '7694252203724262682'
    old_note.write_text('preexisting degraded note', encoding='utf-8')
    db.upsert_summary(external, '{}', str(old_note), 'local-fallback', 'failed')
    before = db.get_current_bundle(cid)
    item = ContentDescriptor('douyin', external, 'test-author', 'title', None, 'video', request()['source']['url'])
    class Connector:
        async def resolve_content(self, url): return item
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    summary = json.dumps({'brief_title': 'Fresh', 'brief_summary': 'Fresh analysis'})
    calls = []
    def organizer(*args):
        calls.append('organize')
        return summary
    def workflow():
        value = private_workflow(db.config, db)
        value.organizer = SimpleNamespace(last_error=None, last_result={
            'status': 'success', 'model': 'actual-fallback-model', 'provider': 'actual-fallback-provider'}, organize=organizer)
        return value
    class ProcessCrash(BaseException): pass
    upsert = db._upsert
    crash = [True]
    depth = [0]
    def crash_after_analysis(table, values, *args, **kwargs):
        # Ignore _upsert's recursive connection acquisition: inject after the
        # orchestration's write returns, or inside the linked transaction.
        depth[0] += 1
        try:
            result = upsert(table, values, *args, **kwargs)
        finally:
            depth[0] -= 1
        if depth[0] == 0 and table == 'ai_analysis' and values.get('status') == 'success' and crash[0]:
            crash[0] = False
            raise ProcessCrash('immediately after successful analysis SQL persistence')
        return result
    monkeypatch.setattr(db, '_upsert', crash_after_analysis)
    submit(db, request())
    run = db.claim_next_task_run('worker')
    payload = {**run['payload_json'], 'task_id': run['id']}
    with db.lease_scope(run), pytest.raises(ProcessCrash):
        asyncio.run(execute(workflow(), payload))
    crashed = db.get_current_bundle(cid)
    assert crashed['analysis'] == before['analysis'], 'crash exposed new successful analysis with the old degraded note'
    assert crashed['note'] == before['note']
    assert old_note.read_text(encoding='utf-8') == 'preexisting degraded note'
    assert receipt(db.get_task_run(run['id']), db)['delivery_status'] != 'complete'
    with db.lease_scope(run):
        recovered = asyncio.run(execute(workflow(), payload))['hermes']
    current = db.get_current_bundle(cid)
    assert calls == ['organize', 'organize']
    assert current['analysis']['result_text'] == summary
    assert current['analysis']['provider'] == 'actual-fallback-provider'
    assert current['analysis']['model'] == 'actual-fallback-model'
    path = Path(current['note']['note_path'])
    assert path != old_note
    rendered = path.read_text(encoding='utf-8')
    assert 'Fresh analysis' in rendered
    assert 'actual-fallback-model' in rendered
    assert recovered['stages']['note']['status'] == 'success'
    assert recovered['delivery_status'] == 'complete'


@pytest.mark.parametrize('platform,external,url', [
    ('douyin', '7694252203724262682', 'https://www.douyin.com/video/7694252203724262682'),
    ('xiaoyuzhou', '6ace3c3a195d838e2af15f95', 'https://www.xiaoyuzhoufm.com/episode/6ace3c3a195d838e2af15f95'),
])
def test_l1_degraded_note_reports_actual_models_and_quality(db, monkeypatch, platform, external, url):
    import yaml
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow, receipt, ContractError
    from kenradar.sources.contracts import ContentDescriptor
    cid, _ = seed_content(db, platform, external, organized=False)
    item = ContentDescriptor(platform, external, 'test-author', 'title', None,
        'audio' if platform == 'xiaoyuzhou' else 'video', url)
    class Connector:
        async def resolve_content(self, url): return item
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    workflow = private_workflow(db.config, db)
    workflow.config.raw['ai'] = {'organizer': {'model': 'configured-primary'}}
    workflow.organizer = SimpleNamespace(last_error='providers failed', last_result={
        'status': 'degraded', 'model': 'local-fallback', 'provider': 'local'}, organize=lambda *a: '{}')
    submit(db, request(url))
    run = db.claim_next_task_run('worker')
    with db.lease_scope(run), pytest.raises(ContractError, match='ORGANIZER_FAILED'):
        asyncio.run(execute(workflow, {**run['payload_json'], 'task_id': run['id']}))
    bundle = db.get_current_bundle(cid)
    text = Path(bundle['note']['note_path']).read_text(encoding='utf-8')
    frontmatter = yaml.safe_load(text.split('---', 2)[1])
    assert frontmatter['status'] == 'degraded', 'fallback note must not claim processed quality'
    assert frontmatter['ai_model'] == 'local-fallback'
    assert frontmatter['transcript_model'] == 'test-asr'
    assert 'test-asr' in text.split('---', 2)[2], 'body must not falsely attribute ASR to Whisper'
    result = receipt(db.get_task_run(run['id']), db)
    assert result['stages']['note']['quality'] == 'degraded'
    assert result['delivery_status'] != 'complete'


def test_l1_empty_existing_note_is_rendered_before_complete(db, monkeypatch):
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow
    from kenradar.sources.contracts import ContentDescriptor
    cid, note = seed_content(db)
    note.write_bytes(b'')
    item = ContentDescriptor('douyin', '7694252203724262682', 'test-author', 'title', None,
        'video', request()['source']['url'])
    class Connector:
        async def resolve_content(self, url): return item
    monkeypatch.setattr('kenradar.sources.registry.connector_for_url', lambda *a: Connector())
    workflow = private_workflow(db.config, db)
    workflow.organizer = SimpleNamespace(organize=lambda *a: pytest.fail('successful analysis should be reused'))
    submit(db, request())
    run = db.claim_next_task_run('worker')
    with db.lease_scope(run):
        result = asyncio.run(execute(workflow, {**run['payload_json'], 'task_id': run['id']}))['hermes']
    path = Path(db.get_current_bundle(cid)['note']['note_path'])
    assert path.stat().st_size > 0, 'empty note was reused and falsely declared complete'
    assert result['stages']['organize']['status'] == 'reused'
    assert result['stages']['note']['status'] == 'success'
    assert result['delivery_status'] == 'complete'
