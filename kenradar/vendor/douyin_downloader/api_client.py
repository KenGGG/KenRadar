from __future__ import annotations

import asyncio
import random
import string
import time
import urllib.request
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlencode

import yaml

from kenradar.vendor.douyin_downloader.xbogus import XBogus

try:
    from kenradar.vendor.douyin_downloader.abogus import ABogus, BrowserFingerprintGenerator
except Exception:  # pragma: no cover - optional dependency
    ABogus = None
    BrowserFingerprintGenerator = None


INVALID_COOKIE_NAME_CHARS = set('()<>@,;:\\"/[]?={} \t\r\n')


USER_AGENT_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


def _is_valid_cookie_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in name):
        return False
    return not any(ch in INVALID_COOKIE_NAME_CHARS for ch in name)


def _sanitize_cookies(cookies: dict[Any, Any]) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for raw_key, raw_value in (cookies or {}).items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key.strip()
        if not _is_valid_cookie_name(key):
            continue
        sanitized[key] = "" if raw_value is None else str(raw_value).strip()
    return sanitized


class MsTokenManager:
    """Generate a Douyin msToken, following the upstream downloader's fallback strategy."""

    F2_CONF_URL = "https://raw.githubusercontent.com/Johnserf-Seed/f2/main/f2/conf/conf.yaml"

    def __init__(self, user_agent: str, timeout_seconds: int = 15):
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    def ensure_ms_token(self, cookies: dict[str, str]) -> str:
        current = str((cookies or {}).get("msToken") or "").strip()
        if current:
            return current
        real = self._gen_real_ms_token()
        if real:
            return real
        return self._gen_fallback_ms_token()

    def _gen_real_ms_token(self) -> str:
        try:
            with urllib.request.urlopen(self.F2_CONF_URL, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            data = yaml.safe_load(raw) or {}
            conf = data.get("f2", {}).get("douyin", {}).get("msToken", {})
            required = {"url", "magic", "version", "dataType", "ulr", "strData"}
            if not isinstance(conf, dict) or not required.issubset(conf):
                return ""
            payload = {
                "magic": conf["magic"],
                "version": conf["version"],
                "dataType": conf["dataType"],
                "strData": conf["strData"],
                "ulr": conf["ulr"],
                "tspFromClient": int(time.time() * 1000),
            }
            request = urllib.request.Request(
                conf["url"],
                data=__import__("json").dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": self.user_agent,
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                token = self._extract_ms_token_from_headers(response.headers)
            return token if len(token) in (164, 184) else ""
        except Exception:
            return ""

    @staticmethod
    def _extract_ms_token_from_headers(headers: Any) -> str:
        set_cookies = headers.get_all("Set-Cookie") if hasattr(headers, "get_all") else []
        for header in set_cookies or []:
            cookie = SimpleCookie()
            cookie.load(header)
            morsel = cookie.get("msToken")
            if morsel and morsel.value:
                return morsel.value.strip()
        return ""

    @staticmethod
    def _gen_fallback_ms_token() -> str:
        return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(182)) + "=="


class DouyinAPIClient:
    """从 douyin-downloader 本地化的最小 API 客户端。

    只保留 KenRadar MVP 需要的用户作品列表、作品详情和下载 URL 构造能力。
    """

    BASE_URL = "https://www.douyin.com"

    def __init__(self, cookies: dict[str, str], proxy: str | None = None):
        self.cookies = _sanitize_cookies(cookies or {})
        self.proxy = str(proxy or "").strip()
        self._session: Any | None = None
        selected_ua = random.choice(USER_AGENT_POOL)
        self.headers = {
            "User-Agent": selected_ua,
            "Referer": "https://www.douyin.com/",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
        }
        self._signer = XBogus(self.headers["User-Agent"])
        self._ms_token_manager = MsTokenManager(self.headers["User-Agent"])
        self._ms_token = str(self.cookies.get("msToken") or "").strip()
        self._abogus_enabled = ABogus is not None and BrowserFingerprintGenerator is not None

    async def __aenter__(self) -> "DouyinAPIClient":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _ensure_session(self) -> None:
        import aiohttp

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers=self.headers,
                cookies=self.cookies,
                timeout=aiohttp.ClientTimeout(total=30),
                raise_for_status=False,
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_session(self) -> Any:
        await self._ensure_session()
        if self._session is None:
            raise RuntimeError("无法创建 aiohttp session")
        return self._session

    async def _ensure_ms_token(self) -> str:
        if self._ms_token:
            return self._ms_token
        token = await asyncio.to_thread(self._ms_token_manager.ensure_ms_token, self.cookies)
        self._ms_token = token.strip()
        if self._ms_token:
            self.cookies["msToken"] = self._ms_token
            if self._session and not self._session.closed:
                self._session.cookie_jar.update_cookies({"msToken": self._ms_token})
        return self._ms_token

    async def _default_query(self) -> dict[str, Any]:
        ms_token = await self._ensure_ms_token()
        return {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "update_version_code": "170400",
            "pc_client_type": "1",
            "version_code": "290100",
            "version_name": "29.1.0",
            "cookie_enabled": "true",
            "screen_width": "1920",
            "screen_height": "1080",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "130.0.0.0",
            "browser_online": "true",
            "engine_name": "Blink",
            "engine_version": "130.0.0.0",
            "os_name": "Windows",
            "os_version": "10",
            "cpu_core_num": "12",
            "device_memory": "8",
            "platform": "PC",
            "downlink": "10",
            "effective_type": "4g",
            "round_trip_time": "100",
            "msToken": ms_token,
        }

    def sign_url(self, url: str) -> tuple[str, str]:
        signed_url, _xbogus, user_agent = self._signer.build(url)
        return signed_url, user_agent

    def build_signed_path(self, path: str, params: dict[str, Any]) -> tuple[str, str]:
        query = urlencode(params)
        base_url = f"{self.BASE_URL}{path}"
        ab_signed = self._build_abogus_url(base_url, query)
        if ab_signed:
            return ab_signed
        return self.sign_url(f"{base_url}?{query}")

    def _build_abogus_url(self, base_url: str, query: str) -> tuple[str, str] | None:
        if not self._abogus_enabled:
            return None
        try:
            browser_fp = BrowserFingerprintGenerator.generate_fingerprint("Edge")
            signer = ABogus(fp=browser_fp, user_agent=self.headers["User-Agent"])
            params_with_ab, _abogus, user_agent, _body = signer.generate_abogus(query, "")
            return f"{base_url}?{params_with_ab}", user_agent
        except Exception:
            return None

    async def _request_json(self, path: str, params: dict[str, Any], *, max_retries: int = 3) -> dict[str, Any]:
        await self._ensure_session()
        if self._session is None:
            return {}

        delays = [1, 2, 5]
        for attempt in range(max_retries):
            url, user_agent = self.build_signed_path(path, params)
            try:
                async with self._session.get(
                    url,
                    headers={**self.headers, "User-Agent": user_agent},
                    proxy=self.proxy or None,
                ) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        return data if isinstance(data, dict) else {}
                    if response.status < 500 and response.status != 429:
                        return {}
            except Exception:
                pass

            if attempt < max_retries - 1:
                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
        return {}

    async def resolve_short_url(self, short_url: str, *, timeout_seconds: float = 10.0) -> str:
        await self._ensure_session()
        if self._session is None:
            return ""
        try:
            import aiohttp

            async with self._session.get(
                short_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
                proxy=self.proxy or None,
            ) as response:
                if response.status >= 400:
                    return ""
                return str(response.url)
        except Exception:
            return ""

    @staticmethod
    def _normalize_paged_response(raw_data: Any, item_keys: list[str] | None = None) -> dict[str, Any]:
        raw = raw_data if isinstance(raw_data, dict) else {}
        keys = ["items", *(item_keys or []), "aweme_list", "mix_list", "music_list"]
        items: list[Any] = []
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                items = value
                break
        has_more_value = raw.get("has_more", 0)
        try:
            has_more = bool(int(has_more_value))
        except (TypeError, ValueError):
            has_more = bool(has_more_value)

        cursor_value = raw.get("max_cursor")
        if cursor_value is None:
            cursor_value = raw.get("cursor", 0)
        try:
            max_cursor = int(cursor_value or 0)
        except (TypeError, ValueError):
            max_cursor = 0

        try:
            status_code = int(raw.get("status_code", 0) or 0)
        except (TypeError, ValueError):
            status_code = 0

        normalized = {
            "items": items,
            "aweme_list": items,
            "has_more": has_more,
            "max_cursor": max_cursor,
            "min_cursor": raw.get("min_cursor", 0),
            "status_code": status_code,
            "raw": raw,
        }
        for key, value in raw.items():
            if key not in normalized:
                normalized[key] = value
        return normalized

    async def _build_user_page_params(self, sec_uid: str, max_cursor: int, count: int) -> dict[str, Any]:
        params = await self._default_query()
        params.update({"sec_user_id": sec_uid, "max_cursor": max_cursor, "count": count, "locate_query": "false"})
        return params

    async def get_user_post(self, sec_uid: str, max_cursor: int = 0, count: int = 20) -> dict[str, Any]:
        params = await self._build_user_page_params(sec_uid, max_cursor, count)
        params.update(
            {
                "show_live_replay_strategy": "1",
                "need_time_list": "1",
                "time_list_query": "0",
                "whale_cut_token": "",
                "cut_version": "1",
                "publish_video_strategy_type": "2",
            }
        )
        raw = await self._request_json("/aweme/v1/web/aweme/post/", params)
        return self._normalize_paged_response(raw, item_keys=["aweme_list"])

    async def get_video_detail(self, aweme_id: str) -> dict[str, Any] | None:
        for aid in ("6383", "1128"):
            params = await self._default_query()
            params.update({"aweme_id": aweme_id, "aid": aid})
            data = await self._request_json("/aweme/v1/web/aweme/detail/", params)
            if not data:
                continue
            detail = data.get("aweme_detail") if isinstance(data, dict) else None
            if isinstance(detail, dict):
                return detail
            filter_info = data.get("filter_detail") if isinstance(data, dict) else None
            if isinstance(filter_info, dict) and filter_info.get("filter_reason"):
                continue
            break
        return None
