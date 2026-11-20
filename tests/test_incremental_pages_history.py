from pathlib import Path
from kenradar.core.config import AppConfig
from kenradar.publishing.static_site import StaticSitePublisher


def test_incremental_publication_preserves_html_and_all_author_hrefs(tmp_path):
    data=tmp_path/'data'; out=tmp_path/'site'
    config=AppConfig({'app':{'data_dir':str(data)},'output':{'obsidian_root':str(data)},
        'publishing':{'github_pages':{'enabled':True,'output_dir':str(out),'preserve_historical_pages':True}}},tmp_path/'config/config.yaml')
    author=out/'notes/douyin/中产财富说'; author.mkdir(parents=True)
    old=author/'旧标题_7604693889647217929.html'; old.write_text('<title>旧标题</title><p>historical bytes</p>',encoding='utf8')
    (author/'index.html').write_text('<a href="%E6%97%A7%E6%A0%87%E9%A2%98_7604693889647217929.html">旧标题</a>',encoding='utf8')
    note=data/'notes/douyin/中产财富说/新标题_7604693889647217929.md'; note.parent.mkdir(parents=True)
    note.write_text('# 新标题',encoding='utf8')
    publisher=StaticSitePublisher(config); publisher.publish_markdown(note)
    assert old.read_text(encoding='utf8') == '<title>旧标题</title><p>historical bytes</p>'
    index=(author/'index.html').read_text(encoding='utf8')
    from urllib.parse import unquote
    assert '旧标题_7604693889647217929.html' in unquote(index)
    assert '新标题_7604693889647217929.html' in unquote(index)
    assert '已发布 2 篇' in index
