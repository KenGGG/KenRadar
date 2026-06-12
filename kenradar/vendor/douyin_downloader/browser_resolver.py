from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from typing import Any

from kenradar.core.config import AppConfig

logger = logging.getLogger(__name__)


def browser_fallback_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
    except Exception:
        return False
    return bool(_chrome_executable(""))


async def resolve_video_with_browser(config: AppConfig, url: str, aweme_id: str) -> dict[str, Any] | None:
    """Resolve a single Douyin video by letting Chrome load the real page.

    This mirrors the upstream downloader's browser fallback idea, but keeps the
    result in KenRadar's local aweme shape. It is intentionally only used after
    the normal detail API fails.
    """

    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        logger.warning("Playwright 不可用，跳过浏览器兜底: %s", exc)
        return None

    chrome_path = _chrome_executable(str(config.get("download.browser_fallback.chrome_path", "") or ""))
    if not chrome_path:
        logger.warning("未找到 Chrome 可执行文件，跳过浏览器兜底")
        return None

    headless = bool(config.get("download.browser_fallback.headless", True))
    wait_seconds = max(10, int(config.get("download.browser_fallback.wait_seconds", 180) or 180))
    target_url = url or f"https://www.douyin.com/video/{aweme_id}"
    found: dict[str, Any] = {"aweme": None, "video_url": "", "title": "", "author": ""}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            executable_path=chrome_path,
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1600, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        cookies = _browser_cookie_payload(config.cookies)
        if cookies:
            await context.add_cookies(cookies)
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """
        )
        page = await context.new_page()

        async def handle_response(response: Any) -> None:
            response_url = str(response.url or "")
            if response.status != 200:
                return
            if _looks_like_video_url(response_url):
                found["video_url"] = found.get("video_url") or response_url
                return
            if not _response_may_contain_aweme(response_url, aweme_id):
                return
            try:
                content_type = str(response.headers.get("content-type", "") or "")
                if "json" in content_type:
                    data = await response.json()
                    aweme = _find_aweme(data, aweme_id)
                    if aweme:
                        found["aweme"] = aweme
                else:
                    text = await response.text()
                    if aweme_id in text and not found.get("video_url"):
                        match = re.search(r'https?://[^"\\]+(?:\.mp4|/play/)[^"\\]*', text)
                        if match:
                            found["video_url"] = match.group(0)
            except Exception:
                return

        page.on("response", handle_response)

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:
            logger.warning("浏览器打开抖音页面超时或失败，继续等待页面状态: %s", exc)

        deadline = asyncio.get_running_loop().time() + wait_seconds
        try:
            while asyncio.get_running_loop().time() < deadline:
                await _harvest_dom_video(page, found)
                if found.get("aweme") or found.get("video_url"):
                    break
                await page.wait_for_timeout(2000)
        finally:
            page_info = await _safe_page_info(page)
            await context.close()
            await browser.close()

    aweme = found.get("aweme")
    if isinstance(aweme, dict):
        aweme.setdefault("aweme_id", aweme_id)
        return aweme
    video_url = str(found.get("video_url") or "").strip()
    if video_url:
        return _minimal_aweme_from_browser(aweme_id, video_url, found, page_info)
    logger.warning("浏览器兜底未获取到视频信息: aweme_id=%s page=%s", aweme_id, page_info)
    return None


def _chrome_executable(configured: str) -> str:
    if configured:
        return configured
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return ""


def _browser_cookie_payload(cookies: dict[str, str]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for domain in (".douyin.com", ".iesdouyin.com"):
        for key, value in (cookies or {}).items():
            if not key or not value:
                continue
            payload.append({"name": str(key), "value": str(value), "domain": domain, "path": "/"})
    return payload


def _looks_like_video_url(url: str) -> bool:
    lowered = url.lower()
    return bool(
        ".mp4" in lowered
        or "/aweme/v1/play/" in lowered
        or "mime_type=video" in lowered
        or ("video" in lowered and ("douyinvod" in lowered or "byte" in lowered))
    )


def _response_may_contain_aweme(url: str, aweme_id: str) -> bool:
    return bool(aweme_id in url or "aweme/detail" in url or "/aweme/v1/" in url or "modal_id" in url)


def _find_aweme(value: Any, aweme_id: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        detail = value.get("aweme_detail")
        if isinstance(detail, dict) and str(detail.get("aweme_id") or "") == aweme_id:
            return detail
        if str(value.get("aweme_id") or "") == aweme_id:
            return value
        for child in value.values():
            found = _find_aweme(child, aweme_id)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_aweme(child, aweme_id)
            if found:
                return found
    return None


async def _harvest_dom_video(page: Any, found: dict[str, Any]) -> None:
    try:
        info = await page.evaluate(
            """
            () => {
                const video = document.querySelector('video');
                const title = document.title || '';
                const authorEl = document.querySelector('[class*="author"], [class*="nickname"]');
                return {
                    href: location.href,
                    title,
                    author: authorEl ? (authorEl.innerText || '') : '',
                    videoSrc: video ? (video.currentSrc || video.src || '') : '',
                    videoCount: document.querySelectorAll('video').length
                };
            }
            """
        )
    except Exception:
        return
    if isinstance(info, dict):
        if info.get("videoSrc"):
            found["video_url"] = found.get("video_url") or str(info["videoSrc"])
        if info.get("title"):
            found["title"] = str(info["title"])
        if info.get("author"):
            found["author"] = str(info["author"])


async def _safe_page_info(page: Any) -> dict[str, Any]:
    try:
        info = await page.evaluate(
            """
            () => ({
                href: location.href,
                title: document.title || '',
                text: (document.body && document.body.innerText || '').slice(0, 120),
                videoCount: document.querySelectorAll('video').length
            })
            """
        )
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _minimal_aweme_from_browser(aweme_id: str, video_url: str, found: dict[str, Any], page_info: dict[str, Any]) -> dict[str, Any]:
    title = str(found.get("title") or page_info.get("title") or aweme_id).replace(" - 抖音", "").strip()
    author = str(found.get("author") or "单视频来源").strip() or "单视频来源"
    return {
        "aweme_id": aweme_id,
        "desc": title,
        "title": title,
        "create_time": int(__import__("time").time()),
        "aweme_type": 0,
        "video_url": f"https://www.douyin.com/video/{aweme_id}",
        "author": {"nickname": author, "sec_uid": ""},
        "video": {
            "play_addr": {
                "uri": "",
                "url_list": [video_url],
            }
        },
        "browser_fallback": {
            "page": page_info,
            "video_url": video_url,
        },
    }
