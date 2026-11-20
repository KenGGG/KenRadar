import json
import pytest
from kenradar.core.organizer import ContentOrganizer


def output(source, corrected=None, summary='不能当成稳定的实盘预期。'):
    return json.dumps(dict(brief_title='波动率研究',brief_summary=summary,content_category='研究',importance_level='中',recommendation_reason='需审校',content_sections=[{'title':'限制','content':'不能当成稳定的实盘预期。'}],corrected_transcript_sections=[{'title':'原样ASR','content':source if corrected is None else corrected}],tags=['研究'],keywords=['波动率'],importance_score=3,novelty_score=3,information_density=3,business_relevance=3,value_score=3,recommended_action='review',deep_research_suggested=False),ensure_ascii=False)


def test_exact_retained_asr_may_contain_opposing_contexts_without_inventing_polarity():
    source='这个模型不能分开。另一个模型能分开好坏消息。不能当成稳定的实盘预期。'
    ContentOrganizer._validate_strict_output(output(source),source)


def test_changed_corrected_transcript_still_rejects_direct_polarity_flip():
    source='这个模型不能分开。不能当成稳定的实盘预期。'
    with pytest.raises(ValueError,match='negation reversal'):
        ContentOrganizer._validate_strict_output(output(source,corrected=source.replace('不能分开','能分开')),source)


def test_exact_retained_asr_does_not_exempt_new_summary_from_polarity_gate():
    source='这个模型不能分开。不能当成稳定的实盘预期。'
    with pytest.raises(ValueError,match='negation reversal'):
        ContentOrganizer._validate_strict_output(output(source,summary='能当成稳定的实盘预期。'),source)
