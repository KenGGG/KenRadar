"""Optional app-local HTTPS connection route; retain URL, SNI and TLS checks."""
from ipaddress import ip_address
from urllib.parse import urlsplit
import requests


class HttpsAddressAdapter(requests.adapters.HTTPAdapter):
    def __init__(self, hostname, address):
        self.hostname = hostname
        self.address = str(ip_address(address))
        super().__init__()

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        if urlsplit(request.url).hostname != self.hostname or requests.utils.select_proxy(request.url, proxies or {}):
            return super().get_connection_with_tls_context(request, verify, proxies, cert)
        host, options = self.build_connection_pool_key_attributes(request, verify, cert)
        request.headers['Host'] = urlsplit(request.url).netloc
        host['host'] = self.address
        options.update(server_hostname=self.hostname, assert_hostname=self.hostname)
        return self.poolmanager.connection_from_host(**host, pool_kwargs=options)


def post_with_address(url, address, **kwargs):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('AI connect_address requires an HTTPS endpoint')
    with requests.Session() as session:
        session.mount('https://'+parsed.netloc+'/', HttpsAddressAdapter(parsed.hostname, address))
        return session.post(url, **kwargs)
