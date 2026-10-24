"""Transport-boundary regressions: preserve routing and fail closed on TLS trust errors."""
from types import SimpleNamespace
import ssl
import pytest
import requests
from urllib3.exceptions import MaxRetryError, SSLError as UrllibSSLError
from kenradar.core.organizer import ContentOrganizer


def organizer(monkeypatch):
    obj = object.__new__(ContentOrganizer)
    values = {'ai.organizer.connect_hostname': 'apihub.agnes-ai.com',
              'ai.organizer.connect_address': '104.18.19.62'}
    obj.config = SimpleNamespace(get=lambda key, default=None: values.get(key, default))
    obj._wait_for_rate_limit = lambda *args: None
    monkeypatch.setattr('kenradar.core.organizer.time.sleep', lambda _: None)
    return obj


def test_certificate_failure_is_not_retried(monkeypatch):
    obj = organizer(monkeypatch)
    calls = []
    error = requests.exceptions.SSLError(UrllibSSLError(ssl.SSLCertVerificationError(
        1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed')))
    def send(*args, **kwargs):
        calls.append(kwargs)
        raise error
    monkeypatch.setattr('kenradar.core.http_routing.post_with_address', send)
    with pytest.raises(requests.exceptions.SSLError) as caught:
        obj._post_with_retry('https://apihub.agnes-ai.com/v1/chat/completions', attempts=3, verify=True)
    assert caught.value is error
    assert len(calls) == 1


def eof_error():
    return requests.exceptions.SSLError(MaxRetryError(
        None, '/v1/chat/completions', UrllibSSLError(ssl.SSLEOFError(
            8, '[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol'))))


@pytest.mark.parametrize('recover', [True, False])
def test_wrapped_eof_preserves_route_verification_and_attempt_bound(monkeypatch, recover):
    obj = organizer(monkeypatch)
    calls = []
    waits = []
    rates = []
    obj._wait_for_rate_limit = lambda *args: rates.append(args)
    monkeypatch.setattr('kenradar.core.organizer.time.sleep', waits.append)
    error = eof_error()
    response = requests.Response()
    response.status_code = 200
    def send(url, address, **kwargs):
        calls.append((url, address, kwargs))
        if recover and len(calls) == 2:
            return response
        raise error
    monkeypatch.setattr('kenradar.core.http_routing.post_with_address', send)
    url = 'https://apihub.agnes-ai.com/v1/chat/completions'
    kwargs = dict(attempts=3, retry_delay=2, rpm_limit=19, rate_limit_key='fixture', verify=True)
    if recover:
        assert obj._post_with_retry(url, **kwargs) is response
    else:
        with pytest.raises(requests.exceptions.SSLError) as caught:
            obj._post_with_retry(url, **kwargs)
        assert caught.value is error
    assert len(calls) == (2 if recover else 3)
    assert waits == ([2] if recover else [2, 4])
    assert rates == [(19, 'fixture')] * len(calls)
    assert all(call == (url, '104.18.19.62', {'verify': True}) for call in calls)


@pytest.mark.parametrize('message', [
    'certificate verify failed', 'hostname mismatch', 'TLSV1_ALERT_UNKNOWN_CA',
    'WRONG_VERSION_NUMBER', 'UNEXPECTED_EOF certificate verify failed',
])
def test_nontransient_tls_is_not_retryable(message):
    assert not ContentOrganizer._is_retryable_request_error(requests.exceptions.SSLError(message))


@pytest.mark.parametrize('status,retryable', [(401, False), (403, False), (429, True), (503, True)])
def test_http_auth_and_existing_transient_status_policy(status, retryable):
    response = requests.Response()
    response.status_code = status
    assert ContentOrganizer._is_retryable_request_error(
        requests.exceptions.HTTPError(response=response)) is retryable
