from pathlib import Path
import pytest
from kenradar.core.config import AppConfig
from kenradar.core.organizer import ContentOrganizer

@pytest.mark.parametrize('effort', ['none', None])
def test_chat_provider_reasoning_effort_is_explicit_and_optional(monkeypatch, effort):
    obj=ContentOrganizer(AppConfig({'gpu_scheduler':{'enabled':False}},Path('config/config.yaml')))
    payloads=[]
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices':[{'message':{'content':'{"ok":true}'}}]}
    def post(url, **kwargs):
        payloads.append(kwargs['json'])
        return Response()
    monkeypatch.setattr(obj,'_post_with_retry',post)
    provider={'max_tokens':6500}
    if effort is not None: provider['reasoning_effort']=effort
    obj._organize_with_chat_completions('http://127.0.0.1:8080/v1','','qwen','full prompt',30,provider)
    if effort is None: assert 'reasoning_effort' not in payloads[0]
    else: assert payloads[0].get('reasoning_effort') == effort
