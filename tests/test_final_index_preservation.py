from pathlib import Path
from kenradar.core.config import AppConfig
from kenradar.publishing.static_site import StaticSitePublisher


def test_preservation_applies_to_write_index_and_publish_many_briefs(tmp_path):
    data=tmp_path/'data';out=tmp_path/'site';out.mkdir()
    config=AppConfig({'app':{'data_dir':str(data)},'output':{'obsidian_root':str(data)},'publishing':{'github_pages':{'enabled':True,'output_dir':str(out),'preserve_historical_pages':True}}},tmp_path/'config/config.yaml')
    author=out/'notes/douyin/fixture';author.mkdir(parents=True)
    (out/'index.html').write_text('<main><a href="historical.html">Historical home</a></main>',encoding='utf8')
    (author/'index.html').write_text('<main><a href="missing-old.html">Historical author</a></main>',encoding='utf8')
    note=data/'notes/douyin/fixture/new.md';note.parent.mkdir(parents=True);note.write_text('# New fixture',encoding='utf8')
    brief=data/'briefs/new.md';brief.parent.mkdir(parents=True);brief.write_text('# New brief',encoding='utf8')
    pub=StaticSitePublisher(config);pub.publish_many([note,brief]);pub.write_index()
    assert 'historical.html' in (out/'index.html').read_text(encoding='utf8')
    assert 'missing-old.html' in (author/'index.html').read_text(encoding='utf8')
    assert 'new.html' in (author/'index.html').read_text(encoding='utf8')
    assert '共 2 篇' in (out/'notes/douyin/index.html').read_text(encoding='utf8')


def test_preserved_directory_updates_only_exact_author_count(tmp_path):
    out=tmp_path/'site';out.mkdir()
    config=AppConfig({'publishing':{'github_pages':{'output_dir':str(out),'preserve_historical_pages':True}}},tmp_path/'config/config.yaml')
    index=out/'index.html'
    index.write_text('<main><a href="notes/douyin/A/index.html">A</a> <code>共 1 篇</code><a href="notes/douyin/B/index.html">B</a> <code>共 7 篇</code></main>',encoding='utf8')
    StaticSitePublisher(config)._write_index_html(index,'<a href="notes/douyin/A/index.html">A</a> <code>共 2 篇</code>')
    text=index.read_text(encoding='utf8')
    assert '<code>共 2 篇</code>' in text and '<code>共 7 篇</code>' in text
