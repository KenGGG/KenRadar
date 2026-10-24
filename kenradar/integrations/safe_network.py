"""Pinned public-IP HTTP for untrusted source/media URLs; proxies are not used."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
import threading
from urllib.parse import urlsplit, urljoin, urlencode

import certifi
import urllib3

from .hermes_v1 import ContractError


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ContractError('SOURCE_UNAVAILABLE', 'Network total deadline exceeded')
    return remaining


def _start_deadline(pool, deadline):
    """Interrupt trickled headers/reads; socket timeouts alone are idle limits."""
    connections, responses = [], []
    expired = threading.Event()
    get_conn = getattr(pool, '_get_conn', None)
    if get_conn is not None:
        def tracked_get_conn(*args, **kwargs):
            _remaining(deadline)
            connection = get_conn(*args, **kwargs)
            connections.append(connection)
            return connection
        pool._get_conn = tracked_get_conn

    def interrupt():
        expired.set()
        sockets = [getattr(connection, 'sock', None) for connection in connections]
        for response in responses:
            fp = getattr(getattr(response, '_fp', None), 'fp', None)
            sockets.append(getattr(getattr(fp, 'raw', None), '_sock', None))
        for sock in sockets:
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass
    timer = threading.Timer(_remaining(deadline), interrupt)
    timer.expired = expired
    timer.daemon = True
    timer.start()
    return timer, responses


def _bounded_chunks(response, chunk_size, max_bytes, deadline):
    if response.headers.get('Content-Encoding', 'identity').lower() not in ('', 'identity'):
        raise ContractError('SOURCE_UNAVAILABLE', 'Compressed network response rejected')
    size = 0
    iterator = iter(response.stream(chunk_size, decode_content=True)) if not hasattr(response, 'read1') else None
    while True:
        remaining = _remaining(deadline)
        connection = getattr(response, '_connection', None)
        sock = getattr(connection, 'sock', None)
        if sock is None:
            # urllib3 detaches the connection on Connection: close, while the
            # HTTPResponse file still owns the same verified TLS socket.
            fp = getattr(getattr(response, '_fp', None), 'fp', None)
            sock = getattr(getattr(fp, 'raw', None), '_sock', None)
        if sock is not None:
            original_timeout = sock.gettimeout()
            sock.settimeout(min(remaining, original_timeout) if original_timeout is not None else remaining)
        try:
            chunk = response.read1(chunk_size, decode_content=True) if iterator is None else next(iterator, b'')
        except (urllib3.exceptions.HTTPError, OSError):
            raise ContractError('SOURCE_UNAVAILABLE', 'Bounded network read failed') from None
        _remaining(deadline)
        if not chunk:
            return
        size += len(chunk)
        if size > max_bytes:
            raise ContractError('SOURCE_UNAVAILABLE', 'Decoded response exceeds byte limit')
        yield chunk

_policy = ContextVar('kenradar_trusted_doh', default=None)


def current_policy():
    return _policy.get()


def policy_from_config(config):
    name = config.get('integrations.hermes_v1.trusted_doh_resolver', '') if config is not None else ''
    if not name:
        return current_policy()
    root = Path(__file__).resolve().parents[2] / 'data/test-migration/hermes-v1'
    data = Path(config.get('app.data_dir', 'data')).resolve()
    if config.get('integrations.hermes_v1.isolated_acceptance', False) is not True or not data.is_relative_to(root.resolve()):
        raise ContractError('UNSAFE_SOURCE_URL', 'Trusted DoH is restricted to isolated acceptance')
    try:
        return TrustedDoHPolicy(name)
    except (ValueError, TypeError):
        raise ContractError('UNSAFE_SOURCE_URL', 'Unknown trusted resolver policy') from None


@contextmanager
def configured_network(config):
    """Scope explicit acceptance resolution to this task, including asyncio.to_thread."""
    token = _policy.set(policy_from_config(config))
    try:
        yield
    finally:
        _policy.reset(token)


@dataclass(frozen=True)
class TrustedDoHPolicy:
    """Explicit authenticated resolver selection, never an arbitrary IP override."""
    resolver: str

    def __post_init__(self):
        if self.resolver not in self._resolvers:
            raise ValueError('Unknown trusted DoH resolver')

    _resolvers = {
        'cloudflare': ('cloudflare-dns.com', '1.1.1.1', '/dns-query'),
        'google': ('dns.google', '8.8.8.8', '/resolve'),
        'alidns': ('dns.alidns.com', '223.5.5.5', '/resolve'),
    }

    @property
    def host(self):
        return self._resolvers[self.resolver][0]

    @property
    def ip(self):
        return self._resolvers[self.resolver][1]

    @property
    def path(self):
        return self._resolvers[self.resolver][2]


def _dns_name(value):
    if not isinstance(value, str):
        raise ValueError()
    name = value.removesuffix('.').lower()
    if (len(name) > 253 or not name or any(
            not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in name.split('.'))):
        raise ValueError()
    return name


def _public_ip(value):
    if not isinstance(value, str):
        raise ValueError()
    ip = ipaddress.ip_address(value)
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise ValueError()
    if getattr(ip, 'ipv4_mapped', None) is not None:
        _public_ip(str(ip.ipv4_mapped))
    return str(ip)


def validate_dns_answers(message, host, qtype):
    """Accept only a bounded connected CNAME chain and exclusively global A/AAAA."""
    try:
        name = _dns_name(host)
        if not isinstance(message, dict):
            raise ValueError()
        questions = message.get('Question')
        if isinstance(questions, dict):
            questions = [questions]  # AliDNS uses a single Question object.
        if (type(message.get('Status')) is not int or message['Status'] != 0
                or message.get('TC', False) is not False
                or not isinstance(questions, list) or len(questions) != 1
                or questions != [{'name': questions[0]['name'], 'type': qtype}]
                or type(questions[0]['type']) is not int
                or _dns_name(questions[0]['name']) != name):
            raise ValueError()
        records = message.get('Answer', [])
        if not isinstance(records, list) or len(records) > 64:
            raise ValueError()
        aliases, addresses = {}, {}
        for record in records:
            owner = _dns_name(record['name'])
            ttl, kind = record['TTL'], record['type']
            if type(ttl) is not int or not 0 <= ttl <= 2147483647 or type(kind) is not int:
                raise ValueError()
            if kind == 5:
                target = _dns_name(record['data'])
                if owner in aliases or owner in addresses:
                    raise ValueError()
                aliases[owner] = target
            elif kind == qtype and qtype in (1, 28):
                ip = _public_ip(record['data'])
                if ipaddress.ip_address(ip).version != (4 if qtype == 1 else 6) or owner in aliases:
                    raise ValueError()
                addresses.setdefault(owner, []).append(ip)
            else:
                raise ValueError()
        visited = set()
        while name in aliases:
            if name in visited or len(visited) >= 8:
                raise ValueError()
            visited.add(name)
            name = aliases[name]
        if name in visited or set(aliases) - visited or set(addresses) - {name} or not addresses.get(name):
            raise ValueError()
        return list(dict.fromkeys(addresses.get(name, [])))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ContractError('UNSAFE_SOURCE_URL', 'Invalid trusted DNS response') from None


class Response:
    def __init__(self, response, url, max_bytes, deadline):
        self.response, self.url = response, url
        self.max_bytes, self.deadline = max_bytes, deadline

    def raise_for_status(self):
        if not 200 <= self.response.status < 300:
            raise ContractError('SOURCE_UNAVAILABLE', f'Source HTTP request was rejected (HTTP {self.response.status})')

    def iter_content(self, chunk_size=262144):
        yield from _bounded_chunks(self.response, min(chunk_size, 65536), self.max_bytes, self.deadline)

    @property
    def text(self):
        chunks, size = [], 0
        for chunk in self.iter_content():
            size += len(chunk)
            if size > 4 * 1024 * 1024:
                raise ContractError('SOURCE_UNAVAILABLE', 'Source page exceeds limit')
            chunks.append(chunk)
        return b''.join(chunks).decode('utf-8', errors='replace')


def _doh_addresses(host, policy, timeout):
    deadline = time.monotonic() + min(timeout, 8)
    pool = urllib3.HTTPSConnectionPool(
        policy.ip, 443, timeout=urllib3.Timeout(connect=min(timeout, 8), read=min(timeout, 8)),
        server_hostname=policy.host, assert_hostname=policy.host,
        cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
    response = None
    timer, tracked_responses = _start_deadline(pool, deadline)
    try:
        response = pool.request('GET', policy.path + '?' + urlencode({'name': _dns_name(host), 'type': 'A'}),
                                headers={'Host': policy.host, 'Accept': 'application/dns-json', 'Accept-Encoding': 'identity'},
                                redirect=False, retries=False, preload_content=False)
        tracked_responses.append(response)
        if timer.expired.is_set():
            raise ContractError('SOURCE_UNAVAILABLE', 'Network total deadline exceeded')
        _remaining(deadline)
        if response.status != 200:
            raise ContractError('SOURCE_UNAVAILABLE', 'Trusted resolver rejected request')
        chunks, size = [], 0
        for chunk in _bounded_chunks(response, 4096, 65536, deadline):
            size += len(chunk)
            if size > 65536:
                raise ContractError('SOURCE_UNAVAILABLE', 'Trusted DNS body exceeds limit')
            chunks.append(chunk)
        return validate_dns_answers(json.loads(b''.join(chunks)), host, 1)
    except ContractError:
        raise
    except (urllib3.exceptions.HTTPError, OSError, ValueError):
        raise ContractError('SOURCE_UNAVAILABLE', 'Trusted DNS transport failed') from None
    finally:
        timer.cancel()
        if response is not None:
            response.close()
            response.release_conn()
        pool.close()


@contextmanager
def safe_get(url, *, timeout=30, headers=None, source=False, stream=True, policy=None,
             max_bytes=256 * 1024 * 1024, total_timeout=120, credential_host=None):
    """Validate every redirect and pin the selected DNS address with TLS hostname verification."""
    policy = policy if policy is not None else current_policy()
    if policy is not None and (type(policy) is not TrustedDoHPolicy or urlsplit(url).scheme != 'https'):
        raise ContractError('UNSAFE_SOURCE_URL', 'Trusted resolver requires fixed policy and HTTPS')
    deadline = time.monotonic() + total_timeout
    for hop in range(6):
        try:
            parsed = urlsplit(url)
            host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)
            if (parsed.scheme not in ('https', 'http') or not host or parsed.username or parsed.password
                    or port not in (80, 443) or any(c.isspace() for c in url)):
                raise ValueError()
            if credential_host is not None and (parsed.scheme != 'https' or port != 443 or host != credential_host):
                raise ValueError()
            try:
                literal = ipaddress.ip_address(host)
            except ValueError:
                literal = None
            if literal is not None and not literal.is_global:
                raise ValueError()
            if literal is not None:
                addresses = [_public_ip(host)]
            elif policy is not None:
                addresses = _doh_addresses(host, policy, min(timeout, _remaining(deadline)))
            else:
                addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
            if not addresses:
                raise ValueError()
            addresses = [_public_ip(ip) for ip in addresses]
        except ContractError:
            raise
        except (ValueError, OSError):
            raise ContractError('UNSAFE_SOURCE_URL', 'Source or redirect is not a public HTTP target') from None
        if source:
            if callable(source):
                source(url)
            else:
                from .hermes_v1 import source_platform
                source_platform(url)
        remaining = min(timeout, _remaining(deadline))
        kwargs = {'timeout': urllib3.Timeout(connect=remaining, read=remaining, total=remaining)}
        if parsed.scheme == 'https':
            kwargs.update(server_hostname=host, assert_hostname=host, cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
            pool = urllib3.HTTPSConnectionPool(addresses[0], port, **kwargs)
        else:
            pool = urllib3.HTTPConnectionPool(addresses[0], port, **kwargs)
        response = None
        timer, tracked_responses = _start_deadline(pool, deadline)
        try:
            request_headers = {'User-Agent': 'KenRadar/0.1', 'Host': parsed.netloc, 'Accept-Encoding': 'identity'}
            for key, value in (headers or {}).items():
                if key.lower() in ('user-agent', 'accept', 'referer', 'origin') or (
                        credential_host is not None and key.lower() in ('cookie', 'authorization')):
                    if not isinstance(value, str) or '\r' in value or '\n' in value:
                        raise ContractError('UNSAFE_SOURCE_URL', 'Invalid request header')
                    request_headers[key] = value
            target = parsed.path or '/'
            if parsed.query:
                target += '?' + parsed.query
            response = pool.request('GET', target, headers=request_headers, redirect=False, retries=False, preload_content=False)
            tracked_responses.append(response)
            if timer.expired.is_set():
                raise ContractError('SOURCE_UNAVAILABLE', 'Network total deadline exceeded')
            _remaining(deadline)
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get('Location')
                if not location:
                    raise ContractError('SOURCE_UNAVAILABLE', 'Redirect has no location')
                next_url = urljoin(url, location)
                if parsed.scheme == 'https' and urlsplit(next_url).scheme != 'https':
                    raise ContractError('UNSAFE_SOURCE_URL', 'TLS downgrade rejected')
                next_parsed = urlsplit(next_url)
                if credential_host is not None and (next_parsed.hostname != credential_host or (next_parsed.port or 443) != 443):
                    raise ContractError('UNSAFE_SOURCE_URL', 'Credentialed cross-origin redirect rejected')
                url = next_url
                continue
            wrapped = Response(response, url, max_bytes, deadline)
            wrapped.raise_for_status()
            yield wrapped
            return
        except ContractError:
            raise
        except (urllib3.exceptions.HTTPError, OSError):
            raise ContractError('SOURCE_UNAVAILABLE', 'Verified source transport failed') from None
        finally:
            timer.cancel()
            if response:
                response.close()
                response.release_conn()
            pool.close()
    raise ContractError('UNSAFE_SOURCE_URL', 'Redirect limit exceeded')
