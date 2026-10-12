import json

from scripts.recover_pages_sources import inventory, import_verified
from kenradar.core.config import load_config
from kenradar.storage import create_database
from kenradar.storage.migrate import upgrade_database


def test_evidence_and_disabled_idempotent_import(tmp_path):
    root = tmp_path / 'pages'
    page = root / 'notes/douyin/同名博主/a.html'
    page.parent.mkdir(parents=True)
    page.write_text('<a href="https://www.douyin.com/user/SEC_001">主页</a><a href="https://www.douyin.com/video/000123">视频</a>', encoding='utf-8')
    unknown = root / 'notes/douyin/只有昵称/b.html'
    unknown.parent.mkdir(parents=True)
    unknown.write_text('<a href="https://evil.example/douyin.com/user/guess">不能采用</a>', encoding='utf-8')
    manifest = inventory(root, 'https://example.org/pages')
    assert len(manifest['sources']) == 2
    verified = next(s for s in manifest['sources'] if s['source_key'])
    assert verified['video_ids'] == ['000123']
    config = tmp_path / 'config.yaml'
    config.write_text(json.dumps({'app': {'database_url': 'sqlite:///' + (tmp_path / 'test.sqlite3').as_posix(), 'data_dir': str(tmp_path)}}), encoding='utf-8')
    upgrade_database(str(config))
    db = create_database(load_config(config))
    assert len(import_verified(db, manifest)['imported_ids']) == 1
    row = db.list_source_subscriptions()[0]
    assert not row['enabled'] and not row['auto_publish'] and row['notify_mode'] == 'off'
    db.set_source_subscription_enabled(row['id'], True)
    assert import_verified(db, manifest)['imported_ids'] == []
    assert db.list_source_subscriptions()[0]['enabled']
    page.write_text('<a href="https://www.douyin.com/user/A">A</a><a href="https://www.douyin.com/user/B">B</a>', encoding='utf-8')
    assert all(s['recovery_status'] == 'identity_required' for s in inventory(root, 'https://example.org')['sources'])
