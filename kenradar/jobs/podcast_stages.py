"""Two podcast stages executed by the existing durable worker, never a second worker."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from kenradar.core.codex_organizer import CodexOrganizer
from kenradar.sources.base import ContentItem
from kenradar.sources.xiaoyuzhou.adapter import XiaoyuzhouAdapter


async def execute_podcast_stage(workflow, task_type, payload):
    data = dict(payload['item'])
    if payload.get('external_content_id') and str(data.get('content_id')) != str(payload['external_content_id']):
        raise ValueError('Podcast snapshot content identity mismatch')
    if data['platform'] != 'xiaoyuzhou':
        raise ValueError('Podcast stage only accepts xiaoyuzhou')
    if data.get('published_at'):
        data['published_at'] = datetime.fromisoformat(data['published_at'])
        if data['published_at'].tzinfo is None:
            data['published_at'] = data['published_at'].replace(tzinfo=ZoneInfo(
                str(workflow.config.get('app.timezone', 'Asia/Shanghai'))))
    item = ContentItem(**data)
    # Use the claimed task's lease-fenced database for all stage writes.
    workflow.database = getattr(workflow, 'delivery_database', workflow.database)
    workflow.transcriber.database = workflow.database
    from kenradar.integrations.privacy import private_content
    if private_content(workflow.database, item.content_id, 'xiaoyuzhou') or item.raw_metadata.get('hermes_private'):
        raise ValueError('PRIVATE_CONTENT: batch external processing is forbidden')
    if task_type in {'podcast_codex', 'podcast_organize'}:
        if not workflow.database.get_successful_transcript(item.content_id, platform='xiaoyuzhou'):
            raise RuntimeError('Waiting for successful GPU transcript; AI stage cannot download or transcribe')
        if task_type == 'podcast_codex':
            if not workflow.config.get('ai.organizer.codex_batch_enabled', True):
                raise ValueError('Terra 集中整理已由用户取消')
            workflow.config = deepcopy(workflow.config)
            workflow.config.raw['ai']['organizer']['model'] = 'gpt-5.6-terra'
            workflow.organizer = CodexOrganizer(workflow.config)
    return await workflow._process_xiaoyuzhou_item(
        item, XiaoyuzhouAdapter(workflow.config), publish=task_type in {'podcast_codex', 'podcast_organize'},
        transcribe_only=task_type == 'podcast_transcribe')
