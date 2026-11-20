import json
from types import SimpleNamespace

import pytest

from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.core.organizer import ContentOrganizer
from kenradar.core.reader_contract import source_paragraphs, assemble_reader_result
from kenradar.core.workflow import Workflow
from kenradar.publishing.static_site import _collapse_transcript_section, _markdown_to_html


def test_source_backed_sections_cover_all_text_even_with_bad_offsets():
    source = '不能加杠杆。收益12.5%，不是保证收益。\n' * 180
    paragraphs = source_paragraphs(source)
    result = json.loads(assemble_reader_result({'overview': '作者讨论杠杆与收益的不确定性。',
        'sections': [{'title': '策略约束', 'start_paragraph': 4},
                     {'title': '收益边界', 'start_paragraph': 999}]}, '标题', paragraphs))
    joined = ''.join(s['content'] for s in result['corrected_transcript_sections'])
    assert ''.join(joined.split()) == ''.join(source.split())


@pytest.mark.parametrize('overview', ['', 'AI 整理失败，错误：502', '暂无摘要。', None])
def test_empty_or_operational_overview_is_not_publishable(overview):
    with pytest.raises(ValueError, match='综述'):
        assemble_reader_result({'overview': overview, 'sections': [{'title': '开场'}]}, '标题', ['原文'])


def test_reader_ignores_optional_schema_and_lexical_false_positives(sqlite_db, monkeypatch):
    _, path = sqlite_db
    config = load_config(path)
    config.raw['ai'] = {'organizer': {'enabled': True, 'output_contract': 'reader-v3',
        'providers': [{'name': 'fixture', 'requires_api_key': False, 'strict_output': True}]}}
    obj = ContentOrganizer(config)
    monkeypatch.setattr(obj, '_organize_with_provider', lambda *args: json.dumps({
        'overview': '作者比较两个模型，指出它们适用的条件不同。',
        'sections': [{'title': '模型适用条件', 'start_paragraph': 1}]}))
    source = '这个模型不能分开。另一个模型能分开好坏消息。提到“风险平价”。'
    result = json.loads(obj.organize('模型研究', source))
    assert obj.last_error is None
    assert result['corrected_transcript_sections'][0]['content'] == source


@pytest.mark.parametrize('platform', ['xiaoyuzhou', 'douyin'])
def test_reader_note_has_three_sections_and_raw_transcript(sqlite_db, platform):
    db, path = sqlite_db
    workflow = object.__new__(Workflow)
    workflow.config = load_config(path)
    workflow.config.raw['ai'] = {'organizer': {'output_contract': 'reader-v3', 'model': 'fixture'}}
    workflow.database = db
    source = '原始转录不能变化。数字12.5%。'
    result = assemble_reader_result({'overview': '作者介绍研究方法及其适用边界。',
        'sections': [{'title': '方法边界', 'start_paragraph': 1}]}, '原标题', [source])
    note = workflow._write_item_summary('episode', '原标题', result, source,
        {'platform': platform, 'blogger_name': '来源', 'video_url': 'https://example.test/source'},
        summary_status='success')
    text = note.read_text(encoding='utf8')
    assert [line for line in text.splitlines() if line.startswith('## ')] == [
        '## 一、内容综述', '## 二、分段原文', '## 三、转录原文']
    assert '知识关联' not in text and '暂无' not in text and '错误' not in text
    assert text.count(source) == 2
    html = _collapse_transcript_section(_markdown_to_html(text.split('---', 2)[-1]))
    assert '<summary>三、转录原文</summary>' in html
    from kenradar.publishing.public_site import metadata as public_metadata
    assert public_metadata(text, '原标题', 'notes/source/note.html')['summary'] == '作者介绍研究方法及其适用边界。'


def test_failed_reader_never_creates_error_note(sqlite_db):
    db, path = sqlite_db
    workflow = object.__new__(Workflow)
    workflow.config = load_config(path)
    workflow.config.raw['ai'] = {'organizer': {'output_contract': 'reader-v3'}}
    workflow.database = db
    with pytest.raises(ValueError, match='综述'):
        workflow._write_item_summary('episode', '标题', '', '原文', {'platform': 'xiaoyuzhou'}, summary_status='failed')
