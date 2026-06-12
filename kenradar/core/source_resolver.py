from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from kenradar.core.config import AppConfig
from kenradar.vendor.douyin_downloader.api_client import DouyinAPIClient
from kenradar.vendor.douyin_downloader.browser_resolver import resolve_video_with_browser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedDouyinSource:
    url: str
    sec_uid: str
    name: str
    avatar_url: str = ""


@dataclass(frozen=True)
class ResolvedDouyinVideo:
    aweme_id: str
    url: str
    sec_uid: str
    name: str
    aweme: dict[str, Any]


def resolve_douyin_source(config: AppConfig, url: str, *, name: str = "", sec_uid: str = "") -> ResolvedDouyinSource:
    raw_url = str(url or "").strip()
    raw_name = str(name or "").strip()
    raw_sec_uid = str(sec_uid or "").strip()
    if not raw_url and raw_sec_uid:
        raw_url = f"https://www.douyin.com/user/{raw_sec_uid}"
    if not raw_url:
        raise ValueError("请填写抖音主页地址")

    normalized_url = _normalize_douyin_url(raw_url)
    resolved_url = _resolve_redirect_url(normalized_url, config.cookies) or normalized_url
    resolved_sec_uid = raw_sec_uid or extract_sec_uid(resolved_url)
    if not resolved_sec_uid:
        html = _fetch_page_html(resolved_url, config.cookies)
        resolved_sec_uid = extract_sec_uid(html)
    if not resolved_sec_uid:
        raise ValueError("无法从抖音主页提取 sec_uid，请确认链接形如 https://www.douyin.com/user/...")

    profile = asyncio.run(_fetch_profile_from_posts(config, resolved_sec_uid))
    nickname = raw_name or str(profile.get("nickname") or "").strip() or resolved_sec_uid
    avatar_url = str(profile.get("avatar_url") or "").strip()
    canonical_url = f"https://www.douyin.com/user/{resolved_sec_uid}"
    return ResolvedDouyinSource(url=canonical_url, sec_uid=resolved_sec_uid, name=nickname, avatar_url=avatar_url)


async def resolve_douyin_video(config: AppConfig, value: str = "", *, aweme_id: str = "") -> ResolvedDouyinVideo:
    raw_value = str(value or "").strip()
    resolved_aweme_id = str(aweme_id or "").strip() or extract_aweme_id(raw_value)
    resolved_url = ""
    if raw_value and not resolved_aweme_id:
        normalized_url = _normalize_douyin_url(_extract_first_url(raw_value) or raw_value)
        resolved_url = await asyncio.to_thread(_resolve_redirect_url, normalized_url, config.cookies) or normalized_url
        resolved_aweme_id = extract_aweme_id(resolved_url)
        if not resolved_aweme_id:
            html = await asyncio.to_thread(_fetch_page_html, resolved_url, config.cookies)
            resolved_aweme_id = extract_aweme_id(html)
    if not resolved_aweme_id:
        raise ValueError("无法从抖音视频链接提取 aweme_id，请确认链接形如 https://www.douyin.com/video/...")

    async with DouyinAPIClient(config.cookies) as api_client:
        detail = await api_client.get_video_detail(resolved_aweme_id)
    browser_fallback_enabled = bool(config.get("download.browser_fallback.enabled", False))
    if not isinstance(detail, dict) or not detail:
        if not browser_fallback_enabled:
            logger.warning(
                "抖音详情 API 未返回有效数据，已按配置禁止浏览器兜底: aweme_id=%s",
                resolved_aweme_id,
            )
        else:
            detail = await resolve_video_with_browser(config, resolved_url or raw_value, resolved_aweme_id)
    if not isinstance(detail, dict) or not detail:
        raise ValueError(f"无法读取抖音视频详情: {resolved_aweme_id}")

    if _is_gallery_aweme(detail):
        raise ValueError(f"当前仅支持视频作品，暂不处理图文作品: {resolved_aweme_id}")

    author = detail.get("author") if isinstance(detail.get("author"), dict) else {}
    author_user = detail.get("author_user_info") if isinstance(detail.get("author_user_info"), dict) else {}
    sec_uid = str(author.get("sec_uid") or author_user.get("sec_uid") or detail.get("sec_uid") or "").strip()
    name = str(
        author.get("nickname")
        or author_user.get("nickname")
        or detail.get("nickname")
        or detail.get("author_name")
        or sec_uid
        or "单视频来源"
    ).strip()
    canonical_url = f"https://www.douyin.com/video/{resolved_aweme_id}"
    detail.setdefault("aweme_id", resolved_aweme_id)
    if sec_uid:
        detail.setdefault("sec_uid", sec_uid)
    return ResolvedDouyinVideo(
        aweme_id=resolved_aweme_id,
        url=resolved_url or canonical_url,
        sec_uid=sec_uid,
        name=name,
        aweme=detail,
    )


def extract_sec_uid(value: str) -> str:
    text = str(value or "")
    patterns = [
        r"/user/([^/?#\"']+)",
        r'"secUid"\s*:\s*"([^"]+)"',
        r'"sec_uid"\s*:\s*"([^"]+)"',
        r"sec_uid=([^&#\"']+)",
        r"secUid=([^&#\"']+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def extract_aweme_id(value: str) -> str:
    text = str(value or "")
    patterns = [
        r"/video/(\d+)",
        r"[?&](?:modal_id|aweme_id|item_id)=(\d+)",
        r'"aweme_id"\s*:\s*"?([0-9]+)"?',
        r'"group_id"\s*:\s*"?([0-9]+)"?',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    if re.fullmatch(r"\d{12,}", text.strip()):
        return text.strip()
    return ""


def _extract_first_url(value: str) -> str:
    match = re.search(r"https?://[^\s\"'<>]+", value)
    return match.group(0).rstrip("，。)") if match else ""


def _normalize_douyin_url(url: str) -> str:
    value = url.strip()
    if not value.startswith(("http://", "https://")):
        value = "https://" + value.lstrip("/")
    return value


def _resolve_redirect_url(url: str, cookies: dict[str, str]) -> str:
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            cookies={key: value for key, value in (cookies or {}).items() if value},
            allow_redirects=True,
            timeout=15,
        )
        if response.url:
            return str(response.url)
    except requests.RequestException as exc:
        logger.warning("解析抖音主页跳转失败: %s", exc)
    return ""


def _fetch_page_html(url: str, cookies: dict[str, str]) -> str:
    parsed = urlparse(url)
    if not parsed.netloc.endswith("douyin.com"):
        return ""
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            cookies={key: value for key, value in (cookies or {}).items() if value},
            timeout=15,
        )
        if response.status_code == 200:
            return response.text
    except requests.RequestException as exc:
        logger.warning("读取抖音主页失败: %s", exc)
    return ""


def _is_gallery_aweme(aweme: dict[str, Any]) -> bool:
    aweme_type = aweme.get("aweme_type")
    return bool(
        aweme.get("image_post_info")
        or aweme.get("images")
        or aweme.get("image_list")
        or aweme_type in {2, 68, 150}
    )


async def _fetch_profile_from_posts(config: AppConfig, sec_uid: str) -> dict[str, Any]:
    try:
        async with DouyinAPIClient(config.cookies) as api_client:
            response = await api_client.get_user_post(sec_uid, max_cursor=0, count=1)
    except Exception as exc:
        logger.warning("通过作品列表补齐抖音博主信息失败: sec_uid=%s error=%s", sec_uid, exc)
        return {}
    items = response.get("items") or response.get("aweme_list") or []
    if not isinstance(items, list) or not items:
        return {}
    item = items[0] if isinstance(items[0], dict) else {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    author_user = item.get("author_user_info") if isinstance(item.get("author_user_info"), dict) else {}
    avatar = author.get("avatar_thumb") or author_user.get("avatar_thumb") or {}
    avatar_url = ""
    if isinstance(avatar, dict):
        urls = avatar.get("url_list")
        if isinstance(urls, list) and urls:
            avatar_url = str(urls[0] or "")
    return {
        "nickname": author.get("nickname") or author_user.get("nickname") or item.get("nickname") or "",
        "avatar_url": avatar_url,
    }
