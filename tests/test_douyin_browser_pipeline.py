"""Browser fallback exercises the same connector consumed by the durable monitor."""
import asyncio
import pytest
from kenradar.core.config import AppConfig
from kenradar.sources.douyin import connector as module
from kenradar.vendor.douyin_downloader import browser_resolver as browser

UID = 'MS4wLjABAAAA-example'


def test_natural_regional_douyin_host_is_allowed_but_suffix_spoof_is_not():
    assert browser._author_post_request('https://www-hj.douyin.com/aweme/v1/web/aweme/post/?sec_user_id='+UID+'&max_cursor=0', UID) == '0'
    assert browser._author_post_request('https://douyin.com.evil.test/aweme/v1/web/aweme/post/?sec_user_id='+UID, UID) is None


def config(**extra):
    return AppConfig({'download': {'browser_fallback': {'enabled': True}},
                      'bloggers': [{'sec_uid': UID, 'enabled': True}], **extra}, path=__import__('pathlib').Path('isolated.yaml'))

class Denied:
    def __init__(self, *_): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass
    async def get_user_post(self, *args, **kwargs):
        raise RuntimeError('DOUYIN_ARGUS: list HTTP 403 Uifid Not Found')

def test_denied_direct_list_uses_complete_author_browser_snapshot(monkeypatch):
    monkeypatch.setattr(module, 'DouyinAPIClient', Denied)
    calls = []
    async def fetch(c, uid, limit=0):
        calls.append((uid, limit))
        return [{'aweme_id': '7700181075120721167', 'author': {'sec_uid': UID},
                 'create_time': 1792838124, 'aweme_type': 0},
                {'aweme_id': '7260137356756405561', 'author': {'sec_uid': UID},
                 'create_time': 1690382460, 'aweme_type': 68}]
    monkeypatch.setattr(browser, 'fetch_user_posts_with_browser', fetch)
    adapter = module.DouyinConnector(config())
    page = asyncio.run(adapter.list_recent(adapter.map_source(UID, 'author')))
    assert calls == [(UID, 0)]
    assert not page.has_more
    assert [i.external_content_id for i in page.items] == ['7700181075120721167']
    assert adapter.last_listing_observation == {
        'direct': 'failed', 'direct_error_code': 'DOUYIN_ARGUS', 'browser': 'success',
        'complete': True, 'listed': 2, 'supported': 1, 'unsupported': 1}


def test_browser_resolution_prefers_validated_enabled_author_metadata(monkeypatch):
    aid='7697294965654703400'
    item={'aweme_id':aid,'author':{'sec_uid':UID},'create_time':1792166162,'video':{'play_addr':{'url_list':['https://media.example.invalid/video.mp4']}}}
    async def fetch(c,uid,limit=0):return [item]
    monkeypatch.setattr(browser,'fetch_user_posts_with_browser',fetch)
    monkeypatch.setattr(browser,'_chrome_executable',lambda path:'')
    resolved=asyncio.run(browser.resolve_video_with_browser(config(),'https://www.douyin.com/video/'+aid,aid))
    assert resolved==item


def test_browser_pages_require_explicit_status_and_unbroken_cursor_chain():
    collector = browser.AuthorPostCollector(UID, max_pages=3, max_items=40)
    item = {'aweme_id': '7700181075120721167', 'author': {'sec_uid': UID}, 'create_time': 1792838124}
    with pytest.raises(RuntimeError, match='STATUS'):
        collector.accept({'aweme_list': [item], 'has_more': 0}, request_cursor='0')
    collector = browser.AuthorPostCollector(UID, max_pages=3, max_items=40)
    collector.accept({'status_code': 0, 'aweme_list': [item], 'has_more': 1, 'max_cursor': 100}, request_cursor='0')
    assert not collector.finished
    with pytest.raises(RuntimeError, match='CURSOR'):
        collector.accept({'status_code': 0, 'aweme_list': [], 'has_more': 0}, request_cursor='99')
