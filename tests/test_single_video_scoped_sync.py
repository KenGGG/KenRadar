from pathlib import Path
from types import SimpleNamespace
from kenradar.core.workflow import Workflow


def test_single_video_uses_scoped_article_sync_not_whole_site(tmp_path, monkeypatch):
    note = tmp_path/'source.md';note.write_text('unchanged',encoding='utf-8')
    article = tmp_path/'article.html';article.write_text('<p>ASR</p>',encoding='utf-8')
    calls=[]
    workflow = object.__new__(Workflow)
    workflow.config = SimpleNamespace(get=lambda key,default=None:default)
    workflow.publisher = SimpleNamespace(
        publish_markdown=lambda p,**kw:calls.append(('render',kw)),
        public_url_for=lambda p:'https://example.invalid/article.html',
        html_path_for=lambda p:article)
    workflow._sync_github_publication=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('unsafe whole-site sync'))
    workflow._wait_public_urls=lambda urls,**kw:{urls[0]:True}
    class Manager:
        def __init__(self,config): pass
        def sync_single_article(self,path,title=''):
            calls.append(('isolated',path))
            return {'ok':True,'enabled':True,'pushed':True,'message':'scoped'}
        def write_last_sync(self,result): pass
    monkeypatch.setattr('kenradar.core.workflow.GithubSyncManager',Manager)
    result=workflow._publish_single_video_result(str(note))
    assert calls==[('render',{'update_index':False}),('isolated',article)]
    assert result['github_synced'] and result['public_url_ready']
    assert note.read_text(encoding='utf-8')=='unchanged'


def test_daily_subscription_defers_inline_publication():
    import asyncio
    from unittest.mock import AsyncMock
    from kenradar.jobs.handlers import _execute_task_run_raw
    workflow = SimpleNamespace(
        config=SimpleNamespace(get=lambda key, default=None: 'subscription_daily' if key == 'schedule.mode' else default),
        process_single_url=AsyncMock(return_value={'status': 'success'}))
    asyncio.run(_execute_task_run_raw(workflow, 'process_url', {'url': 'https://www.douyin.com/video/123', 'subscription_id': 4}))
    assert workflow.process_single_url.call_args.kwargs['publish'] is False


def test_archived_video_does_not_publish_when_deferred(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from kenradar.core import workflow as module
    w = object.__new__(Workflow)
    w.config = SimpleNamespace()
    w.database = SimpleNamespace(upsert_blogger=lambda **kw: 1, insert_aweme=lambda *a, **kw: None,
        is_aweme_fully_processed=lambda _: True, get_summary=lambda _: {'summary_path': 'note.md'})
    w._load_aweme_for_retry = lambda _: {'title': 'fixture', 'nickname': 'fixture'}
    w._detail_url = lambda _: '/content'
    w._publish_single_video_result = lambda _: (_ for _ in ()).throw(AssertionError('inline publication'))
    monkeypatch.setattr(module, 'resolve_douyin_video', AsyncMock(return_value=SimpleNamespace(
        url='https://www.douyin.com/video/123', aweme_id='123', sec_uid='fixture', name='fixture', aweme={})))
    result = asyncio.run(w.research_video(video='https://www.douyin.com/video/123', publish=False))
    assert result['status'] == 'skipped'
