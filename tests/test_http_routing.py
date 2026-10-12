import requests
import json
import threading
from kenradar.core.http_routing import HttpsAddressAdapter

def test_route_preserves_tls_hostname_and_ca_verification(monkeypatch):
    adapter=HttpsAddressAdapter('apihub.agnes-ai.com','104.18.19.62')
    captured={}
    def pool(**kwargs):
        captured.update(kwargs)
        return object()
    monkeypatch.setattr(adapter.poolmanager,'connection_from_host',pool)
    request=requests.Request('POST','https://apihub.agnes-ai.com/v1/chat/completions').prepare()
    adapter.get_connection_with_tls_context(request,True)
    assert captured['host']=='104.18.19.62'
    assert captured['pool_kwargs']['server_hostname']=='apihub.agnes-ai.com'
    assert captured['pool_kwargs']['assert_hostname']=='apihub.agnes-ai.com'
    assert captured['pool_kwargs']['cert_reqs']=='CERT_REQUIRED'
    assert request.headers['Host']=='apihub.agnes-ai.com'


def test_invalid_ai_json_is_retried_once_then_validated(monkeypatch):
    from types import SimpleNamespace
    from kenradar.core.organizer import ContentOrganizer
    organizer=object.__new__(ContentOrganizer)
    organizer.config=SimpleNamespace(get=lambda key, default=None: default)
    organizer._semaphore=threading.BoundedSemaphore(1)
    organizer._organizer_providers=lambda: [{'name':'fixture','requires_api_key':False}]
    organizer._provider_api_key=lambda p: ''
    organizer._provider_transcript=lambda p,t: t
    organizer._provider_prompt=lambda p,title,t,prompt: prompt
    organizer._build_prompt=lambda *args: 'fixture prompt'
    calls=[]
    good=json.dumps({'brief_summary':'摘要','corrected_transcript_sections':[{'content':'原始口播'}]},ensure_ascii=False)
    def request(*args):
        calls.append(1)
        return 'invalid JSON' if len(calls)==1 else good
    organizer._organize_with_provider=request
    assert json.loads(organizer.organize('标题','原始口播'))['brief_summary']=='摘要'
    assert len(calls)==2
    assert organizer.last_error is None
