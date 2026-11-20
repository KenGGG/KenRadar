import json
import pytest
from test_sqlite_v2 import sqlite_db

from kenradar.core.reader_migration import upgrade_saved_reader_analysis
from kenradar.core.workflow import Workflow


def test_legacy_layout_upgrade_reuses_summary_and_all_original_words():
    first = '不能将历史收益率当成未来收益的保证。'
    second = '这里有中间被旧整理遗漏的重要原文，数字为12.5%。'
    last = '第二个话题讨论风险控制与组合配置方法。'
    source = first+second+last
    old = {'brief_summary':'作者介绍收益与风险的关系。',
           'content_sections':[{'title':'风险','content':'作者强调应保留对不确定性的认识。'}],
           'corrected_transcript_sections':[{'title':'收益边界','content':first}, {'title':'组合方法','content':last}]}
    upgraded = upgrade_saved_reader_analysis(old, source)
    assert upgraded['reader_contract'] == 'reader-v3'
    assert ''.join(section['content'] for section in upgraded['corrected_transcript_sections']) == source
    assert second in ''.join(section['content'] for section in upgraded['corrected_transcript_sections'])
    assert '作者强调' in upgraded['brief_summary']
    assert 'reader_contract' not in old


def test_source_paragraph_longer_than_12000_is_never_cut():
    body = '不得删除原文中的任何一句话。' * 1200
    sections = Workflow._normalize_corrected_transcript_sections([{'title':'完整长段','content':body}])
    assert sections[0]['content'] == body


def test_current_reader_analysis_is_unchanged():
    current = {'reader_contract':'reader-v3','brief_summary':'完整综述','corrected_transcript_sections':[{'title':'原文','content':'完整'}]}
    assert upgrade_saved_reader_analysis(current, '完整') == current


def test_format_update_is_atomic_and_preserves_ai_and_transcript_provenance(sqlite_db, tmp_path):
    db, _ = sqlite_db
    creator = db.upsert_creator('xiaoyuzhou', 'show', 'Show', '')
    cid = db.upsert_content_item('xiaoyuzhou', 'episode', creator)
    db.upsert_transcript('episode', '原始转录必须保留', '', '', 'asr-original', 'success', platform='xiaoyuzhou')
    path = tmp_path/'note.md'
    path.write_text('# Old', encoding='utf8')
    db.upsert_summary('episode', '{"brief_summary":"原有综述"}', str(path), 'original-model', 'success', platform='xiaoyuzhou')
    before = db.get_current_bundle(cid)
    with pytest.raises(ValueError, match='changed'):
        db.update_note_format(cid, 'wrong-hash', before['analysis']['result_hash'], {}, path, 'b'*64)
    assert db.get_current_bundle(cid)['analysis']['result_json'] == before['analysis']['result_json']
    db.update_note_format(cid, before['note']['content_sha256'], before['analysis']['result_hash'],
        {'brief_summary':'原有综述','reader_contract':'reader-v3'}, path, 'b'*64)
    after = db.get_current_bundle(cid)
    assert after['transcript'] == before['transcript']
    assert after['analysis']['model'] == before['analysis']['model']
    assert after['analysis']['completed_at'] == before['analysis']['completed_at']
    assert after['note']['content_sha256'] == 'b'*64
