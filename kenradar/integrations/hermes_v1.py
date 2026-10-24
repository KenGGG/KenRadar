"""Hermes content contract. No publication/notification authorization in v1."""
from copy import deepcopy
from uuid import UUID

STAGES = ('resolve', 'download', 'transcribe', 'organize', 'note', 'publish', 'notify')
TASK_TYPE = 'hermes_content_v1'


class ContractError(ValueError):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.status = code, status


def receipt(row, database=None):
    request = row['payload_json']['request']
    stages = {stage: {'status': 'pending'} for stage in STAGES}
    for stage in ('publish', 'notify'):
        stages[stage] = {'status': 'skipped', 'reason': 'not_requested'}
    result = {'request_id': request['request_id'], 'task_id': int(row['id']),
            'content_identity': None, 'task_status': row['status'], 'delivery_status': 'pending',
            'stages': stages, 'result': {}, 'warnings': [], 'error': None}
    saved = (row.get('stats_json') or {}).get('hermes') or (row.get('progress_json') or {}).get('hermes')
    if saved:
        result.update(deepcopy(saved))
    result['task_status'] = row['status']
    if database and result['content_identity']:
        from pathlib import Path
        import json
        identity = result['content_identity']
        content = database.find_content_item(identity['platform'], identity['external_content_id'])
        if content:
            bundle = database.get_current_bundle(content['id'])
            historical = [operation for operation in database.publications.list_operations(content['id'])
                          if operation['operation'] == 'publication' and operation['status'] == 'success']
            if historical:
                result['result']['historical_publication'] = {'status': 'recorded', 'verified': False,
                    'verification_level': 'historical_record_unverified'}
                if 'existing_publication_not_retracted' not in result['warnings']:
                    result['warnings'].append('existing_publication_not_retracted')
            try:
                analysis = json.loads((bundle.get('analysis') or {}).get('result_text') or '{}')
                if isinstance(analysis, dict):
                    result['result']['summary'] = str(analysis.get('brief_summary') or analysis.get('one_sentence_conclusion') or '')
            except ValueError:
                pass
            if result['stages']['note']['status'] in ('success', 'reused'):
                path = Path((bundle.get('note') or {}).get('note_path') or '')
                if not path.is_file() or not path.stat().st_size:
                    result['stages']['note'] = {'status': 'failed'}
                    result['result'].pop('note', None)
                    result['error'] = {'code': 'ARTIFACT_MISSING', 'stage': 'note', 'message': 'Stored note artifact is missing',
                        'retryable': False, 'recommended_action': 'review_artifact'}
    required = [result['stages'][s]['status'] for s in STAGES[:5]]
    if all(s in ('success', 'reused') for s in required):
        result['delivery_status'] = 'complete'
    elif 'failed' in required or row['status'] in ('failed', 'cancelled', 'success'):
        result['delivery_status'] = 'partial_failed' if result['result'].get('note') or result['result'].get('evidence') else 'failed'
    else:
        result['delivery_status'] = 'pending'
    return result


def private_workflow(config, database):
    """Reuse processing services without importing subscriptions or constructing delivery services."""
    from kenradar.core.config import AppConfig
    from kenradar.core.workflow import Workflow
    from kenradar.core.transcriber import Transcriber
    from kenradar.core.organizer import ContentOrganizer
    root = config.data_dir / 'hermes-private'
    raw = deepcopy(config.raw)
    raw.setdefault('integrations', {}).setdefault('hermes_v1', {})['safe_network'] = True
    raw.setdefault('download', {})['path'] = str(root / 'media')
    raw.setdefault('output', {})['obsidian_root'] = str(root)
    raw.setdefault('sources', {}).setdefault('xiaoyuzhou', {})['audio_temp_dir'] = str(root / 'media')
    raw.setdefault('publishing', {})['enabled'] = False
    raw['publishing'].setdefault('github_pages', {})['enabled'] = False
    raw.setdefault('notification', {})['enabled'] = False
    safe_config = AppConfig(raw, config.path, config.source_revision)
    workflow = object.__new__(Workflow)
    workflow.config, workflow.database = safe_config, database
    workflow.transcriber = Transcriber(safe_config, database)
    workflow.organizer = ContentOrganizer(safe_config)
    return workflow


async def execute(workflow, payload):
    """Persist sanitized stage failure before allowing the durable worker to retry."""
    from kenradar.storage.sqlite_database import LeaseLost
    from kenradar.integrations.safe_network import configured_network
    try:
        with configured_network(workflow.config):
            return await _execute(workflow, payload)
    except LeaseLost:
        raise
    except Exception as exc:
        database, run_id = workflow.database, payload['task_id']
        row = database.get_task_run(run_id)
        result = receipt(row)
        failed_stage = next((s for s in STAGES if result['stages'][s]['status'] == 'running'), 'resolve')
        code = exc.code if isinstance(exc, ContractError) else getattr(exc, 'error_code', f'{failed_stage.upper()}_FAILED')
        retryable = code not in ('UNSAFE_SOURCE_URL', 'UNSUPPORTED_SOURCE', 'POLICY_CONFLICT', 'INVALID_REQUEST', 'CAPABILITY_UNAVAILABLE', 'SOURCE_PARSE_CHANGED', 'SOURCE_UNAVAILABLE', 'SOURCE_IDENTITY_MISMATCH')
        result['stages'][failed_stage] = {'status': 'failed'}
        result['error'] = {'code': code, 'stage': failed_stage, 'message': f'{failed_stage} did not complete',
            'retryable': retryable, 'recommended_action': 'retry_failed_stage' if retryable else 'review_source_or_policy'}
        result['delivery_status'] = 'partial_failed' if result['result'].get('evidence') else 'failed'
        progress = deepcopy(row.get('progress_json') or {})
        progress['hermes'] = result
        database.heartbeat_task_run(run_id, progress=progress)
        # Never forward provider exceptions or transcript text into task errors.
        raise ContractError(code, f'{code}: {failed_stage} did not complete') from None
    finally:
        row = workflow.database.get_task_run(payload['task_id'])
        lock = (row.get('progress_json') or {}).get('content_lock') if row else None
        if lock and lock.get('owner') == row.get('lease_token'):
            try:
                progress = dict(row.get('progress_json') or {})
                progress.pop('content_lock', None)
                workflow.database.heartbeat_task_run(row['id'], progress=progress)
                workflow.database.release_resource_lease(lock['key'], lock['owner'])
            except LeaseLost:
                pass  # A replacement worker owns the task; leave expiry recovery to it.


async def _execute(workflow, payload):
    from kenradar.sources.registry import connector_for_url
    from pathlib import Path
    database = workflow.database
    request = validate(payload['request'])
    run_id = payload['task_id']
    row = database.get_task_run(run_id)
    # Every attempt owns a disjoint artifact tree; activation is a fenced DB pointer.
    # A late attempt can leave garbage here, never replace/delete the winner's files.
    attempt_root = workflow.config.data_dir / 'hermes-private' / 'attempts' / row['lease_token']
    workflow.config.raw.setdefault('output', {})['obsidian_root'] = str(attempt_root)
    workflow.config.raw.setdefault('download', {})['path'] = str(attempt_root / 'media')
    workflow.config.raw.setdefault('sources', {}).setdefault('xiaoyuzhou', {})['audio_temp_dir'] = str(attempt_root / 'media')
    result = receipt(row)
    result['error'] = None

    from dataclasses import asdict
    from datetime import datetime
    from kenradar.sources.contracts import ContentDescriptor
    progress = deepcopy(row.get('progress_json') or {})
    resolved = progress.get('resolved_content') or payload.get('resolved_content')

    def stage(name, status, **details):
        result['stages'][name] = {'status': status, **details}
        progress['hermes'] = result
        database.heartbeat_task_run(run_id, progress=progress)

    if resolved:
        values = deepcopy(resolved)
        if values.get('published_at'):
            values['published_at'] = datetime.fromisoformat(values['published_at'])
        item = ContentDescriptor(**values)
        connector = None
        stage('resolve', 'reused')
    else:
        stage('resolve', 'running')
        connector = connector_for_url(request['source']['url'], workflow.config)
        item = await connector.resolve_content(request['source']['url'])
        from urllib.parse import urlsplit
        expected_platform = source_platform(request['source']['url'])
        requested_url = urlsplit(request['source']['url'])
        expected_id = None if requested_url.hostname == 'v.douyin.com' else requested_url.path.rstrip('/').rsplit('/', 1)[-1]
        if item.platform != expected_platform or (expected_id and item.external_content_id != expected_id):
            raise ContractError('SOURCE_IDENTITY_MISMATCH', 'Resolved content does not match the requested item')
        resolved = asdict(item)
        resolved['published_at'] = item.published_at.isoformat() if item.published_at else None
        progress['resolved_content'] = resolved
        stage('resolve', 'success')
    result['content_identity'] = {'platform': item.platform, 'external_content_id': item.external_content_id}
    lock_key = f'hermes-content:{item.platform}:{item.external_content_id}'
    if not database.acquire_resource_lease(lock_key, row['lease_token'], lease_seconds=300):
        stage('resolve', 'running')
        raise ContractError('CONTENT_BUSY', 'Another worker is processing this content')
    progress['content_lock'] = {'key': lock_key, 'owner': row['lease_token']}
    database.heartbeat_task_run(run_id, progress=progress)
    content = database.find_content_item(item.platform, item.external_content_id)
    if not content:
        from sqlalchemy import select
        creators, platforms = database.table('creator'), database.table('platform')
        source_id = item.external_source_id or 'single-content'
        with database.connect() as conn:
            known = conn.execute(select(creators.c.id).join(platforms, platforms.c.id == creators.c.platform_id)
                .where(platforms.c.code == item.platform, creators.c.platform_uid == source_id)).fetchone()
        creator = known['id'] if known else database.upsert_creator(item.platform, source_id,
            item.external_source_id or 'Unknown creator', '', enabled=False)
        published = item.published_at
        if published and published.tzinfo is None:
            published = published.astimezone()
        cid = database.upsert_content_item(item.platform, item.external_content_id, creator,
            title=item.title, content_type=item.media_type, source_url=item.url, media_url=item.media_url,
            publish_time=published, download_status='pending', extra={'hermes_private': True})
        content = database.find_content_item(item.platform, item.external_content_id)
    else:
        cid = content['id']
        database.upsert_content_item(item.platform, item.external_content_id, content['creator_id'],
            extra={'hermes_private': True})
    bundle = database.get_current_bundle(cid)
    transcript, analysis, note = (bundle.get(k) or {} for k in ('transcript', 'analysis', 'note'))
    metadata = {'platform': item.platform, 'blogger_id': item.external_source_id,
        'blogger_name': str((item.raw_metadata.get('author') or {}).get('nickname') or item.raw_metadata.get('podcast_title') or item.external_source_id or 'Unknown creator'),
        'publish_time': item.published_at.isoformat() if item.published_at else '',
        'video_url': item.url, 'source_url': item.url, 'media_type': item.media_type}
    text = str(transcript.get('text_content') or '')
    if transcript.get('status') == 'success' and text:
        stage('download', 'reused', reason='stored_transcript_preserves_media_evidence')
        stage('transcribe', 'reused', model=str(transcript.get('model') or 'unknown'))
    else:
        media_path = Path(content.get('local_path') or '')
        if media_path.is_file() and media_path.stat().st_size:
            import shutil
            isolated_media = workflow.config.download_dir / media_path.name
            isolated_media.parent.mkdir(parents=True, exist_ok=True)
            if media_path.resolve() != isolated_media.resolve():
                shutil.copyfile(media_path, isolated_media)
            media_path = isolated_media
            stage('download', 'reused')
        else:
            stage('download', 'running')
            connector = connector or connector_for_url(request['source']['url'], workflow.config)
            downloaded = await connector.download(item, workflow.config.download_dir)
            if not downloaded.success or not downloaded.path or not Path(downloaded.path).is_file():
                raise ContractError(downloaded.error_code or 'DOWNLOAD_FAILED', 'Media download failed')
            media_path = Path(downloaded.path)
            database.upsert_content_item(item.platform, item.external_content_id, content['creator_id'],
                local_path=str(media_path), download_status='done')
            stage('download', 'success')
        stage('transcribe', 'running')
        transcript = await workflow.transcriber.transcribe(item.external_content_id, media_path, metadata)
        text = str(transcript.get('text') or '')
        if transcript.get('status') != 'success' or not text:
            raise ContractError('TRANSCRIBE_FAILED', 'Transcription did not produce valid text')
        stage('transcribe', 'success', model=str(transcript.get('model') or 'unknown'))
    result['result'] = {'title': item.title, 'evidence': {'kind': 'stored_transcript', 'locator': f'transcript:{cid}'}}
    if analysis.get('status') == 'success' and analysis.get('result_text'):
        summary = analysis['result_text']
        workflow.config.raw.setdefault('ai', {}).setdefault('organizer', {})['model'] = str(analysis.get('model') or 'unknown')
        stage('organize', 'reused', model=str(analysis.get('model') or 'unknown'), provider=str(analysis.get('provider') or 'unknown'))
    else:
        stage('organize', 'running')
        summary = workflow.organizer.organize(item.title, text, metadata)
        provenance = getattr(workflow.organizer, 'last_result', {})
        model = str(provenance.get('model') or 'unknown')
        workflow.config.raw.setdefault('ai', {}).setdefault('organizer', {})['model'] = model
        if workflow.organizer.last_error or provenance.get('status') == 'degraded' or not summary:
            # Preserve a usable but explicitly degraded local note, never call it organized success.
            degraded = workflow._write_item_summary(item.external_content_id, item.title, summary or '{}', text, metadata,
                summary_status='failed', transcript_model=str(transcript.get('model') or ''))
            database.upsert_summary(item.external_content_id, summary or '{}', str(degraded),
                str(workflow.config.get('ai.organizer.model', '')), 'failed', 'ORGANIZER_FAILED', platform=item.platform)
            result['result']['note'] = {'kind': 'local_artifact', 'locator': f'content-note:{cid}', 'degraded': True}
            stage('note', 'success', quality='degraded')
            raise ContractError('ORGANIZER_FAILED', 'Organizer failed or produced a degraded result')
        # Keep successful analysis attempt-local until its actual note exists.
        # Activating analysis alone could make a retry reuse an old degraded note.
        stage('organize', 'success', model=model, provider=str(provenance.get('provider') or 'unknown'))
    stored_note = Path(note.get('note_path') or '')
    if stored_note.is_file() and stored_note.stat().st_size and analysis.get('status') == 'success':
        stage('note', 'reused')
    else:
        stage('note', 'running')
        path = workflow._write_item_summary(item.external_content_id, item.title, summary, text, metadata,
            summary_status='success', transcript_model=str(transcript.get('model') or ''))
        if not path.is_file() or not path.stat().st_size:
            raise ContractError('NOTE_FAILED', 'Note artifact missing')
        import json
        try:
            parsed_summary = json.loads(summary)
        except (ValueError, TypeError):
            parsed_summary = {}
        database.replace_analysis_and_note(cid, {
            'result_json': parsed_summary, 'result_text': summary,
            'model': result['stages']['organize'].get('model', 'unknown'),
            'provider': result['stages']['organize'].get('provider', 'unknown'),
            'status': 'success', 'error_message': None},
            {'note_path': str(path), 'title': path.stem})
        stage('note', 'success')
    result['result']['note'] = {'kind': 'local_artifact', 'locator': f'content-note:{cid}'}
    result['delivery_status'] = 'complete'
    progress['hermes'] = result
    database.heartbeat_task_run(run_id, progress=progress)
    return {'hermes': result, 'processed': 1}


def validate(payload):
    import re
    from typing import Literal
    from pydantic import BaseModel, ConfigDict, Field, ValidationError

    class Closed(BaseModel):
        model_config = ConfigDict(extra='forbid', strict=True)

    class Source(Closed):
        url: str = Field(min_length=1, max_length=2048)

    class Delivery(Closed):
        visibility: Literal['private', 'public']
        publish: Literal['none', 'github_pages']
        notify: Literal['none', 'feishu']

    class Execution(Closed):
        reuse_existing: bool

    class Request(Closed):
        contract_version: Literal['1.0']
        request_id: str
        operation: Literal['process_content']
        source: Source
        purpose: Literal['knowledge_note', 'transcript']
        instructions: str = Field(default='', max_length=4096)
        delivery: Delivery
        execution: Execution

    try:
        parsed = Request.model_validate(payload)
        if not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', parsed.request_id):
            raise ValueError('uuid')
        UUID(parsed.request_id)
    except (ValidationError, ValueError, TypeError):
        raise ContractError('INVALID_REQUEST', 'Invalid fields, types, version or request UUID') from None
    source_platform(parsed.source.url)
    if parsed.delivery.visibility == 'private' and parsed.delivery.publish != 'none':
        raise ContractError('POLICY_CONFLICT', 'Private content cannot be published')
    if parsed.delivery.publish != 'none' or parsed.delivery.notify != 'none':
        raise ContractError('CAPABILITY_UNAVAILABLE', 'Authorized external delivery is not supported by this adapter')
    if parsed.purpose != 'knowledge_note' or not parsed.execution.reuse_existing or parsed.instructions:
        raise ContractError('CAPABILITY_UNAVAILABLE', 'Transcript-only, force and custom instructions are not supported')
    return deepcopy(payload)


def source_platform(url):
    import ipaddress
    import re
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if (parsed.scheme not in ('https', 'http') or not host or parsed.username or parsed.password
                or parsed.port not in (None, 80, 443) or parsed.fragment or any(c.isspace() for c in url)):
            raise ValueError()
        if host == 'localhost' or host.endswith('.local'):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
    except ValueError:
        raise ContractError('UNSAFE_SOURCE_URL', 'Unsafe source URL') from None
    if host in ('www.douyin.com', 'douyin.com', 'www.iesdouyin.com', 'iesdouyin.com') and re.fullmatch(r'/(video|share/video)/[0-9]+/?', parsed.path):
        return 'douyin'
    if host == 'v.douyin.com' and re.fullmatch(r'/[A-Za-z0-9_-]+/?', parsed.path):
        return 'douyin'
    if host in ('www.xiaoyuzhoufm.com', 'xiaoyuzhoufm.com') and re.fullmatch(r'/episode/[0-9a-fA-F]{24}/?', parsed.path):
        return 'xiaoyuzhou'
    raise ContractError('UNSUPPORTED_SOURCE', 'Only Douyin videos and Xiaoyuzhou episodes are supported')


def submit(database, payload):
    request = validate(payload)
    row = database.enqueue_task_run(TASK_TYPE, {'request': request, 'policy_version': 'hermes-private-v1'},
        message='Hermes single content task', requested_by='hermes-loopback',
        idempotency_key='hermes-v1:' + str(UUID(request['request_id'])), max_attempts=3)
    if row['payload_json']['request'] != request:
        raise ContractError('REQUEST_ID_CONFLICT', 'request_id is already bound to a different request', 409)
    return receipt(row)


def retry(database, task_id, payload):
    import re
    from sqlalchemy import select
    if (not isinstance(payload, dict) or set(payload) != {'request_id', 'stage'}
        or not isinstance(payload['request_id'], str)
        or not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', payload['request_id'])
        or payload['stage'] not in STAGES[:5]):
        raise ContractError('INVALID_REQUEST', 'retry requires a UUID and a supported stage')
    key = 'hermes-v1:' + str(UUID(payload['request_id']))
    table = database.table('task_run')
    with database.connect() as conn:
        existing = conn.execute(select(table).where(table.c.idempotency_key == key)).fetchone()
    if existing:
        stored = existing['payload_json']
        if stored.get('retry_of') != task_id or stored.get('retry_stage') != payload['stage']:
            raise ContractError('REQUEST_ID_CONFLICT', 'request_id already bound to a different operation', 409)
        return receipt(dict(existing))
    original = database.get_task_run(task_id)
    if not original or original['task_type'] != TASK_TYPE:
        raise ContractError('TASK_NOT_FOUND', 'Hermes task not found', 404)
    result = receipt(original)
    error = result.get('error') or {}
    if (original['status'] not in ('failed', 'success') or result['stages'][payload['stage']]['status'] != 'failed'
            or error.get('stage') != payload['stage'] or not error.get('retryable')):
        raise ContractError('RETRY_NOT_ALLOWED', 'Only terminal, retryable failed stages can be recovered', 409)
    request = deepcopy(original['payload_json']['request'])
    request['request_id'] = payload['request_id']
    validate(request)
    values = {'request': request, 'policy_version': 'hermes-private-v1', 'retry_of': task_id,
        'retry_stage': payload['stage'], 'resolved_content': (original.get('progress_json') or {}).get('resolved_content')}
    row = database.enqueue_task_run(TASK_TYPE, values, 'Hermes failed-stage recovery', 'hermes-loopback', idempotency_key=key)
    if row['payload_json'] != values:
        raise ContractError('REQUEST_ID_CONFLICT', 'request_id already bound to a different operation', 409)
    return receipt(row)


def capabilities():
    return {'contract_versions': ['1.0'], 'supported_platforms': ['douyin', 'xiaoyuzhou'],
            'supported_purposes': ['knowledge_note'], 'private_processing': True,
            'stage_retry': True, 'publish_targets': [], 'notification_channels': [],
            'policy_version': 'hermes-private-v1'}
