from contextlib import contextmanager
import pytest
import requests

class GPU:
    def __init__(self): self.locked=False
    @contextmanager
    def gpu_task(self, name):
        self.locked=True
        try: yield
        finally: self.locked=False

@pytest.mark.parametrize('initial,failure,actions', [
    ('stopped',None,['start','stop']), ('ready',None,[]),
    ('stopped','inference',['start','stop']), ('stopped','startup',['start','stop']),
    ('loading',None,[]), ('stopped','timeout',['start','stop'])])
def test_managed_lifecycle_ownership(monkeypatch, initial, failure, actions):
    from kenradar.core.strata_provider import managed_strata
    gpu=GPU(); calls=[]; state=[initial]; clock=[0]
    class Response:
        def __init__(self,data): self.data=data
        def raise_for_status(self): pass
        def json(self): return self.data
    def get(url, **kw):
        assert gpu.locked
        if url.endswith('/api/token'): return Response({'token':'private-test-token'})
        if url.endswith('/health'): return Response({'loaded':True,'model':'qwen3.8-flash-next-iq2_xs'})
        return Response({'strata':{'state':state[0],'busy':False,'desired':initial!='stopped','current_model':'IQ2_XS' if state[0]=='ready' else None}})
    def post(url, **kw):
        assert gpu.locked
        assert kw['headers']['Origin']=='http://127.0.0.1:9377'
        action=kw['json']['action']; calls.append(action)
        state[0]=('error' if failure=='startup' else 'loading' if failure=='timeout' else 'ready') if action=='start' else 'stopped'
        return Response({'ok':True})
    monkeypatch.setattr('kenradar.core.strata_provider.requests.get',get)
    monkeypatch.setattr('kenradar.core.strata_provider.requests.post',post)
    monkeypatch.setattr('kenradar.core.strata_provider.time.monotonic',lambda:clock[0])
    monkeypatch.setattr('kenradar.core.strata_provider.time.sleep',lambda t:clock.__setitem__(0,clock[0]+t))
    provider={'endpoint':'http://127.0.0.1:8080/v1','model':'qwen3.8-flash-next-iq2_xs','startup_timeout':2}
    if failure or initial=='loading':
        with pytest.raises((RuntimeError,requests.RequestException)):
            with managed_strata(provider,gpu):
                if failure=='inference': raise requests.Timeout('test')
    else:
        with managed_strata(provider,gpu): assert gpu.locked
    assert calls==actions
    assert not gpu.locked
