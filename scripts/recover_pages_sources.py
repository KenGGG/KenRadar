"""Inventory published source evidence; never infer active subscriptions from publication."""
from __future__ import annotations

import argparse
import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.update(value for key, value in attrs if key == 'href' and value and value.startswith('https://'))


def inventory(root: Path, base_url: str) -> dict:
    sources = []
    for directory in sorted((root / 'notes').glob('*/*')):
        if not directory.is_dir() or directory.is_symlink():
            continue
        platform, name = directory.parent.name, directory.name
        evidence, profiles, videos, external = [], set(), set(), set()
        for page in sorted(directory.glob('*.html')):
            if page.name == 'index.html' or page.is_symlink():
                continue
            data = page.read_bytes()
            links = Links()
            links.feed(data.decode('utf-8'))
            urls = sorted(links.urls)
            evidence.append({'path': page.relative_to(root).as_posix(), 'sha256': hashlib.sha256(data).hexdigest(), 'external_links': urls})
            for url in urls:
                parsed = urlsplit(url)
                host = (parsed.hostname or '').lower()
                parts = parsed.path.strip('/').split('/')
                if host in {'douyin.com', 'www.douyin.com'} and len(parts) == 2:
                    if parts[0] == 'user' and parts[1]:
                        profiles.add(unquote(parts[1]))
                    elif parts[0] == 'video' and parts[1].isdigit():
                        videos.add(parts[1])
                if host == 'www.xiaoyuzhoufm.com' and len(parts) == 2 and parts[0] == 'podcast':
                    external.add(url)
        if not evidence:
            continue
        ambiguous = name in {'待定', '单视频来源'} or len(profiles) > 1 or len(external) > 1
        key = next(iter(profiles)) if len(profiles) == 1 else ''
        feed = next(iter(external)) if len(external) == 1 else ''
        sources.append({'platform': platform, 'display_name': name, 'publication_count': len(evidence),
            'video_ids': sorted(videos), 'profile_ids': sorted(profiles), 'podcast_urls': sorted(external),
            'source_key': key or feed, 'source_url': f'https://www.douyin.com/user/{key}' if key else feed,
            'recovery_status': 'identity_available' if (key or feed) and not ambiguous else 'identity_required',
            'enabled': False, 'auto_publish': False, 'notify_mode': 'off',
            'evidence_url': base_url.rstrip('/') + '/' + directory.relative_to(root).as_posix() + '/index.html',
            'evidence': evidence})
    return {'format': 'kenradar-pages-source-recovery/1', 'historical_enabled_state': 'unknown', 'sources': sources}


def import_verified(db, manifest):
    """Add verified identities only, leaving existing subscriptions entirely unchanged."""
    imported, skipped = [], []
    for source in manifest['sources']:
        platform = 'xiaoyuzhou' if source['platform'] == 'podcast' else source['platform']
        if source['recovery_status'] != 'identity_available' or not source['source_key']:
            skipped.append(source['display_name'])
            continue
        if db.find_subscription(platform, source['source_key']):
            skipped.append(source['display_name'])
            continue
        imported.append(db.upsert_source_subscription(platform=platform, source_type='creator' if platform == 'douyin' else 'podcast',
            source_key=source['source_key'], display_name=source['display_name'], source_url=source['source_url'],
            enabled=False, auto_publish=False, notify_mode='off', review_required=True,
            extra={'recovery': 'github_pages', 'historical_enabled_state': 'unknown', 'evidence_url': source['evidence_url']}))
    return {'imported_ids': imported, 'skipped': skipped}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default='https://kenggg.github.io/KenRadar-pages')
    args = parser.parse_args()
    report = inventory(args.source.resolve(), args.base_url)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'sources.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = ['# GitHub Pages 来源恢复清单', '', '这是历史发布证据；启用状态未知。未导入生产或开启监控。', '', '| 平台 | 名称 | HTML 篇数 | 来源身份 |', '| --- | --- | ---: | --- |']
    for s in report['sources']:
        rows.append(f"| {s['platform']} | [{s['display_name'].replace('|', ' / ')}]({s['evidence_url']}) | {s['publication_count']} | {s['recovery_status']} |")
    (args.output / 'sources.md').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    print(json.dumps({'sources': len(report['sources']), 'identity_available': sum(s['recovery_status'] == 'identity_available' for s in report['sources'])}))


if __name__ == '__main__':
    main()
