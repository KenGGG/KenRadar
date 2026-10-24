import json
from pathlib import Path
from contextlib import contextmanager
import pytest
import requests
from kenradar.core.config import AppConfig
from kenradar.core.organizer import ContentOrganizer


def valid():
    return dict(brief_title='标题', brief_summary='作者观点', content_sections=[{'title':'观点','content':'原文'}], corrected_transcript_sections=[{'title':'原稿','content':'原文不能保持头脑清醒'}], tags=['其他'], value_score=3, recommended_action='review', content_category='投资策略', importance_level='中', keywords=['策略'], importance_score=3, novelty_score=3, information_density=3, business_relevance=3, recommendation_reason='人工审阅', deep_research_suggested=False)


@pytest.mark.parametrize('field', list(valid()))
def test_all_contract_fields_required(field):
    data=valid(); del data[field]
    with pytest.raises(ValueError, match='schema'):
        ContentOrganizer._validate_strict_output(json.dumps(data), '原文不能保持头脑清醒')


def test_strict_quality_rejects_partial_schema():
    with pytest.raises(ValueError, match='schema'):
        ContentOrganizer._validate_strict_output(json.dumps({'corrected_transcript_sections':[{'content':'原文'}]}), '原文')


def test_strict_quality_rejects_invented_source_quote():
    data=valid(); data['corrected_transcript_sections'][0]['content']+='（原文“铁水”）'
    with pytest.raises(ValueError, match='quote'):
        ContentOrganizer._validate_strict_output(json.dumps(data), '原文不能保持头脑清醒')


def test_strict_quality_accepts_complete_source_faithful_output():
    ContentOrganizer._validate_strict_output(json.dumps(valid()), '原文不能保持头脑清醒')


def test_agnes_priority_and_bounded_fallback(monkeypatch, tmp_path):
    from kenradar.core import strata_provider
    events=[]
    @contextmanager
    def managed(provider, gpu):
        events.append('start'); yield; events.append('stop')
    monkeypatch.setattr(strata_provider, 'managed_strata', managed)
    cfg=AppConfig({'gpu_scheduler':{'enabled':False},'ai':{'organizer':{'providers':[
        {'name':'agnes','model':'agnes','endpoint':'https://example.com/v1','requires_api_key':False,'retry_count':2,'rpm_limit':0},
        {'name':'qwen-strata','model':'qwen','endpoint':'http://127.0.0.1:8080/v1','managed_runtime':'kenpulse_strata','strict_output':True,'requires_api_key':False,'retry_count':1,'rpm_limit':0}]}}},tmp_path/'config.yaml')
    obj=ContentOrganizer(cfg)
    fail=[False]
    class Response:
        status_code=200
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':json.dumps(valid())}}]}
    def post(url, **kw):
        events.append(kw['json']['model'])
        if fail[0] and kw['json']['model']=='agnes': raise requests.ConnectionError('injected')
        return Response()
    monkeypatch.setattr('kenradar.core.organizer.requests.post',post)
    monkeypatch.setattr('kenradar.core.organizer.time.sleep',lambda _:None)
    obj.organize('标题','原文不能保持头脑清醒')
    assert events==['agnes']; assert obj.last_result['provider']=='agnes'
    events.clear(); fail[0]=True
    obj.organize('标题','原文不能保持头脑清醒')
    assert events==['agnes','agnes','start','qwen','stop']
    assert obj.last_result['provider']=='qwen-strata'


def test_strict_prompt_forbids_invented_source_annotations():
    prompt=ContentOrganizer._provider_prompt({'strict_output':True},'标题','原稿','完整默认提示')
    assert prompt.startswith('完整默认提示')
    assert '不得添加' in prompt and '原文' in prompt


@pytest.mark.parametrize('failure', ['timeout','json','schema','quote'])
def test_local_failure_never_returns_to_agnes(monkeypatch, tmp_path, failure):
    obj=ContentOrganizer(AppConfig({'gpu_scheduler':{'enabled':False},'ai':{'organizer':{'providers':[
        {'name':'agnes','requires_api_key':False}, {'name':'qwen','strict_output':True,'requires_api_key':False}]}}},tmp_path/'config.yaml'))
    calls=[]
    def generate(provider,key,prompt):
        calls.append(provider['name'])
        if provider['name']=='agnes' or failure=='timeout': raise requests.Timeout('injected')
        if failure=='json': return 'not json'
        if failure=='schema': return '{"content":"partial"}'
        data=valid(); data['corrected_transcript_sections'][0]['content']+='（原文“铁水”）'
        return json.dumps(data)
    monkeypatch.setattr(obj,'_organize_with_provider',generate)
    obj.organize('标题','原文不能保持头脑清醒')
    assert obj.last_result['status']=='degraded' and obj.last_error
    assert calls[0]=='agnes' and calls.count('agnes')==1
    assert calls.count('qwen') <= 2


def test_gate_rejects_summary_negation_reversal():
    data=valid(); data['brief_summary']='只适合能保持头脑清醒的人'
    with pytest.raises(ValueError, match='negation'):
        ContentOrganizer._validate_strict_output(json.dumps(data), '只适合不能保持头脑清醒，而且遵守纪律的人')


def test_gate_rejects_ascii_source_quote():
    data=valid(); data['corrected_transcript_sections'][0]['content']+='（原文"铁水"）'
    with pytest.raises(ValueError, match='quote'):
        ContentOrganizer._validate_strict_output(json.dumps(data), '原文不能保持头脑清醒')
