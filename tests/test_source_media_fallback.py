import asyncio
from types import SimpleNamespace
from pathlib import Path
from kenradar.core.config import AppConfig
from kenradar.core import downloader as module


def test_incomplete_detail_does_not_discard_identity_verified_source_media(tmp_path,monkeypatch):
    aid='7697294965654703400'
    config=AppConfig({'download':{'path':str(tmp_path/'media')}},tmp_path/'config/config.yaml')
    updates=[]
    service=module.Downloader(config,SimpleNamespace(update_aweme_download=lambda *a,**k:updates.append((a,k))))
    aweme={'aweme_id':aid,'create_time':1792166162,'desc':'fixture','author':{'sec_uid':'fixture'},'video':{'play_addr':{'url_list':['https://media.example.invalid/fixture.mp4']}}}
    path=service._build_save_path(aweme,'fixture');path.write_bytes(b'isolated fixture - no external media')
    class Client:
        BASE_URL='https://www.douyin.com'
        def __init__(self,*args):self.headers={}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def get_video_detail(self,aweme_id):return {'aweme_id':aid,'desc':'incomplete detail'}
    monkeypatch.setattr(module,'DouyinAPIClient',Client)
    result=asyncio.run(service.download_aweme(aweme,'fixture'))
    assert result==path
    assert updates[0][0][0:2]==(aid,'done')


def test_detail_without_playable_media_reaches_verified_browser_adapter(tmp_path,monkeypatch):
    from kenradar.core import source_resolver
    aid='7697294965654703400'
    class Client:
        def __init__(self,*a):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
        async def get_video_detail(self,*a):return {'aweme_id':aid}
    async def browser(c,url,requested):
        assert requested==aid
        return {'aweme_id':aid,'create_time':1792166162,'author':{'sec_uid':'fixture'},'video':{'play_addr':{'url_list':['https://media.example.invalid/fixture.mp4']}}}
    monkeypatch.setattr(source_resolver,'DouyinAPIClient',Client)
    monkeypatch.setattr(source_resolver,'resolve_video_with_browser',browser)
    config=AppConfig({'download':{'browser_fallback':{'enabled':True}}},tmp_path/'config/config.yaml')
    result=asyncio.run(source_resolver.resolve_douyin_video(config,'https://www.douyin.com/video/'+aid))
    assert result.aweme['video']['play_addr']['url_list']
