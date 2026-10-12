import asyncio
from types import SimpleNamespace

import pytest

from kenradar.core.checker import Checker


class EmptyAPI:
    def __init__(self, cookies):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get_user_post(self, *args, **kwargs):
        return {'aweme_list': [], 'has_more': False}


class Config:
    cookies = {}

    def get(self, key, default=None):
        return False if key == 'download.browser_fallback.enabled' else default


def test_empty_history_is_not_success_and_does_not_advance_checkpoint(monkeypatch):
    monkeypatch.setattr('kenradar.core.checker.DouyinAPIClient', EmptyAPI)
    checker = Checker(Config(), object())
    with pytest.raises(RuntimeError, match='空列表'):
        asyncio.run(checker.fetch_aweme_history(SimpleNamespace(sec_uid='author', id=1)))


def test_history_browser_records_only_verified_results(monkeypatch):
    monkeypatch.setattr('kenradar.core.checker.DouyinAPIClient', EmptyAPI)
    class BrowserConfig(Config):
        def get(self, key, default=None):
            return True if key == 'download.browser_fallback.enabled' else default
    recorded = []
    class DB:
        def insert_aweme(self, creator, item, status):
            recorded.append(item['aweme_id'])
        def update_blogger_checkpoint(self, creator, item):
            assert item == '001'
    async def verified(*args, **kwargs):
        return [{'aweme_id': '001', 'aweme_type': 0}, {'aweme_id': '002', 'aweme_type': 68}]
    monkeypatch.setattr('kenradar.vendor.douyin_downloader.browser_resolver.fetch_user_posts_with_browser', verified)
    result = asyncio.run(Checker(BrowserConfig(), DB()).fetch_aweme_history(SimpleNamespace(sec_uid='author', id=1)))
    assert recorded == ['001']
    assert len(result) == 1


def test_empty_job_restart_keeps_original_id_with_real_sqlite(tmp_path, monkeypatch):
    import json
    from kenradar.core.config import load_config
    from kenradar.core.workflow import Workflow
    from kenradar.storage import create_database
    from kenradar.storage.migrate import upgrade_database
    path = tmp_path / 'config.yaml'
    path.write_text(json.dumps({'app': {'data_dir': str(tmp_path), 'database_url': 'sqlite:///' + (tmp_path / 'db.sqlite3').as_posix()}}), encoding='utf-8')
    upgrade_database(str(path))
    config = load_config(path)
    db = create_database(config)
    creator = db.upsert_blogger('https://www.douyin.com/user/source', '来源', 'source', enabled=False)
    job = db.create_research_job(platform='douyin', blogger_id=creator, blogger_name='来源', limit_count=0, since_time=None, until_time=None, push_enabled=False, force_enabled=False)
    db.update_research_job(job, status='failed')
    workflow = object.__new__(Workflow)
    workflow.config, workflow.database = config, db
    async def rediscover(source, **kwargs):
        assert source == 'source'
        assert kwargs['resume_job_id'] == job
        assert kwargs['limit'] == 0 and not kwargs['push']
        return {'job_id': job}
    monkeypatch.setattr(workflow, 'research_blogger', rediscover)
    assert asyncio.run(workflow.restart_research_job(job)) == {'job_id': job}
    assert db.get_research_job(job)['status'] == 'failed'
