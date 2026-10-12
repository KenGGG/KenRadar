"""Explicitly requested one-off Quantgirl publication and delivery."""
from copy import deepcopy
from pathlib import Path
import json
import shutil
import sys
from urllib.parse import quote
from concurrent.futures import ThreadPoolExecutor
import requests
from kenradar.core.config import AppConfig, load_config
from kenradar.publishing import StaticSitePublisher, GithubSyncManager
from kenradar.publishing.github_sync import SyncCandidate
from kenradar.notification.feishu import _post_feishu_json_with_retry, _raise_for_feishu_error, build_research_feishu_card
from kenradar.storage import create_database
from scripts.verify_creator_recovery import main as verify

BASE = 'https://kenggg.github.io/KenRadar-pages'
UID = 'MS4wLjABAAAA_C2VXT1FT00QgTcH9v14uws4BQRaUXjKMP6JOD-UvWA'

def main():
    config = load_config('config/config.yaml')
    proof = config.resolve_path('data/test-migration/recovery-129')
    rel = Path('notes/douyin/量化Quantgirl')
    index_url = BASE + '/' + quote(rel.as_posix()) + '/index.html'
    if sys.argv[1] == 'prepare':
        verify()
        raw = deepcopy(config.raw)
        raw['publishing']['github_pages'].update(enabled=True, output_dir='data/test-migration/recovery-129/public-stage', public_base_url=BASE)
        raw['publishing']['github_sync']['repo_dir'] = 'data/github-pages'
        cfg = AppConfig(raw=raw, path=config.path)
        publisher = StaticSitePublisher(cfg)
        paths = sorted((config.data_dir / rel).glob('*.md'))
        assert len(paths) == 129
        publisher.publish_many(paths)
        staged = publisher.output_dir / rel
        assert len(list(staged.glob('*.html'))) == 130
        # Scan the full file text, including transcripts, before public upload.
        manager = GithubSyncManager(cfg)
        for path in staged.glob('*.html'):
            text = path.read_text(encoding='utf-8')
            assert not any(pattern.search(text) for pattern in manager.SECRET_TEXT_PATTERNS), path.name
        target = manager.repo_dir / rel
        target.mkdir(parents=True, exist_ok=True)
        for path in target.glob('*.html'):
            if not (staged / path.name).exists():
                path.unlink()  # only this author's stale generated pages; Git retains previous versions
        shutil.copytree(staged, target, dirs_exist_ok=True)
        homepage = manager.repo_dir / 'index.html'
        marker = '<!-- quantgirl-129-publication -->'
        html = homepage.read_text(encoding='utf-8')
        if marker not in html:
            html = html.replace('<main>', '<main>' + marker + '<p><a href="' + quote(rel.as_posix()) + '/index.html">量化Quantgirl：129 篇完整笔记</a></p>', 1)
            homepage.write_text(html, encoding='utf-8')
        manifest = {'index_url':index_url, 'urls':[publisher.public_url_for(p) for p in paths], 'count':129}
        (proof/'public-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'prepared':129,'index_url':index_url},ensure_ascii=True))
    elif sys.argv[1] == 'verify':
        manifest = json.loads((proof/'public-manifest.json').read_text(encoding='utf-8'))
        def check(url):
            r=requests.get(url,timeout=40)
            return {'url':url,'status':r.status_code,'ok':r.status_code==200 and '视频原始转录' in r.text}
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(check,manifest['urls']))
        r=requests.get(index_url,timeout=40)
        good=all(x['ok'] for x in results) and r.status_code==200 and '已发布 129 篇' in r.text
        (proof/'public-verification.json').write_text(json.dumps({'ok':good,'pages':results,'index_status':r.status_code},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'ok':good,'verified':sum(x['ok'] for x in results),'index_status':r.status_code}))
        if not good: raise SystemExit(1)
    elif sys.argv[1] == 'notify':
        assert json.loads((proof/'public-verification.json').read_text(encoding='utf-8'))['ok']
        receipt=proof/'publication-feishu-receipt.json'
        if receipt.exists(): raise SystemExit('Already delivered; refusing duplicate reminder')
        text='量化Quantgirl｜GitHub Pages 发布成功\n129 篇笔记已发布，129 个公开正文页面已逐一验证可访问。AI 整理成功129条，失败0条；其中3条无可辨识口播短片已如实说明。\n\n全部笔记：'+index_url+'\n博主抖音主页：https://www.douyin.com/user/'+UID
        payload=build_research_feishu_card('量化Quantgirl', {'fetched':129,'processed':129,'skipped':0,'failed':0,
            'creator_url':'https://www.douyin.com/user/'+UID,
            'note':'129 个公开正文页面已逐一验证可访问；其中 3 条无可辨识口播短片已如实说明。'}, index_url,
            title='量化Quantgirl｜笔记发布成功')
        response=_post_feishu_json_with_retry(config.feishu_webhook_url,payload)
        _raise_for_feishu_error(response)
        receipt.write_text(json.dumps({'ok':True,'http_status':response.status_code,'response':response.json(),'index_url':index_url},ensure_ascii=False,indent=2),encoding='utf-8')
        create_database(config).insert_push_log(None,'quantgirl-pages-129-20261012','success',message_type='card')
        print('Feishu publication result and creator homepage delivered successfully.')

if __name__ == '__main__': main()
