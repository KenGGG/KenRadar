import asyncio
import json

from kenradar.vendor.douyin_downloader.browser_resolver import _find_aweme, _harvest_dom_aweme


def test_browser_requires_matching_structured_identity():
    target = '000123'
    assert _find_aweme({'video': {'url': 'https://example.org/demo.mp4'}}, target) is None
    assert _find_aweme({'aweme_detail': {'aweme_id': '999'}}, target) is None
    matching = {'aweme_id': target, 'video': {'play_addr': {'url_list': ['https://example.org/actual.mp4']}}}

    class Scripts:
        async def all_text_contents(self):
            return ['bad json', json.dumps({'nested': [matching]})]

    class Page:
        def locator(self, selector):
            return Scripts()

    found = {'video_url': 'https://example.org/demo.mp4'}
    asyncio.run(_harvest_dom_aweme(Page(), found, target))
    assert found['aweme'] == matching
