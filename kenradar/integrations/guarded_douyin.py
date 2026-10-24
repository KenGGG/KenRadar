"""Private Douyin adapter: reuse vendor signing/mapping, never vendor egress.

Remote token configuration/bootstrap is deliberately disabled: supplied msToken or
vendor local fallback only. Browser egress cannot enforce this boundary and is
never invoked. The ordinary production vendor client is unchanged.
"""
import asyncio
import json
from http.cookies import SimpleCookie

from kenradar.vendor.douyin_downloader.api_client import DouyinAPIClient, MsTokenManager
from .hermes_v1 import ContractError
from .safe_network import safe_get, policy_from_config


def validate_profile_url(url):
    import re
    from urllib.parse import urlsplit
    from .hermes_v1 import source_platform
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.hostname not in ('www.douyin.com', 'douyin.com', 'v.douyin.com')
                or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment
                or any(c.isspace() for c in url)):
            raise ValueError()
    except ValueError:
        raise ContractError('UNSAFE_SOURCE_URL', 'Unsafe Douyin source URL') from None
    if not re.fullmatch(r'/user/[A-Za-z0-9_-]+/?', parsed.path):
        source_platform(url)


class GuardedDouyinAPIClient(DouyinAPIClient):
    def __init__(self, config):
        super().__init__(config.cookies if config is not None else {})
        self.policy = policy_from_config(config)

    async def _ensure_session(self):
        # No aiohttp session (including its automatic redirects/cookie jar).
        return None

    async def get_session(self):
        raise ContractError('UNSAFE_SOURCE_URL', 'Unguarded session unavailable in private adapter')

    async def _ensure_ms_token(self):
        if not self._ms_token:
            self._ms_token = MsTokenManager._gen_fallback_ms_token()
        return self._ms_token

    async def _request_json(self, path, params, *, max_retries=3):
        delays = (1, 2, 5)
        for attempt in range(min(max_retries, 3)):
            url, user_agent = self.build_signed_path(path, params)
            cookie = SimpleCookie()
            for key, value in self.cookies.items():
                cookie[key] = value
            headers = {**self.headers, 'User-Agent': user_agent,
                       'Cookie': '; '.join(m.OutputString() for m in cookie.values())}
            def fetch():
                with safe_get(url, headers=headers, policy=self.policy,
                              credential_host='www.douyin.com', max_bytes=4 * 1024 * 1024,
                              total_timeout=30) as response:
                    try:
                        data = json.loads(response.text)
                    except ValueError:
                        return {}  # HTTP 200 HTML/challenge is not metadata.
                    return data if isinstance(data, dict) else {}
            try:
                return await asyncio.to_thread(fetch)
            except ContractError as exc:
                if exc.code != 'SOURCE_UNAVAILABLE' or attempt == min(max_retries, 3) - 1:
                    raise
                await asyncio.sleep(delays[attempt])
        return {}
