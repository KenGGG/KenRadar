import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from kenradar.vendor.douyin_downloader import browser_resolver as module


@pytest.mark.parametrize('foreign_author', [False, True])
def test_navigation_timeout_keeps_validating_author_pages(monkeypatch, foreign_author):
    from playwright.async_api import TimeoutError as NavigationTimeout
    uid = 'fixture-author'
    data = {'status_code': 0, 'has_more': 0, 'max_cursor': 0,
            'aweme_list': [{'aweme_id': '123', 'create_time': 1790000000,
                            'author': {'sec_uid': 'foreign' if foreign_author else uid}}]}
    response = SimpleNamespace(status=200,
        url='https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id='+uid+'&max_cursor=0',
        json=AsyncMock(return_value=data))
    class Page:
        def on(self, event, callback): self.capture = callback
        async def goto(self, *args, **kwargs):
            await self.capture(response)
            raise NavigationTimeout('navigation stalled after response')
    page = Page()
    context = SimpleNamespace(add_cookies=AsyncMock(), new_page=AsyncMock(return_value=page))
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
    class Playwright:
        async def __aenter__(self): return SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
        async def __aexit__(self, *args): pass
    monkeypatch.setattr('playwright.async_api.async_playwright', Playwright)
    monkeypatch.setattr(module, '_chrome_executable', lambda *_: 'fixture-chrome')
    config = SimpleNamespace(cookies={}, get=lambda key, default=None: default)
    if foreign_author:
        with pytest.raises(RuntimeError, match='DOUYIN_BROWSER_IDENTITY'):
            asyncio.run(module.fetch_user_posts_with_browser(config, uid))
    else:
        assert asyncio.run(module.fetch_user_posts_with_browser(config, uid))[0]['aweme_id'] == '123'
    browser.close.assert_awaited_once()
