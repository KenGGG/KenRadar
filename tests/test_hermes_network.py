"""Security boundary tests; fake sockets only, never live platform requests."""
import json
import pytest


def dns_message(host='www.douyin.com', records=None, qtype=1):
    return {'Status': 0, 'TC': False, 'Question': [{'name': host + '.', 'type': qtype}],
            'Answer': records if records is not None else [
                {'name': host + '.', 'type': 5, 'TTL': 30, 'data': 'cdn.example.'},
                {'name': 'cdn.example.', 'type': qtype, 'TTL': 30,
                 'data': '1.1.1.2' if qtype == 1 else '2606:4700:4700::1111'}]}


def test_dns_answers_require_valid_complete_public_chain():
    assert hasattr(net, 'validate_dns_answers'), 'missing DNS answer validation'
    assert net.validate_dns_answers(dns_message(), 'www.douyin.com', 1) == ['1.1.1.2']
    cases = []
    for ip in ('198.18.0.61', '127.0.0.1', '10.0.0.1', '::ffff:127.0.0.1', 'not-an-ip'):
        msg = dns_message()
        msg['Answer'].append({'name': 'cdn.example.', 'type': 1, 'TTL': 30, 'data': ip})
        cases.append(msg)
    msg = dns_message(); msg['Answer'][1]['name'] = 'unrelated.example.'; cases.append(msg)
    msg = dns_message(); msg['Question'][0]['name'] = 'wrong.example.'; cases.append(msg)
    msg = dns_message(); msg['Answer'][1]['type'] = 16; cases.append(msg)
    msg = dns_message(); msg['Answer'][0]['data'] = 'www.douyin.com.'; cases.append(msg)
    msg = dns_message(); msg['Answer'][0]['TTL'] = -1; cases.append(msg)
    msg = dns_message(); msg['TC'] = True; cases.append(msg)
    msg = dns_message(); msg['Status'] = 3; cases.append(msg)
    cases += [dns_message(records=[]), {'Status': 0}, None]
    for message in cases:
        with pytest.raises(ContractError) as error:
            net.validate_dns_answers(message, 'www.douyin.com', 1)
        assert error.value.code == 'UNSAFE_SOURCE_URL'


from kenradar.integrations import safe_network as net
from kenradar.integrations.hermes_v1 import ContractError


class FakeResponse:
    def __init__(self, body=b'ok', status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}
        self.closed = False

    def stream(self, *args, **kwargs):
        yield self.body

    def close(self):
        self.closed = True

    def release_conn(self):
        pass


def fake_pools(monkeypatch, responses):
    calls = []
    class Pool:
        def __init__(self, ip, port, **kwargs):
            self.ip, self.kwargs = ip, kwargs
        def request(self, method, target, **kwargs):
            calls.append((self.ip, self.kwargs, method, target, kwargs))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        def close(self):
            pass
    monkeypatch.setattr(net.urllib3, 'HTTPSConnectionPool', Pool)
    monkeypatch.setattr(net.urllib3, 'HTTPConnectionPool', Pool)
    return calls


def test_opt_in_doh_replaces_fake_dns_without_waiving_safety(monkeypatch):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('198.18.0.61', 443))])
    calls = fake_pools(monkeypatch, [FakeResponse(json.dumps(dns_message()).encode()), FakeResponse()])
    with pytest.raises(ContractError):
        with net.safe_get('https://www.douyin.com/video/123'):
            pass
    assert not calls
    with net.safe_get('https://www.douyin.com/video/123', policy=net.TrustedDoHPolicy('cloudflare')) as response:
        assert response.text == 'ok'
    assert [call[0] for call in calls] == ['1.1.1.1', '1.1.1.2']
    for call, hostname in zip(calls, ['cloudflare-dns.com', 'www.douyin.com']):
        assert call[1]['server_hostname'] == call[1]['assert_hostname'] == hostname
        assert call[1]['cert_reqs'] == 'CERT_REQUIRED'
        assert call[1]['ca_certs']
        assert call[4]['redirect'] is False and call[4]['retries'] is False


def test_redirect_downgrade_is_rejected_before_second_connection(monkeypatch):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    calls = fake_pools(monkeypatch, [FakeResponse(status=302, headers={'Location': 'http://public.example/' }), FakeResponse()])
    with pytest.raises(ContractError) as error:
        with net.safe_get('https://www.douyin.com/video/123'):
            pass
    assert error.value.code == 'UNSAFE_SOURCE_URL'
    assert len(calls) == 1


def test_configured_doh_is_acceptance_only_and_context_scoped(monkeypatch):
    assert hasattr(net, 'configured_network'), 'missing acceptance-only policy context'
    class Config:
        def __init__(self, values): self.values = values
        def get(self, key, default=None): return self.values.get(key, default)
    values = {'integrations.hermes_v1.trusted_doh_resolver': 'google',
              'integrations.hermes_v1.isolated_acceptance': True,
              'app.data_dir': 'D:/Projects/KenRadar/data/test-migration/hermes-v1/acceptance'}
    with net.configured_network(Config(values)):
        assert net.current_policy().resolver == 'google'
    assert net.current_policy() is None
    for key, value in [('integrations.hermes_v1.isolated_acceptance', False), ('app.data_dir', 'data')]:
        with pytest.raises(ContractError):
            with net.configured_network(Config({**values, key: value})):
                pass
    with net.configured_network(Config({})):
        assert net.current_policy() is None


def test_decoded_media_bytes_and_total_deadline_are_bounded(monkeypatch):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    fake_pools(monkeypatch, [FakeResponse(b'12345'), FakeResponse(b'x')])
    with pytest.raises(ContractError):
        with net.safe_get('https://cdn.example/file', max_bytes=4) as response:
            list(response.iter_content())
    clock = [0]
    monkeypatch.setattr(net.time, 'monotonic', lambda: clock[0])
    with net.safe_get('https://cdn.example/file', total_timeout=2) as response:
        clock[0] = 3
        with pytest.raises(ContractError):
            list(response.iter_content())


def test_credentials_are_exact_https_host_scoped_and_cannot_redirect(monkeypatch):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    calls = fake_pools(monkeypatch, [FakeResponse(), FakeResponse(status=302, headers={'Location': 'https://other.example/'}), FakeResponse()])
    headers = {'Cookie': 'session=fake-test-cookie', 'Authorization': 'Bearer fake-test', 'Host': 'evil'}
    with net.safe_get('https://www.douyin.com/api', headers=headers, credential_host='www.douyin.com'):
        pass
    assert calls[0][4]['headers']['Cookie'] == headers['Cookie']
    assert calls[0][4]['headers']['Host'] == 'www.douyin.com'
    with pytest.raises(ContractError):
        with net.safe_get('https://www.douyin.com/api?msToken=fake', headers=headers, credential_host='www.douyin.com'):
            pass
    assert len(calls) == 2
    with net.safe_get('https://other.example/', headers=headers):
        pass
    assert 'Cookie' not in calls[-1][4]['headers']
    assert 'Authorization' not in calls[-1][4]['headers']


import asyncio
from kenradar.sources.douyin.connector import DouyinConnector
from kenradar.vendor.douyin_downloader.api_client import DouyinAPIClient, MsTokenManager


class PrivateConfig:
    cookies = {'sessionid': 'fake-test'}
    def get(self, key, default=None):
        return {'integrations.hermes_v1.safe_network': True,
                'download.browser_fallback.enabled': True}.get(key, default)


def test_canonical_private_detail_uses_guarded_signed_api_without_token_or_browser_egress(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError('unguarded legacy session/browser used')
    monkeypatch.setattr(DouyinAPIClient, '_ensure_session', forbidden)
    import kenradar.core.source_resolver as resolver
    monkeypatch.setattr(resolver, 'resolve_video_with_browser', forbidden)
    monkeypatch.setattr(MsTokenManager, '_gen_real_ms_token', lambda *a: pytest.fail('remote token bootstrap'))
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    detail = {'aweme_id': '7694252203724262682', 'desc': 'test', 'author': {'sec_uid': 'test-user'}}
    calls = fake_pools(monkeypatch, [FakeResponse(json.dumps({'aweme_detail': detail}).encode())])
    content = asyncio.run(DouyinConnector(PrivateConfig()).resolve_content('https://www.douyin.com/video/7694252203724262682'))
    assert content.external_content_id == detail['aweme_id']
    assert '/aweme/v1/web/aweme/detail/' in calls[0][3]
    assert 'msToken=' in calls[0][3]
    assert 'X-Bogus=' in calls[0][3] or 'a_bogus=' in calls[0][3]
    assert calls[0][4]['headers']['Cookie'].startswith('sessionid=fake-test')


def test_private_source_resolution_never_calls_legacy_http(monkeypatch):
    import kenradar.core.source_resolver as resolver
    monkeypatch.setattr(resolver, 'resolve_douyin_source', lambda *a, **k: pytest.fail('legacy source egress'))
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    item = {'aweme_id': '123', 'author': {'sec_uid': 'test-user', 'nickname': 'test-name'}}
    calls = fake_pools(monkeypatch, [FakeResponse(json.dumps({'aweme_list': [item]}).encode())])
    source = asyncio.run(DouyinConnector(PrivateConfig()).resolve_source('https://www.douyin.com/user/test-user'))
    assert source.external_source_id == 'test-user'
    assert source.display_name == 'test-name'
    assert '/aweme/v1/web/aweme/post/' in calls[0][3]


def test_private_listing_uses_guarded_api(monkeypatch):
    async def forbidden(*a, **k): raise AssertionError('legacy listing session')
    monkeypatch.setattr(DouyinAPIClient, '_ensure_session', forbidden)
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    fake_pools(monkeypatch, [FakeResponse(json.dumps({'aweme_list': [{'aweme_id': '123'}]}).encode())])
    connector = DouyinConnector(PrivateConfig())
    page = asyncio.run(connector.list_recent(connector.map_source('user', 'name')))
    assert page.items[0].external_content_id == '123'


def test_second_detail_fetch_rejects_nonpublic_redirect_before_media(monkeypatch, tmp_path):
    async def forbidden(*a, **k): raise AssertionError('legacy second detail session')
    monkeypatch.setattr(DouyinAPIClient, '_ensure_session', forbidden)
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    calls = fake_pools(monkeypatch, [FakeResponse(status=302, headers={'Location': 'https://127.0.0.1/secret'})])
    config = PrivateConfig(); config.download_dir = tmp_path
    connector = DouyinConnector(config)
    result = asyncio.run(connector.download(connector.map_content({'aweme_id': '123'}), tmp_path))
    assert result.success is False and result.error_code == 'UNSAFE_SOURCE_URL'
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('stage', ['resolver', 'source'])
def test_tls_failures_are_fail_closed_without_fallback(monkeypatch, stage):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: pytest.fail('DoH must not fall back to OS DNS'))
    responses = [net.urllib3.exceptions.SSLError('certificate hostname mismatch')]
    if stage == 'source': responses.insert(0, FakeResponse(json.dumps(dns_message()).encode()))
    calls = fake_pools(monkeypatch, responses)
    with pytest.raises(ContractError) as error:
        with net.safe_get('https://www.douyin.com/video/123', policy=net.TrustedDoHPolicy('cloudflare')):
            pass
    assert error.value.code == 'SOURCE_UNAVAILABLE'
    assert len(calls) == (1 if stage == 'resolver' else 2)


def test_mixed_trusted_dns_answers_reject_before_source_connection(monkeypatch):
    message = dns_message()
    message['Answer'].append({'name': 'cdn.example.', 'type': 1, 'TTL': 30, 'data': '10.0.0.1'})
    calls = fake_pools(monkeypatch, [FakeResponse(json.dumps(message).encode())])
    with pytest.raises(ContractError) as error:
        with net.safe_get('https://www.douyin.com/video/123', policy=net.TrustedDoHPolicy('cloudflare')):
            pass
    assert error.value.code == 'UNSAFE_SOURCE_URL'
    assert len(calls) == 1


def test_compressed_response_is_rejected_without_decompressing(monkeypatch):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    response = FakeResponse(b'compressed-bomb', headers={'Content-Encoding': 'gzip'})
    calls = fake_pools(monkeypatch, [response])
    with pytest.raises(ContractError):
        with net.safe_get('https://cdn.example/file') as wrapped:
            list(wrapped.iter_content())
    assert calls[0][4]['headers']['Accept-Encoding'] == 'identity'
    assert response.closed


@pytest.mark.parametrize('url,policy', [
    ('http://www.douyin.com/video/123', net.TrustedDoHPolicy('cloudflare')),
    ('https://www.douyin.com/video/123', type('Arbitrary', (), {'host': 'evil.example', 'ip': '1.1.1.2', 'path': '/'})()),
])
def test_opt_in_policy_cannot_allow_cleartext_or_arbitrary_resolvers(monkeypatch, url, policy):
    calls = fake_pools(monkeypatch, [FakeResponse(json.dumps(dns_message()).encode()), FakeResponse()])
    with pytest.raises(ContractError) as error:
        with net.safe_get(url, policy=policy):
            pass
    assert error.value.code == 'UNSAFE_SOURCE_URL'
    assert not calls


def test_private_profile_shortlink_redirects_use_guard_before_posts(monkeypatch):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    calls = fake_pools(monkeypatch, [FakeResponse(status=302, headers={'Location': 'https://www.douyin.com/user/test-user'}),
                                    FakeResponse(), FakeResponse(b'{"aweme_list": []}')])
    source = asyncio.run(DouyinConnector(PrivateConfig()).resolve_source('https://v.douyin.com/test/'))
    assert source.external_source_id == 'test-user'
    assert len(calls) == 3
    assert all('Cookie' not in call[4]['headers'] for call in calls[:2])


@pytest.mark.parametrize('response', [
    FakeResponse(b'x' * 65537), FakeResponse(b'not JSON'),
    FakeResponse(status=302, headers={'Location': 'https://other.example/resolve'}),
])
def test_resolver_body_and_redirect_fail_closed(monkeypatch, response):
    calls = fake_pools(monkeypatch, [response])
    with pytest.raises(ContractError):
        with net.safe_get('https://www.douyin.com/video/123', policy=net.TrustedDoHPolicy('cloudflare')):
            pass
    assert len(calls) == 1 and response.closed
    assert 'Cookie' not in calls[0][4]['headers']


def test_each_redirect_re_resolves_and_blocks_rebinding(monkeypatch):
    public = dns_message(host='public.example')
    private = dns_message(host='public.example', records=[{'name': 'public.example.', 'type': 1, 'TTL': 0, 'data': '198.18.0.61'}])
    calls = fake_pools(monkeypatch, [FakeResponse(json.dumps(public).encode()),
                                    FakeResponse(status=302, headers={'Location': '/next'}),
                                    FakeResponse(json.dumps(private).encode())])
    with pytest.raises(ContractError) as error:
        with net.safe_get('https://public.example/', policy=net.TrustedDoHPolicy('cloudflare')):
            pass
    assert error.value.code == 'UNSAFE_SOURCE_URL'
    assert [call[0] for call in calls] == ['1.1.1.1', '1.1.1.2', '1.1.1.1']


def test_http200_challenge_is_not_metadata_and_browser_is_disabled(monkeypatch):
    import kenradar.core.source_resolver as resolver
    async def forbidden(*a, **k): pytest.fail('browser fallback selected')
    monkeypatch.setattr(resolver, 'resolve_video_with_browser', forbidden)
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    calls = fake_pools(monkeypatch, [FakeResponse(b'<html>acrawler</html>'), FakeResponse(b'<html>acrawler</html>')])
    with pytest.raises(ContractError) as error:
        asyncio.run(DouyinConnector(PrivateConfig()).resolve_content('https://www.douyin.com/video/123'))
    assert error.value.code == 'SOURCE_UNAVAILABLE' and len(calls) == 2


def test_private_canonical_content_rejects_cleartext_before_api(monkeypatch):
    calls = fake_pools(monkeypatch, [FakeResponse(b'{"aweme_detail": {"aweme_id": "123"}}')])
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    with pytest.raises(ContractError) as error:
        asyncio.run(DouyinConnector(PrivateConfig()).resolve_content('http://www.douyin.com/video/123'))
    assert error.value.code == 'UNSAFE_SOURCE_URL' and not calls


@pytest.mark.parametrize('field', ['question_type', 'question_name', 'alias_name'])
def test_dns_response_question_and_names_use_strict_wire_shapes(field):
    message = dns_message()
    if field == 'question_type': message['Question'][0]['type'] = True
    if field == 'question_name': message['Question'][0]['name'] = 'www.douyin.com..'
    if field == 'alias_name': message['Answer'][0]['data'] = 'cdn.example..'
    with pytest.raises(ContractError):
        net.validate_dns_answers(message, 'www.douyin.com', 1)


def test_stream_deadline_updates_socket_even_when_connection_close_detaches_it(monkeypatch):
    from types import SimpleNamespace
    class Sock:
        def __init__(self): self.timeouts = []
        def gettimeout(self): return 0.5
        def settimeout(self, value): self.timeouts.append(value)
    sock = Sock()
    class ClosingResponse(FakeResponse):
        _connection = None
        _fp = SimpleNamespace(fp=SimpleNamespace(raw=SimpleNamespace(_sock=sock)))
        def read1(self, size, decode_content=True):
            body, self.body = self.body, b''
            return body
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    fake_pools(monkeypatch, [ClosingResponse()])
    with net.safe_get('https://cdn.example/file', timeout=0.5, total_timeout=2) as response:
        assert response.text == 'ok'
    assert sock.timeouts and all(0 < timeout <= 0.5 for timeout in sock.timeouts)


def test_alidns_authenticated_single_question_object_is_validated(monkeypatch):
    message = dns_message()
    message['Question'] = message['Question'][0]
    calls = fake_pools(monkeypatch, [FakeResponse(json.dumps(message).encode()), FakeResponse()])
    with net.safe_get('https://www.douyin.com/video/123', policy=net.TrustedDoHPolicy('alidns')) as response:
        assert response.text == 'ok'
    assert [call[0] for call in calls] == ['223.5.5.5', '1.1.1.2']
    message['Question']['name'] = 'wrong.example.'
    with pytest.raises(ContractError):
        net.validate_dns_answers(message, 'www.douyin.com', 1)


def test_http_rejection_reports_only_sanitized_status(monkeypatch):
    monkeypatch.setattr(net.socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('1.1.1.2', 443))])
    fake_pools(monkeypatch, [FakeResponse(status=403)])
    with pytest.raises(ContractError) as error:
        with net.safe_get('https://www.douyin.com/api?msToken=secret-test'):
            pass
    assert 'HTTP 403' in str(error.value)
    assert 'secret-test' not in str(error.value)


@pytest.mark.parametrize('policy', [None, net.TrustedDoHPolicy('cloudflare')])
def test_total_deadline_interrupts_stalled_http_headers(monkeypatch, policy):
    import threading
    from types import SimpleNamespace
    stopped = threading.Event()
    class Sock:
        def shutdown(self, how): stopped.set()
        def close(self): pass
    class HeaderStallPool:
        def __init__(self, *args, **kwargs): self.conn = SimpleNamespace(sock=Sock())
        def _get_conn(self, timeout=None): return self.conn
        def request(self, *args, **kwargs):
            self._get_conn()
            stopped.wait(0.5)
            return FakeResponse()
        def close(self): pass
    monkeypatch.setattr(net.urllib3, 'HTTPSConnectionPool', HeaderStallPool)
    url = 'https://www.douyin.com/video/123' if policy else 'https://1.1.1.2/'
    with pytest.raises(ContractError):
        with net.safe_get(url, policy=policy, total_timeout=0.02):
            pass
    assert stopped.is_set(), 'deadline must interrupt the verified socket, not only check after a stalled read'


def test_dns_address_records_require_textual_ip_syntax():
    message = dns_message()
    message['Answer'][1]['data'] = 16843009
    with pytest.raises(ContractError):
        net.validate_dns_answers(message, 'www.douyin.com', 1)


def test_trusted_resolver_policy_is_explicit_and_fixed():
    assert hasattr(net, 'TrustedDoHPolicy'), 'missing explicit trusted resolver policy'
    for name, host, ip in [('cloudflare', 'cloudflare-dns.com', '1.1.1.1'),
                           ('google', 'dns.google', '8.8.8.8'),
                           ('alidns', 'dns.alidns.com', '223.5.5.5')]:
        policy = net.TrustedDoHPolicy(name)
        assert (policy.host, policy.ip) == (host, ip)
    with pytest.raises(ValueError):
        net.TrustedDoHPolicy('https://arbitrary.example/resolve')


from test_hermes_v1 import db, request, seed_content


@pytest.mark.parametrize('fail_source', [False, True])
@pytest.mark.parametrize('outer_resolver', [None, 'google'])
def test_private_xiaoyuzhou_task_scopes_doh_through_to_thread_and_resets(db, monkeypatch, fail_source, outer_resolver):
    from pathlib import Path
    from kenradar.integrations.hermes_v1 import submit, execute, private_workflow
    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector
    external = '6ace3c3a195d838e2af15f95'
    url = 'https://www.xiaoyuzhoufm.com/episode/' + external
    seed_content(db, 'xiaoyuzhou', external)
    db.config.raw['integrations'] = {'hermes_v1': {
        'isolated_acceptance': True, 'trusted_doh_resolver': 'alidns'}}
    html = Path('tests/fixtures/xiaoyuzhou_episode.html').read_text(encoding='utf-8').replace('episode-1', external)
    responses = [FakeResponse(json.dumps(dns_message(host='www.xiaoyuzhoufm.com')).encode()),
                 FakeResponse(html.encode(), status=403 if fail_source else 200)]
    calls = fake_pools(monkeypatch, responses)
    def os_dns(*args, **kwargs): pytest.fail('task used OS DNS instead of scoped DoH')
    monkeypatch.setattr(net.socket, 'getaddrinfo', os_dns)
    original_dns = net.socket.getaddrinfo
    fetch = XiaoyuzhouConnector._fetch_text
    observed = []
    def observed_fetch(self, source):
        policy = net.current_policy()
        observed.append(policy.resolver if policy else None)
        assert policy and policy.resolver == 'alidns', 'private async orchestration did not propagate configured task policy'
        return fetch(self, source)
    monkeypatch.setattr(XiaoyuzhouConnector, '_fetch_text', observed_fetch)
    submit(db, request(url))
    run = db.claim_next_task_run('worker')
    class OuterConfig:
        def get(self, key, default=None):
            return {'integrations.hermes_v1.trusted_doh_resolver': outer_resolver,
                    'integrations.hermes_v1.isolated_acceptance': True,
                    'app.data_dir': str(db.config.data_dir)}.get(key, default)
    async def exercise():
        before = net.current_policy()
        entered, release = asyncio.Event(), asyncio.Event()
        async def sibling():
            entered.set()
            await release.wait()
            assert net.current_policy() is before, 'task policy leaked to sibling async task'
        spectator = asyncio.create_task(sibling())
        await entered.wait()
        try:
            with db.lease_scope(run):
                if fail_source:
                    with pytest.raises(ContractError, match='SOURCE_UNAVAILABLE'):
                        await execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']})
                else:
                    result = await execute(private_workflow(db.config, db), {**run['payload_json'], 'task_id': run['id']})
                    assert result['hermes']['delivery_status'] == 'complete'
            assert net.current_policy() is before, 'policy was not restored after orchestration'
        finally:
            release.set()
            await spectator
    with net.configured_network(OuterConfig()):
        asyncio.run(exercise())
    assert net.current_policy() is None
    assert net.socket.getaddrinfo is original_dns, 'orchestration changed global DNS'
    assert observed == ['alidns']
    assert [call[0] for call in calls] == ['223.5.5.5', '1.1.1.2']
