from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from urllib.parse import unquote
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

    # Reuse the same natural author-page adapter as automatic subscriptions.
    # Its metadata is author/ID/time validated and avoids a second legacy page context.
    sources = [row for row in config.get('bloggers', []) or []
               if isinstance(row, dict) and row.get('enabled', True) and row.get('sec_uid')]
    for source in sources[:3]:
        sec_uid = str(source['sec_uid'])
        posts = await fetch_user_posts_with_browser(config, sec_uid, limit=0)
        for item in posts:
            if item.get('aweme_id') == aweme_id and (item.get('author') or {}).get('sec_uid') == sec_uid:
                return item

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
                await _harvest_dom_aweme(page, found, aweme_id)
                if found.get("aweme"):
                    break
                await page.wait_for_timeout(2000)
            if not found.get("aweme"):
                # Known source homepages can expose matching post JSON even
                # when the standalone video route returns the generic demo.
                for source in config.get("bloggers", []) or []:
                    profile = str(source.get("url") or "") if isinstance(source, dict) else ""
                    if not profile.startswith("https://www.douyin.com/user/"):
                        continue
                    await page.goto(profile, wait_until="domcontentloaded", timeout=45_000)
                    for _ in range(10):
                        await _harvest_dom_aweme(page, found, aweme_id)
                        if found.get("aweme"):
                            break
                        await page.wait_for_timeout(2000)
                    if found.get("aweme"):
                        break
        finally:
            page_info = await _safe_page_info(page)
            await context.close()
            await browser.close()

    aweme = found.get("aweme")
    if isinstance(aweme, dict):
        aweme.setdefault("aweme_id", aweme_id)
        return aweme
    # A media response or the first DOM video may be an advertisement or the
    # site's login/demo clip. Never assign the requested ID to unverified media.
    logger.warning("浏览器兜底未获取到视频信息: aweme_id=%s page=%s", aweme_id, page_info)
    return None


def _author_post_request(url: str, sec_uid: str) -> str | None:
    from urllib.parse import urlsplit, parse_qs
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('www.douyin.com', 'douyin.com', 'www-hj.douyin.com') or parsed.path != '/aweme/v1/web/aweme/post/':
        return None
    query = parse_qs(parsed.query)
    if query.get('sec_user_id', [''])[0] != sec_uid:
        return None
    return query.get('max_cursor', ['0'])[0]


class AuthorPostCollector:
    """Fail closed on incomplete, foreign-author or unordered browser pagination."""
    def __init__(self, sec_uid: str, *, max_pages: int = 50, max_items: int = 1000):
        self.sec_uid, self.max_pages, self.max_items = sec_uid, max_pages, max_items
        self.items: dict[str, dict[str, Any]] = {}
        self.pages: dict[str, tuple] = {}
        self.cursor = '0'
        self.finished = False

    def accept(self, data: Any, *, request_cursor: str) -> None:
        if not isinstance(data, dict) or type(data.get('status_code')) is not int or data['status_code'] != 0:
            raise RuntimeError('DOUYIN_BROWSER_STATUS: unsuccessful or missing status')
        posts = data.get('aweme_list')
        if not isinstance(posts, list) or type(data.get('has_more')) not in (int, bool) or data['has_more'] not in (0, 1):
            raise RuntimeError('DOUYIN_BROWSER_SCHEMA: invalid list or has_more')
        for item in posts:
            if (not isinstance(item, dict) or not isinstance(item.get('author'), dict)
                    or item['author'].get('sec_uid') != self.sec_uid
                    or not isinstance(item.get('aweme_id'), str) or not item['aweme_id'].isdigit()
                    or type(item.get('create_time')) is not int or item['create_time'] <= 0):
                raise RuntimeError('DOUYIN_BROWSER_IDENTITY: invalid author, ID or source timestamp')
        next_cursor = str(data.get('max_cursor') or '')
        fingerprint = (tuple(x['aweme_id'] for x in posts), bool(data['has_more']), next_cursor)
        if request_cursor in self.pages:
            if self.pages[request_cursor] != fingerprint:
                raise RuntimeError('DOUYIN_BROWSER_CURSOR: inconsistent duplicate page')
            return
        if self.finished or request_cursor != self.cursor:
            raise RuntimeError('DOUYIN_BROWSER_CURSOR: broken pagination chain')
        if data['has_more'] and (not next_cursor.isdigit() or next_cursor == request_cursor or next_cursor in self.pages):
            raise RuntimeError('DOUYIN_BROWSER_CURSOR: nonadvancing cursor')
        if len(self.pages) >= self.max_pages or (data['has_more'] and len(self.pages) + 1 >= self.max_pages):
            raise RuntimeError('DOUYIN_BROWSER_BUDGET: page budget exhausted')
        self.pages[request_cursor] = fingerprint
        self.items.update({item['aweme_id']: item for item in posts})
        if len(self.items) > self.max_items:
            raise RuntimeError('DOUYIN_BROWSER_BUDGET: item budget exhausted')
        self.cursor = next_cursor
        self.finished = not bool(data['has_more'])


async def fetch_user_posts_with_browser(
    config: AppConfig, sec_uid: str, limit: int = 0, *, first_page_only: bool = False
) -> list[dict[str, Any]]:
    """Natural navigation only; a complete bounded snapshot is mandatory even for recent scans."""
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
    from urllib.parse import urlsplit, parse_qs
    chrome = _chrome_executable(str(config.get("download.browser_fallback.chrome_path", "") or ""))
    if not chrome:
        raise RuntimeError("DOUYIN_BROWSER_UNAVAILABLE: Chrome not found")
    collector = AuthorPostCollector(sec_uid,
        max_pages=min(50, max(1, int(config.get('download.browser_fallback.max_pages', 50)))),
        max_items=min(2000, max(20, int(config.get('download.browser_fallback.max_items', 1000)))))
    errors: list[str] = []
    timeout = min(300, max(30, int(config.get('download.browser_fallback.history_timeout', 180))))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=chrome,
            headless=bool(config.get('download.browser_fallback.headless', True)))
        try:
            async with asyncio.timeout(timeout):
                context = await browser.new_context(locale='zh-CN', timezone_id='Asia/Shanghai',
                                                    viewport={'width': 1280, 'height': 900})
                await context.add_cookies(_browser_cookie_payload(config.cookies))
                page = await context.new_page()
                async def capture(response):
                    request_cursor = _author_post_request(response.url, sec_uid)
                    if request_cursor is None:
                        return
                    try:
                        if response.status != 200:
                            raise RuntimeError('DOUYIN_BROWSER_HTTP: rejected author list')
                        collector.accept(await response.json(), request_cursor=request_cursor)
                    except Exception as exc:
                        code = str(exc).split(':', 1)[0]
                        errors.append(code if code.startswith('DOUYIN_BROWSER_') else 'DOUYIN_BROWSER_SCHEMA')
                page.on('response', capture)
                try:
                    await page.goto(f'https://www.douyin.com/user/{sec_uid}', wait_until='domcontentloaded', timeout=60000)
                except PlaywrightTimeoutError:
                    logger.warning('Author navigation timed out; continue validating captured pagination')
                while not collector.finished and not (first_page_only and collector.pages):
                    if errors:
                        raise RuntimeError(errors[0])
                    # Do not interact with login or verification challenges.
                    body = await page.locator('body').inner_text(timeout=5000)
                    if any(marker in body for marker in ('请完成下方验证', '拖动滑块', '安全验证')):
                        raise RuntimeError('DOUYIN_BROWSER_CHALLENGE: user verification required')
                    await page.mouse.move(850, 700)
                    await page.mouse.wheel(0, 2200)
                    await page.wait_for_timeout(1500)
                if errors:
                    raise RuntimeError(errors[0])
                result = sorted(collector.items.values(), key=lambda item: item['create_time'], reverse=True)
                logger.info('浏览器来源读取完成: count=%s pages=%s complete=%s',
                            len(result), len(collector.pages), collector.finished)
                return result[:limit] if limit > 0 else result
        except TimeoutError:
            raise RuntimeError('DOUYIN_BROWSER_INCOMPLETE: timeout before terminal page') from None
        finally:
            await browser.close()


async def _harvest_dom_aweme(page: Any, found: dict[str, Any], aweme_id: str) -> None:
    try:
        scripts = await page.locator('script[type="application/json"], script#RENDER_DATA').all_text_contents()
    except Exception:
        return
    for text in scripts:
        try:
            data = json.loads(unquote(text))
        except (ValueError, TypeError):
            continue
        aweme = _find_aweme(data, aweme_id)
        if aweme:
            found["aweme"] = aweme
            return


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
        if isinstance(detail, dict) and str(detail.get("aweme_id") or "") == aweme_id and isinstance(detail.get('video'), dict) and detail['video']:
            return detail
        if str(value.get("aweme_id") or "") == aweme_id and isinstance(value.get('video'), dict) and value['video']:
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
