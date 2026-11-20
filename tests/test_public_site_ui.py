import json
from pathlib import Path

from kenradar.core.config import AppConfig
from kenradar.publishing.static_site import StaticSitePublisher
from kenradar.publishing.public_site import refresh_existing


def test_legacy_video_id_title_uses_heading_then_published_filename(tmp_path):
    from kenradar.publishing.public_site import page_title
    path = tmp_path/'2026-09-28_市场展望与研究_7690382152403275513.html'
    assert page_title('<title>7690382152403275513｜KenRadar</title><h1>真实标题 &amp; 依据</h1>', path) == '真实标题 & 依据'
    assert page_title('<title>7690382152403275513｜KenRadar</title><h1>7690382152403275513</h1>', path) == '市场展望与研究'
    assert page_title('<h1>1984</h1>', path) == '1984'


def test_numeric_legacy_title_never_replaces_reading_title_in_upgrade(tmp_path):
    pub = publisher(tmp_path)
    path = pub.output_dir/'notes/douyin/来源/2026-09-28_真实标题_7690382152403275513.html'
    path.parent.mkdir(parents=True)
    path.write_text('<title>7690382152403275513｜KenRadar</title><main><h1>真实标题</h1><p>保留正文</p></main>', encoding='utf8')
    refresh_existing(pub)
    result = path.read_text(encoding='utf8')
    assert '<h1>真实标题</h1>' in result
    items = json.loads((pub.output_dir/'content-index.json').read_text(encoding='utf8'))['items']
    assert items[0]['title'] == '真实标题'


def publisher(tmp_path):
    return StaticSitePublisher(AppConfig({'app': {'data_dir': str(tmp_path/'data')}, 'output': {'obsidian_root': str(tmp_path/'data')}, 'publishing': {'github_pages': {'enabled': True, 'output_dir': str(tmp_path/'site'), 'preserve_historical_pages': True}}}, tmp_path/'config/config.yaml'))


def test_public_catalog_identity_privacy_and_article_contract(tmp_path):
    pub = publisher(tmp_path)
    folder = tmp_path/'data/notes/douyin/来源 A'
    folder.mkdir(parents=True)
    note = folder/'中文 标题_7697294965654703400.md'
    note.write_text('---\nplatform: douyin\ncreator: 来源 A\nvideo_id: "7697294965654703400"\npublished_at: 2026-10-16\ntopics: [量化策略, ETF]\n---\n# 量化研究\n> [!summary]\n> 来源观点摘要\n\n## 一、内容简述\n正文证据\n## 二、分段原文\n完整整理\n## 三、知识关联\n[[ETF]]\n## 四、视频原始转录\n不参与搜索的原稿', encoding='utf8')
    pub.publish_markdown(note)
    private = folder/'copied.md'
    private.write_text('---\nhermes_private: true\n---\n# PRIVATE TITLE', encoding='utf8')
    (pub.output_dir/'notes/douyin/来源 A/copied.html').write_text('<title>PRIVATE TITLE</title>', encoding='utf8')
    alias = pub.html_path_for(note).with_name('old_7697294965654703400.html')
    alias.write_text('<title>历史标题</title>', encoding='utf8')
    pub.write_index()
    catalog = json.loads((pub.output_dir/'content-index.json').read_text(encoding='utf8'))
    assert len(catalog['items']) == 1
    item = catalog['items'][0]
    assert item['external_content_id'] == '7697294965654703400'
    assert item['topics'] == ['量化策略', 'ETF']
    assert item['published_at'].startswith('2026-10-16')
    assert item['summary'] == '来源观点摘要'
    assert '不参与搜索的原稿' not in json.dumps(catalog, ensure_ascii=False)
    assert str(tmp_path) not in json.dumps(catalog)
    assert 'PRIVATE TITLE' not in json.dumps(catalog)
    article = pub.html_path_for(note).read_text(encoding='utf8')
    assert '<details class="transcript">' in article and ' open' not in article
    assert 'data-pagefind-ignore' in article
    assert '../../../assets/site.css' in article
    assert '内容来源的摘要' in article
    assert '不参与搜索的原稿' in article
    assert article.index('一、内容简述') < article.index('二、分段原文') < article.index('三、知识关联')
    assert (pub.output_dir/'sources.html').is_file()


def test_restyl_restores_historical_links_without_rewriting_markdown(tmp_path):
    pub = publisher(tmp_path)
    folder = pub.output_dir/'notes/podcast/播客'
    folder.mkdir(parents=True)
    old = folder/'中文 空格.html'
    old.write_text('<html><title>历史文章</title><main><h1>历史文章</h1><p>完整历史正文</p><details class="transcript"><summary>四、视频原始转录</summary>历史原稿</details></main></html>', encoding='utf8')
    (folder/'index.html').write_text('<a href="中文%20空格.html">历史文章</a>', encoding='utf8')
    assert refresh_existing(pub) == 1
    article = old.read_text(encoding='utf8')
    assert '完整历史正文' in article and '历史原稿' in article
    assert 'site.css' in article
    assert not (tmp_path/'data').exists()
    assert len(json.loads((pub.output_dir/'content-index.json').read_text(encoding='utf8'))['items']) == 1


def test_privacy_build_snapshot_is_read_only_and_does_not_escape_build(tmp_path):
    import sqlite3
    from kenradar.integrations.privacy import artifact_privacy_snapshot, private_artifact
    db = tmp_path/'policy.sqlite3'
    conn = sqlite3.connect(db)
    conn.executescript('CREATE TABLE content_item(id INTEGER,content_id TEXT,extra TEXT); CREATE TABLE content_note(content_item_id INTEGER,note_path TEXT);')
    conn.execute('INSERT INTO content_item VALUES (1,?,?)', ('7697294965654703400', '{"hermes_private":true}'))
    conn.commit()
    config = AppConfig({'app': {'database_url': 'sqlite:///' + db.as_posix()}}, tmp_path/'config/config.yaml')
    page = tmp_path/'copied_7697294965654703400.html'
    page.write_text('public-looking legacy body')
    before = db.read_bytes()
    with artifact_privacy_snapshot(config):
        assert private_artifact(page, config)
        assert private_artifact(page, config)
    assert db.read_bytes() == before
    conn.execute("UPDATE content_item SET extra='{}'")
    conn.commit()
    assert not private_artifact(page, config)
    conn.close()


def test_layout_upgrade_uses_existing_public_body_when_local_note_differs(tmp_path):
    pub = publisher(tmp_path)
    source = tmp_path/'data/notes/douyin/来源/文章.md'
    source.parent.mkdir(parents=True)
    source.write_text('# 旧本地笔记\n不应覆盖公开文章的旧版本正文', encoding='utf8')
    page = pub.html_path_for(source)
    page.parent.mkdir(parents=True)
    page.write_text('<title>已发布文章</title><main><h1>已发布文章</h1><p>需要保留的公开完整正文</p></main>', encoding='utf8')
    before = source.read_bytes()
    refresh_existing(pub)
    assert source.read_bytes() == before
    assert '需要保留的公开完整正文' in page.read_text(encoding='utf8')
    assert '不应覆盖公开文章的旧版本正文' not in page.read_text(encoding='utf8')


def test_large_exact_publication_scope_keeps_wildcards_and_invalidates_on_change(tmp_path):
    import pytest
    from kenradar.publishing.github_sync import GithubSyncManager, GithubSyncError
    allowed = [f'notes/douyin/a/{i}.html' for i in range(4400)] + ['assets/*.css', 'notes/a[[]b].html']
    config = AppConfig({'publishing': {'github_sync': {'allowed_paths': allowed}}}, tmp_path/'config/config.yaml')
    manager = GithubSyncManager(config)
    assert manager._scope_allows('notes/douyin/a/4399.html')
    assert manager._scope_allows('assets/site.css')
    assert manager._scope_allows('notes/a[b].html')
    assert not manager._scope_allows('config/config.yaml')
    allowed.remove('notes/douyin/a/4399.html')
    assert not manager._scope_allows('notes/douyin/a/4399.html')
    allowed.append('../escape.html')
    with pytest.raises(GithubSyncError, match='PUBLICATION_SCOPE'):
        manager._scope_allows('assets/site.css')


def test_sync_phases_reload_changed_private_policy(tmp_path):
    import sqlite3
    import pytest
    from kenradar.publishing.github_sync import GithubSyncManager, GithubSyncError, SyncCandidate
    db = tmp_path/'policy.sqlite3'
    page = tmp_path/'article.html'
    page.write_text('public-looking body')
    conn = sqlite3.connect(db)
    conn.executescript('CREATE TABLE content_item(id INTEGER,content_id TEXT,extra TEXT); CREATE TABLE content_note(content_item_id INTEGER,note_path TEXT);')
    conn.execute('INSERT INTO content_item VALUES (1,?,?)', ('private-identity', '{}'))
    conn.execute('INSERT INTO content_note VALUES (1,?)', (str(page),))
    conn.commit()
    config = AppConfig({'app': {'database_url': 'sqlite:///' + db.as_posix()}, 'publishing': {'github_sync': {'repo_dir': str(tmp_path)}}}, tmp_path/'config/config.yaml')
    manager = GithubSyncManager(config)
    manager._guard_sensitive_files(['article.html'], [SyncCandidate(page, 'html_docs')])
    conn.execute('UPDATE content_item SET extra=?', ('{"hermes_private":true}',))
    conn.commit()
    with pytest.raises(GithubSyncError, match='敏感文件'):
        manager._guard_sensitive_files(['article.html'], [SyncCandidate(page, 'html_docs')])
    conn.close()
