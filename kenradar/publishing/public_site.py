"""Public reading UI. Only approved, existing HTML enters the public catalog."""
from __future__ import annotations

import html
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


def esc(value):
    return html.escape(str(value), quote=True)


def href(value):
    return '/'.join(quote(part, safe='-_.~') for part in str(value).split('/'))


def safe_url(value):
    text = str(value or '').strip()
    parsed = urlsplit(text)
    return text if parsed.scheme in ('http', 'https') and parsed.netloc and not parsed.username else ''


def platform_code(value):
    text = str(value or '').strip()
    return {'抖音': 'douyin', '小宇宙': 'xiaoyuzhou', 'podcast': 'xiaoyuzhou'}.get(text, text)


def page_title(text, path):
    """Prefer the reading title over legacy <title> values containing video IDs."""
    for pattern in (r'<h1\b[^>]*>(.*?)</h1>', r'<title\b[^>]*>(.*?)</title>'):
        match = re.search(pattern, text, re.S | re.I)
        if match:
            value = html.unescape(re.sub(r'<[^>]*>', '', match[1])).removesuffix('｜KenRadar').strip()
            if value and not re.fullmatch(r'\d{16,20}', value):
                return value
    # Existing descriptive filenames retain the original published heading.
    value = re.sub(r'^\d{4}-\d{2}-\d{2}_', '', Path(path).stem)
    value = re.sub(r'_\d{16,20}$', '', value)
    return value or Path(path).stem


def metadata(markdown, title, rel):
    from .static_site import _frontmatter_dict, _frontmatter_datetime, _douyin_source_url
    front = _frontmatter_dict(markdown)
    parts = Path(rel).parts
    topics = front.get('topics', [])
    topics = [str(t)[:80] for t in topics if isinstance(t, str)] if isinstance(topics, list) else []
    summary = re.search(r'^>\s*\[!summary\][^\n]*\n((?:>[^\n]*(?:\n|$))+)', markdown, re.M)
    summary = re.sub(r'^>\s?', '', summary.group(1), flags=re.M).strip() if summary else ''
    if not summary:
        overview = re.search(r'^##\s+一、内容综述\s*\n([\s\S]*?)(?=^##\s|\Z)', markdown, re.M)
        summary = overview.group(1).strip() if overview else ''
    summary = re.sub(r'[\[\]*`#]', '', summary)[:280]
    published = _frontmatter_datetime(markdown, 'published_at')
    return dict(title=title, relative_url=rel, platform=platform_code(front.get('platform') or (parts[1] if parts[0] == 'notes' and len(parts) > 2 else 'brief')),
                creator=str(front.get('creator') or (parts[2] if parts[0] == 'notes' and len(parts) > 3 else 'KenRadar')),
                external_content_id=str(front.get('video_id') or front.get('external_content_id') or ''),
                published_at=published.strftime('%Y-%m-%d %H:%M:%S') if published else '', topics=topics,
                summary=summary, source_url=safe_url(_douyin_source_url(front, Path(rel)) or front.get('source_url')))


def assets(publisher):
    target = publisher.output_dir / 'assets'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('site.css', 'site.js'):
        source = Path(__file__).with_name('assets') / name
        destination = target / name
        if not destination.exists() or destination.read_bytes() != source.read_bytes():
            shutil.copyfile(source, destination)


def shell(publisher, title, body, output, *, kind='article', side='', info=None):
    from .static_site import _relative_href
    assets(publisher)
    base = _relative_href(output, publisher.output_dir / 'index.html')
    prefix = base[:-len('index.html')]
    home, sources = href(base), href(prefix + 'sources.html')
    topics = href(prefix + 'index.html') + '#topics'
    navigation = f'<a href="{home}">总览</a><a href="{sources}">来源</a><a href="{topics}">研究主题</a>'
    data = json.dumps(info or {}, ensure_ascii=False).replace('<', '\\u003c').replace('&', '\\u0026')
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="description" content="{esc((info or {}).get('summary') or 'KenRadar · 可查找、可复核的研究阅读空间')}">
<title>{esc(title)}｜KenRadar</title><link rel="stylesheet" href="{href(prefix)}assets/site.css">
<script defer src="{href(prefix)}assets/site.js"></script></head>
<body data-kind="{kind}" data-root="{esc(prefix)}"><a class="skip" href="#main">跳到正文</a>
<header class="topbar"><a class="brand" href="{home}"><span class="radar">◎</span><span>KenRadar<small>信息有据 · 研究有序</small></span></a>
<nav aria-label="主导航">{navigation}</nav><div class="actions"><button data-search>⌕ 搜索 <kbd>Ctrl K</kbd></button><button data-theme aria-label="切换深浅色主题">◐</button></div></header>
<div class="layout"><aside class="sidebar"><p class="eyebrow">研究工作台</p>{navigation}<hr><p class="eyebrow">探索公开知识</p><p class="muted">从来源出发，让每一条信息<br>都有可回溯的依据。</p><a href="{sources}">全部来源 →</a><div id="sidebar-topics"></div></aside>
<main id="main" tabindex="-1">{body}</main><aside class="right">{side or '<div class="panel"><p class="eyebrow">关于 KENRADAR</p><h3>让信息成为知识</h3><p>汇集公开来源，保留原始语境，连接可复用的研究主题。</p><p class="muted">摘要与观点来自内容来源，不代表独立核验或投资建议。</p></div>'}</aside></div>
<footer>KenRadar · 公开研究笔记 <span>页面生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</span></footer>
<nav class="bottom" aria-label="移动导航"><a href="{home}">◎ 总览</a><a href="{sources}">▦ 来源</a><button data-search>⌕ 搜索</button></nav>
<dialog id="search-dialog" aria-label="全站搜索"><div class="search-head"><label for="global-query">搜索公开笔记</label><button data-close aria-label="关闭搜索">关闭</button></div><input id="global-query" type="search" placeholder="标题、创作者、研究主题…" autocomplete="off"><p class="muted">检索标题、来源、主题和摘要；原始转录不参与搜索。</p><div id="search-results" aria-live="polite"></div></dialog>
<script id="kr-metadata" type="application/json">{data}</script></body></html>'''


def article(publisher, markdown, title, source, output, body, links):
    if re.fullmatch(r'\d{16,20}', title.strip()):
        title = page_title(body, source)
    rel = output.relative_to(publisher.output_dir).as_posix()
    info = metadata(markdown, title, rel)
    # The body is already escaped by MarkdownIt(html=False).
    body = re.sub(r'^<h1>.*?</h1>\s*', '', body, count=1, flags=re.S)
    body = body.replace('<strong>一句话结论</strong>', '<strong>一句话结论 · 内容来源的摘要</strong>')
    toc = []
    def heading(match):
        anchor = 'section-' + str(len(toc) + 1)
        label = re.sub('<[^>]+>', '', match[2])
        toc.append(f'<a href="#{anchor}">{label}</a>')
        return f'<h{match[1]} id="{anchor}">{match[2]}</h{match[1]}>'
    body = re.sub(r'<h([23])>(.*?)</h\1>', heading, body, flags=re.S)
    # Keep the existing disclosure markup and give its wrapper an indexing boundary.
    body = body.replace('<details class="transcript">', '<div data-pagefind-ignore><details class="transcript">')
    if '<div data-pagefind-ignore><details class="transcript">' in body:
        body = body.replace('</details>', '</details></div>', 1)
    if '<details class="transcript">' in body:
        body = body.replace('<div data-pagefind-ignore>', '<div data-pagefind-ignore id="raw-transcript">', 1)
        raw_heading = '三、转录原文' if '## 三、转录原文' in markdown else '四、视频原始转录'
        toc.append(f'<a href="#raw-transcript">{raw_heading}</a>')
    contents = ''.join(toc)
    meta = f'{esc(info["creator"])} · {esc(info["platform"])} · 视频发布于 {esc(info["published_at"] or "未知时间")}'
    reading = f'''<div class="crumbs"><a href="{href('../' * (len(Path(rel).parts)-1))}index.html">总览</a> / 研究笔记</div>
<article data-pagefind-body><header class="article-head"><p class="eyebrow">RESEARCH NOTES · 来源笔记</p><h1>{esc(title)}</h1><p class="muted">{meta}</p>{links}<button class="focus-toggle" data-focus>专注阅读</button></header>
<details class="mobile-toc"><summary>本文目录</summary>{contents}</details><div class="article-copy">{body}</div></article><section id="related" data-topics="{esc(json.dumps(info['topics'], ensure_ascii=False))}" data-current="{esc(rel)}"></section>'''
    return shell(publisher, title, reading, output, side=f'<div class="toc"><p class="eyebrow">本文目录</p>{contents}<a href="#main">↑ 回到顶部</a></div>', info=info)


def collect(publisher):
    from kenradar.core.obsidian import summary_dir, brief_dir
    from kenradar.integrations.privacy import private_artifact
    from .static_site import _first_heading
    items, denied, denied_identities = {}, set(), set()
    for root in (summary_dir(publisher.config), brief_dir(publisher.config)):
        for note in root.glob('**/*.md'):
            page = publisher.html_path_for(note)
            rel = page.relative_to(publisher.output_dir).as_posix()
            if private_artifact(note, publisher.config):
                denied.add(rel)
                info = metadata(note.read_text(encoding='utf8', errors='replace'), '', rel)
                from .static_site import StaticSitePublisher
                identity = info['external_content_id'] or StaticSitePublisher._video_id_from_path(note)
                if identity:
                    denied_identities.add((info['platform'], identity))
                continue
            if not page.is_file() or private_artifact(page, publisher.config):
                continue
            text = note.read_text(encoding='utf8', errors='replace')
            from .static_site import _frontmatter_dict
            if _frontmatter_dict(text).get('status') in {'failed', 'degraded', 'pending', 'processing'}:
                denied.add(rel)
                continue
            title = _first_heading(text) or note.stem
            if re.fullmatch(r'\d{16,20}', title):
                title = page_title(page.read_text(encoding='utf8'), page)
            items[rel] = metadata(text, title, rel)
    with_markdown = set(items)
    for folder in ('notes', 'briefs'):
        for page in (publisher.output_dir / folder).glob('**/*.html'):
            rel = page.relative_to(publisher.output_dir).as_posix()
            if page.name == 'index.html' or rel in items or rel in denied or private_artifact(page, publisher.config):
                continue
            text = page.read_text(encoding='utf8', errors='replace')
            if re.search(r'hermes_private\s*["\x27]?\s*[:=]\s*(true|1)', text, re.I):
                continue
            item = metadata('', page_title(text, page), rel)
            # Historical HTML has no trustworthy frontmatter: do not infer dates or topics.
            items[rel] = item
    seen, unique = set(), []
    for item in sorted(items.values(), key=lambda item: (item['published_at'], item['relative_url'] in with_markdown, item['relative_url']), reverse=True):
        from .static_site import StaticSitePublisher
        item['external_content_id'] = item['external_content_id'] or StaticSitePublisher._video_id_from_path(Path(item['relative_url']))
        key = (item['platform'], item['external_content_id']) if item['external_content_id'] else item['relative_url']
        if key in denied_identities:
            continue
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def card(item, prefix=''):
    tags = ''.join(f'<span class="chip">{esc(t)}</span>' for t in item['topics'][:3])
    return f'''<a class="content-card" data-card data-date="{esc(item['published_at'])}" data-title="{esc(item['title'])}" data-topics="{esc(json.dumps(item['topics'], ensure_ascii=False))}" data-platform="{esc(item['platform'])}" href="{href(prefix + item['relative_url'])}"><div class="card-meta"><span class="pill">{esc(item['platform'])}</span><time>视频发布于 {esc(item['published_at'] or '未知时间')}</time></div><h3>{esc(item['title'])}</h3><p>{esc(item['summary'] or '查看来源笔记与完整内容 →')}</p><div class="card-foot"><span>{esc(item['creator'])}</span>{tags}</div></a>'''


def controls(items):
    topics = Counter(t for item in items for t in set(item['topics']))
    platforms = sorted({item['platform'] for item in items})
    return f'''<div class="filters" id="topics"><label>搜索当前列表<input type="search" id="feed-query" placeholder="标题、作者、主题…"></label><label>平台<select id="platform"><option value="">全部平台</option>{''.join(f'<option>{esc(p)}</option>' for p in platforms)}</select></label><label>排序<select id="sort"><option value="date">最新发布</option><option value="title">标题排序</option></select></label><button data-view>切换列表视图</button></div><div class="topic-row"><button data-topic="" aria-pressed="true">全部文章</button>{''.join(f'<button data-topic="{esc(t)}" aria-pressed="false">{esc(t)} <small>{n}</small></button>' for t,n in topics.most_common(12))}</div><p class="muted" id="feed-status" aria-live="polite">共 {len(items)} 篇公开内容</p>'''


def preserve_links(publisher, path, body, historical_markup=None):
    """Retain legacy navigation even if the original Markdown is absent."""
    if not path.exists() or not publisher.config.get('publishing.github_pages.preserve_historical_pages', False):
        return body
    import posixpath
    from .github_sync import GithubSyncManager
    rel = path.relative_to(publisher.output_dir).as_posix()
    known = GithubSyncManager._canonical_index_links(body, rel)
    extra = []
    class Links(HTMLParser):
        pending = None
        def handle_starttag(self, tag, attrs):
            if tag != 'a': return
            self.pending = None
            url = dict(attrs).get('href', '')
            parsed = urlsplit(url)
            if parsed.scheme or parsed.netloc or not parsed.path.endswith('.html'): return
            canonical = posixpath.normpath(posixpath.join(posixpath.dirname(rel), unquote(parsed.path)))
            if canonical in known or canonical.startswith('../'): return
            from kenradar.integrations.privacy import private_artifact
            if private_artifact(publisher.output_dir / canonical, publisher.config): return
            from kenradar.core.obsidian import obsidian_root
            if private_artifact((obsidian_root(publisher.config) / canonical).with_suffix('.md'), publisher.config): return
            known.add(canonical)
            extra.append(f'<a href="{esc(url)}">{esc(Path(unquote(parsed.path)).stem)}</a>')
            self.pending = len(extra) - 1
            self.label = []
            self.url = url
        def handle_data(self, data):
            if self.pending is not None:
                self.label.append(data)
        def handle_endtag(self, tag):
            if tag == 'a' and self.pending is not None:
                label = ''.join(self.label).strip()
                if label:
                    extra[self.pending] = f'<a href="{esc(self.url)}">{esc(label)}</a>'
                self.pending = None
    Links().feed(historical_markup if historical_markup is not None else path.read_text(encoding='utf8'))
    if extra:
        body += '<details class="legacy"><summary>历史公开入口</summary>' + ''.join(extra) + '</details>'
    return body


def refresh_existing(publisher):
    from kenradar.integrations.privacy import artifact_privacy_snapshot
    with artifact_privacy_snapshot(publisher.config):
        return _refresh_existing(publisher)


def _refresh_existing(publisher):
    """Restyle existing public pages only; never create or alter source Markdown."""
    from kenradar.core.obsidian import obsidian_root
    from kenradar.integrations.privacy import private_artifact
    count = 0
    for folder in ('notes', 'briefs'):
        for page in (publisher.output_dir / folder).glob('**/*.html'):
            if page.name == 'index.html' or private_artifact(page, publisher.config):
                continue
            rel = page.relative_to(publisher.output_dir)
            source = (obsidian_root(publisher.config) / rel).with_suffix('.md')
            if private_artifact(source, publisher.config):
                continue
            original = page.read_text(encoding='utf8')
            if '<body data-kind="article"' in original:
                continue
            if re.search(r'hermes_private\s*["\x27]?\s*[:=]\s*(true|1)', original, re.I):
                continue
            title = page_title(original, page)
            # A visual upgrade must not replace historical public prose with a
            # possibly older local Markdown version. Read Markdown for metadata only.
            main = re.search(r'<main\b[^>]*>(.*?)</main>', original, re.S)
            if not main: continue
            markdown = source.read_text(encoding='utf8') if source.is_file() else ''
            links = re.search(r'<nav class="page-links">.*?</nav>', original, re.S)
            rendered = article(publisher, markdown, title, source, page, main[1], links[0] if links else publisher._page_links(markdown, source, page))
            page.write_text(rendered, encoding='utf8')
            count += 1
    build_catalog(publisher)
    return count


def build_catalog(publisher, only_creator=None):
    from kenradar.integrations.privacy import artifact_privacy_snapshot
    with artifact_privacy_snapshot(publisher.config):
        return _build_catalog(publisher, only_creator)


def _build_catalog(publisher, only_creator=None):
    from .static_site import _relative_href
    publisher.output_dir.mkdir(parents=True, exist_ok=True)
    items = collect(publisher)
    assets(publisher)
    # Whitelisted fields only; no YAML, transcript, local paths or credentials.
    (publisher.output_dir / 'content-index.json').write_text(json.dumps(dict(schema_version=1, items=items), ensure_ascii=False), encoding='utf8')
    grouped = defaultdict(list)
    for item in items:
        parts = Path(item['relative_url']).parts
        if len(parts) == 4 and parts[0] == 'notes': grouped[(parts[1], parts[2])].append(item)
    creators = []
    for (platform, name), entries in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        rel = f'notes/{platform}/{name}/index.html'
        creators.append(f'<a class="creator" href="{href(rel)}"><span class="avatar">{esc(name[:1])}</span><span><strong>{esc(name)}</strong><small>{esc(platform)} · 共 {len(entries)} 篇</small></span><span>↗</span></a>')
        if only_creator and only_creator != (platform, name): continue
        path = publisher.output_dir / rel
        prefix = '../../../'
        intro = f'<div class="crumbs"><a href="../../../index.html">总览</a> / <a href="../../../sources.html">来源</a> / {esc(name)}</div><section class="profile"><span class="avatar">{esc(name[:1])}</span><div><p class="eyebrow">CREATOR / {esc(platform)}</p><h1>{esc(name)}</h1><p>已发布 {len(entries)} 篇内容笔记。</p><p class="muted">最近内容发布于 {esc(entries[0]["published_at"] or "未知时间")}</p></div></section><nav class="page-links"><a href="../index.html">返回博主目录</a><a href="../../../index.html">返回主索引</a></nav>'
        body = intro + controls(entries) + '<div class="feed creator-feed">' + ''.join(card(i, prefix) for i in entries) + '</div>'
        body = preserve_links(publisher, path, body)
        # Historical links whose HTML is missing remain reachable, but are not search results.
        legacy_count = len(re.findall(r'<a href=', body.split('<details class="legacy">')[-1])) if '<details class="legacy">' in body else 0
        if legacy_count:
            body = body.replace(f'已发布 {len(entries)} 篇', f'已发布 {len(entries)+legacy_count} 篇', 1)
        path.write_text(shell(publisher, name, body, path, kind='creator'), encoding='utf8')
    for platform in sorted({p for p, _ in grouped}):
        path = publisher.output_dir / f'notes/{platform}/index.html'
        body = f'<h1>{esc(platform)} 博主目录</h1><nav class="page-links"><a href="../../index.html">返回主索引</a></nav>'
        for (p, name), entries in sorted(grouped.items()):
            if p == platform:
                author = path.parent / name / 'index.html'
                count = len(entries)
                if author.exists():
                    match = re.search(r'已发布 (\d+) 篇', author.read_text(encoding='utf8'))
                    if match: count = int(match[1])
                body += f'<p><a href="{href(name)}/index.html">{esc(name)}</a> <code>共 {count} 篇</code></p>'
        path.write_text(shell(publisher, platform + ' 博主目录', preserve_links(publisher, path, body), path, kind='sources'), encoding='utf8')
    source_path = publisher.output_dir / 'sources.html'
    source_path.write_text(shell(publisher, '来源目录', '<p class="eyebrow">PUBLIC SOURCES</p><h1>探索你的研究来源</h1><p class="muted">按公开笔记数量排列，保留每个创作者的历史入口。</p><div class="creator-grid">' + ''.join(creators) + '</div>', source_path, kind='sources'), encoding='utf8')
    path = publisher.output_dir / 'index.html'
    topic_count = len({t for i in items for t in i['topics']})
    hero = f'<section class="hero"><p class="eyebrow">KENRADAR / RESEARCH INTELLIGENCE</p><h1>捕捉信息信号，<br>连接研究线索。</h1><p>从公开内容到结构化知识，让结论有来源，让研究可回溯。</p><a href="sources.html">探索全部来源 ↗</a><span class="orbit" aria-hidden="true">◎</span></section><div class="metrics"><div><strong>{len(items)}</strong><span>公开内容</span></div><div><strong>{len(grouped)}</strong><span>研究来源</span></div><div><strong>{topic_count}</strong><span>研究主题</span></div></div>'
    body = hero + '<div class="section-heading"><h2>最新内容</h2><span class="muted">发现 · 阅读 · 关联</span></div>' + controls(items) + '<div class="feed">' + ''.join(card(i) for i in items) + '</div>'
    # Keep a full, server-rendered directory for no-JS access and old navigation contracts.
    body += '<details class="directory"><summary>博主目录 · 全部来源</summary>' + ''.join(creators) + '</details>'
    body = preserve_links(publisher, path, body)
    side = '<p class="eyebrow">研究来源</p><h3>持续积累的知识</h3>' + ''.join(creators[:8]) + '<div class="panel"><h3>来源清楚，阅读有据</h3><p>内容摘要来自公开来源。请结合原文语境、样本条件与局限阅读。</p></div>'
    path.write_text(shell(publisher, '研究总览', body, path, kind='home', side=side), encoding='utf8')
    return path
