from __future__ import annotations

import html
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from urllib.parse import quote, urlsplit, urlunsplit

from kenradar.core.config import AppConfig
from kenradar.core.obsidian import brief_dir, obsidian_root, summary_dir
from kenradar.utils.text import sanitize_filename

try:
    from markdown_it import MarkdownIt
except Exception:  # pragma: no cover - dependency is declared, fallback keeps runtime tolerant.
    MarkdownIt = None  # type: ignore[assignment]


class StaticSitePublisher:
    def __init__(self, config: AppConfig):
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("publishing.github_pages.enabled", False))

    def publish_markdown(self, markdown_path: str | Path, title: str = "", *, update_index: bool = True) -> str:
        from kenradar.integrations.privacy import private_artifact
        if private_artifact(markdown_path, self.config):
            raise ValueError('PRIVATE_CONTENT: publication forbidden')
        if not self.enabled:
            return ""
        source = Path(markdown_path)
        if not source.exists() or source.suffix.lower() != ".md":
            return ""
        output_path = self.html_path_for(source)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_stale_video_pages(source, output_path)
        markdown = source.read_text(encoding="utf-8", errors="replace")
        normalized_markdown = _normalize_video_note_section_order(markdown)
        if normalized_markdown != markdown:
            source.write_text(normalized_markdown, encoding="utf-8")
            markdown = normalized_markdown
        page_title = str(_frontmatter_dict(markdown).get("title") or title or _first_heading(markdown) or source.stem)
        output_path.write_text(self._render_page(markdown, page_title, source, output_path), encoding="utf-8")
        if update_index:
            if self.config.get('publishing.github_pages.preserve_historical_pages', False):
                self._write_incremental_indexes(output_path)
            else:
                self.write_index()
        return self.public_url_for(source)

    def _write_incremental_indexes(self, output_path: Path) -> None:
        """Only refresh this author and its directory; never rebuild unrelated author indexes."""
        from .public_site import build_catalog
        parts = output_path.relative_to(self.output_dir).parts
        build_catalog(self, (parts[1], parts[2]) if len(parts) == 4 and parts[0] == 'notes' else None)
        return

    def publish_many(self, paths: list[str | Path]) -> dict[str, str]:
        urls: dict[str, str] = {}
        for path in paths:
            url = self.publish_markdown(path, update_index=False)
            html_path = self.html_path_for(path)
            if url or html_path.exists():
                urls[str(path)] = url or str(html_path)
        if urls:
            self.write_index()
        return urls

    def _write_index_html(self, path: Path, rendered: str) -> None:
        """Merge new navigation into the original markup, never drop old hrefs."""
        if self.config.get('publishing.github_pages.preserve_historical_pages', False) and path.exists():
            from kenradar.publishing.github_sync import GithubSyncManager
            from html.parser import HTMLParser
            from urllib.parse import unquote, urlsplit
            import posixpath
            rel = path.relative_to(self.output_dir).as_posix()
            original = path.read_text(encoding='utf8')
            counts = {}
            count_pattern = r'(<a\s+href="([^"]+)"[^>]*>.*?</a>\s*<code>共\s*)(\d+)(\s*篇</code>)'
            for match in re.finditer(count_pattern, rendered):
                counts[unquote(html.unescape(match.group(2)))] = match.group(3)
            original = re.sub(count_pattern, lambda match: match.group(1) + counts.get(unquote(html.unescape(match.group(2))), match.group(3)) + match.group(4), original)
            known = GithubSyncManager._canonical_index_links(original, rel)
            additions = []
            class Anchors(HTMLParser):
                def handle_starttag(inner, tag, attrs):
                    if tag != 'a':
                        return
                    href = dict(attrs).get('href', '')
                    target = urlsplit(href)
                    if target.scheme or target.netloc or not target.path.endswith('.html'):
                        return
                    canonical = posixpath.normpath(posixpath.join(posixpath.dirname(rel), unquote(target.path)))
                    if canonical not in known:
                        known.add(canonical)
                        label = Path(unquote(target.path)).stem
                        additions.append(f'<p><a href="{html.escape(href, quote=True)}">{html.escape(label)}</a></p>')
            Anchors().feed(rendered)
            addition = '\n'.join(additions)
            rendered = original.replace('</main>', addition + '</main>') if '</main>' in original else original + addition
            if len(Path(rel).parts) == 4 and Path(rel).parts[0] == 'notes':
                count = len([p for p in known if posixpath.dirname(p) == posixpath.dirname(rel) and not p.endswith('/index.html')])
                if re.search(r'已发布\s*\d+\s*篇内容笔记', rendered):
                    rendered = re.sub(r'已发布\s*\d+\s*篇内容笔记', f'已发布 {count} 篇内容笔记', rendered)
                else:
                    rendered += f'<p>已发布 {count} 篇内容笔记。</p>'
        path.write_text(rendered, encoding='utf8')

    def write_index(self) -> Path:
        from .public_site import build_catalog
        self._clear_batch_notes_output()
        return build_catalog(self)

    def _collect_note_pages(self) -> list[tuple[str, str, str]]:
        from kenradar.integrations.privacy import private_artifact
        pages: list[tuple[str, str, str]] = []
        for path in sorted(summary_dir(self.config).glob("**/*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file() or private_artifact(path, self.config):
                continue
            html_path = self.html_path_for(path)
            if not html_path.exists():
                continue
            rel = html_path.relative_to(self.output_dir).as_posix()
            markdown = path.read_text(encoding="utf-8", errors="replace")
            title = _first_heading(markdown) or path.stem
            published = _frontmatter_datetime(markdown, "published_at")
            pages.append((title, rel, published.strftime("%Y-%m-%d %H:%M:%S") if published else ""))
        pages.sort(key=lambda item: (item[2], item[1]), reverse=True)
        return pages

    def _write_source_indexes(self, pages: list[tuple[str, str, str]]) -> list[tuple[str, str, int]]:
        grouped: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
        for title, rel, updated_at in pages:
            parts = Path(rel).parts
            if len(parts) < 4 or parts[0] != "notes":
                continue
            platform, blogger = parts[1], parts[2]
            grouped.setdefault((platform, blogger), []).append((title, rel, updated_at))

        source_indexes: list[tuple[str, str, int]] = []
        platform_groups: dict[str, list[tuple[str, str, int]]] = {}
        for (platform, blogger), entries in sorted(grouped.items(), key=lambda item: item[0][1]):
            entries.sort(key=lambda item: item[2], reverse=True)
            index_rel = Path("notes") / platform / blogger / "index.html"
            lines = [
                f"# {blogger}",
                "",
                f"平台：`{platform}`",
                "",
                f"已发布 {len(entries)} 篇内容笔记。",
                "",
            ]
            for title, rel, updated_at in entries:
                filename = Path(rel).name
                lines.append(f"- [{title}]({filename}) `视频发布于 {updated_at or '未知时间'}`")
            index_path = self.output_dir / index_rel
            index_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_index_html(index_path,
                self._render_page("\n".join(lines), blogger, index_path.with_suffix(".md"), index_path))
            rel_text = index_rel.as_posix()
            label = f"{platform} / {blogger}"
            count = len(entries)
            if self.config.get('publishing.github_pages.preserve_historical_pages', False):
                match = re.search(r'已发布\s*(\d+)\s*篇内容笔记', index_path.read_text(encoding='utf8'))
                if match:
                    count = int(match.group(1))
            source_indexes.append((label, rel_text, count))
            platform_groups.setdefault(platform, []).append((blogger, rel_text, count))

        # Keep directories belonging to earlier deployments, whose Markdown
        # is not necessarily present in this new local installation.
        known = set(grouped)
        for existing in (self.output_dir / "notes").glob("*/*/index.html"):
            platform, blogger = existing.parent.parent.name, existing.parent.name
            if (platform, blogger) in known:
                continue
            match = re.search(r"已发布\s*(\d+)\s*篇", existing.read_text(encoding="utf-8"))
            count = int(match.group(1)) if match else len(list(existing.parent.glob("*.html"))) - 1
            rel = existing.relative_to(self.output_dir).as_posix()
            source_indexes.append((f"{platform} / {blogger}", rel, count))
            platform_groups.setdefault(platform, []).append((blogger, rel, count))
        for platform, entries in platform_groups.items():
            entries.sort(key=lambda item: (-item[2], item[0]))
            index_rel = Path("notes") / platform / "index.html"
            lines = [
                f"# {platform} 博主目录",
                "",
                f"已发布 {len(entries)} 个博主目录。",
                "",
            ]
            for blogger, rel, count in entries:
                lines.append(f"- [{blogger}]({Path(rel).parent.name}/index.html) `共 {count} 篇`")
            index_path = self.output_dir / index_rel
            index_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_index_html(index_path,
                self._render_page("\n".join(lines), f"{platform} 博主目录", index_path.with_suffix(".md"), index_path))

        return sorted(source_indexes, key=lambda item: (-item[2], item[0]))

    def publish_research_collection(
        self,
        job_id: int,
        blogger_name: str,
        markdown_paths: list[str | Path],
    ) -> str:
        del job_id, blogger_name, markdown_paths
        if not self.enabled:
            return ""
        self._clear_batch_notes_output()
        self.write_index()
        return ""

    def public_url_for(self, markdown_path: str | Path) -> str:
        if not self.enabled:
            return ""
        base_url = str(self.config.get("publishing.github_pages.public_base_url", "") or "").strip().rstrip("/")
        if not base_url or "${" in base_url:
            return ""
        html_path = self.html_path_for(markdown_path)
        rel = html_path.relative_to(self.output_dir).as_posix()
        return self._public_url_from_rel_path(base_url, rel)

    def html_path_for(self, markdown_path: str | Path) -> Path:
        source = Path(markdown_path).resolve()
        root = obsidian_root(self.config).resolve()
        try:
            rel = source.relative_to(root)
        except ValueError:
            rel = Path(sanitize_filename(source.stem, "page") + ".md")
        return (self.output_dir / rel).with_suffix(".html")

    @staticmethod
    def _video_id_from_path(path: Path) -> str:
        matches = re.findall(r"(?<!\d)(\d{16,20})(?!\d)", path.stem)
        return matches[-1] if matches else ""

    @staticmethod
    def _public_url_from_rel_path(base_url: str, rel_path: str) -> str:
        parsed = urlsplit(base_url)
        normalized_path = "/".join(quote(part, safe="-_.~") for part in rel_path.split("/"))
        prefix = parsed.path.rstrip("/")
        if prefix:
            normalized_path = f"{prefix}/{normalized_path}" if normalized_path else prefix
        else:
            normalized_path = f"/{normalized_path}"
        return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, parsed.query, parsed.fragment))

    def _remove_stale_video_pages(self, source: Path, keep_path: Path) -> None:
        if self.config.get('publishing.github_pages.preserve_historical_pages', False):
            return
        video_id = self._video_id_from_path(source)
        if not video_id:
            return
        for candidate in keep_path.parent.glob(f"*{video_id}*.html"):
            if candidate != keep_path and candidate.is_file():
                candidate.unlink()

    @property
    def output_dir(self) -> Path:
        return self.config.resolve_path(self.config.get("publishing.github_pages.output_dir", "./data/github_pages"))

    def _clear_batch_notes_output(self) -> None:
        if self.config.get("publishing.github_pages.preserve_existing_collections", False):
            return
        batch_root = self.output_dir / "batch-notes"
        if batch_root.exists():
            shutil.rmtree(batch_root)

    def _render_page(self, markdown: str, title: str, source: Path, output_path: Path | None = None) -> str:
        markdown = _normalize_video_note_section_order(markdown)
        body = _markdown_to_html(_preprocess_obsidian(markdown))
        body = _postprocess_wikilinks(body)
        body = _collapse_transcript_section(body)
        page_links = self._page_links(markdown, source, output_path)
        from .public_site import article
        return article(self, markdown, title, source, output_path or self.html_path_for(source), body, page_links)

    def _page_links(self, markdown: str, source: Path, output_path: Path | None) -> str:
        if output_path is None:
            return ""
        links: list[tuple[str, str, bool]] = []
        frontmatter = _frontmatter_dict(markdown)
        video_url = _douyin_source_url(frontmatter, source)
        if video_url:
            links.append(("抖音源视频", video_url, True))
        else:
            from .public_site import safe_url
            source_url = safe_url(frontmatter.get('source_url'))
            if source_url:
                links.append(("查看原始来源", source_url, True))

        output_path = output_path.resolve()
        root_index = self.output_dir.resolve() / "index.html"
        blogger_index = self._blogger_index_for_note(source)
        if blogger_index and output_path != blogger_index.resolve():
            links.append(("返回博主主页", _relative_href(output_path, blogger_index), False))

        try:
            rel_parts = output_path.relative_to(self.output_dir.resolve()).parts
        except ValueError:
            rel_parts = ()
        if len(rel_parts) == 4 and rel_parts[0] == "notes" and rel_parts[3] == "index.html":
            links.append(("返回博主目录", _relative_href(output_path, self.output_dir / "notes" / rel_parts[1] / "index.html"), False))
            links.append(("返回主索引", _relative_href(output_path, root_index), False))
        elif len(rel_parts) == 3 and rel_parts[0] == "notes" and rel_parts[2] == "index.html":
            links.append(("返回主索引", _relative_href(output_path, root_index), False))
        elif rel_parts and output_path != root_index:
            links.append(("返回发布首页", _relative_href(output_path, root_index), False))

        if not links:
            return ""
        rendered = []
        seen: set[tuple[str, str]] = set()
        for label, href, external in links:
            key = (label, href)
            if key in seen:
                continue
            seen.add(key)
            target = ' target="_blank" rel="noopener noreferrer"' if external else ""
            rendered.append(f'<a href="{html.escape(href, quote=True)}"{target}>{html.escape(label)}</a>')
        return '<nav class="page-links">' + "".join(rendered) + "</nav>"

    def _blogger_index_for_note(self, source: Path) -> Path | None:
        html_path = self.html_path_for(source)
        try:
            rel_parts = html_path.relative_to(self.output_dir).parts
        except ValueError:
            return None
        if len(rel_parts) < 4 or rel_parts[0] != "notes" or rel_parts[-1] == "index.html":
            return None
        return self.output_dir / "notes" / rel_parts[1] / rel_parts[2] / "index.html"


def _frontmatter_dict(markdown: str) -> dict[str, Any]:
    match = re.match(r"^---\s*\n(?P<front>.*?)\n---(?:\s*\n|$)", markdown, flags=re.DOTALL)
    if not match:
        return {}
    try:
        frontmatter = yaml.safe_load(match.group("front")) or {}
    except yaml.YAMLError:
        return {}
    return frontmatter if isinstance(frontmatter, dict) else {}


def _douyin_source_url(frontmatter: dict[str, Any], source: Path) -> str:
    platform = str(frontmatter.get("platform") or "").strip().lower()
    video_id = str(frontmatter.get("video_id") or "").strip() or StaticSitePublisher._video_id_from_path(source)
    source_url = str(frontmatter.get("source_url") or "").strip()
    source_parts = {part.lower() for part in source.parts}
    is_douyin = platform == "douyin" or "douyin" in source_parts or "douyin.com" in source_url
    if is_douyin and video_id:
        return f"https://www.douyin.com/video/{video_id}"
    if "douyin.com" in source_url:
        return source_url
    return ""


def _relative_href(from_path: Path, to_path: Path) -> str:
    rel = os.path.relpath(Path(to_path).resolve(), Path(from_path).resolve().parent)
    rel = Path(rel).as_posix()
    return rel or "."


def _preprocess_obsidian(markdown: str) -> str:
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", markdown, flags=re.DOTALL)
    # Wikilink -> span conversion is deferred to _postprocess_wikilinks so that
    # user/AI content is rendered with html=False (no raw HTML execution).
    text = re.sub(r"^>\s*\[!summary\]\s*$", "> **一句话结论**", text, flags=re.MULTILINE)
    return text


def _postprocess_wikilinks(body: str) -> str:
    """Convert [[wikilinks]] in already-rendered, HTML-escaped body into styled spans.

    Runs after markdown rendering (html=False), so the injected span is the only
    raw HTML added and user/AI content has already been escaped by markdown-it.
    """
    return re.sub(
        r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
        lambda m: f'<span class="wikilink">{html.escape(m.group(2) or m.group(1))}</span>',
        body,
    )


def _normalize_video_note_section_order(markdown: str) -> str:
    """Keep video notes in the canonical reading order before publishing."""
    if "## 二、知识关联" not in markdown or "## 三、分段原文" not in markdown:
        return markdown
    headings = {
        name: re.search(rf"^##\s+{re.escape(name)}\s*$", markdown, flags=re.MULTILINE)
        for name in ("二、知识关联", "三、分段原文", "四、视频原始转录")
    }
    if not all(headings.values()):
        return markdown
    knowledge_heading = headings["二、知识关联"]
    transcript_heading = headings["三、分段原文"]
    raw_transcript_heading = headings["四、视频原始转录"]
    assert knowledge_heading is not None
    assert transcript_heading is not None
    assert raw_transcript_heading is not None
    if not (knowledge_heading.start() < transcript_heading.start() < raw_transcript_heading.start()):
        return markdown

    before = markdown[: knowledge_heading.start()].rstrip()
    knowledge = markdown[knowledge_heading.end() : transcript_heading.start()].strip()
    transcript = markdown[transcript_heading.end() : raw_transcript_heading.start()].strip()
    after = markdown[raw_transcript_heading.start() :].lstrip()
    return (
        f"{before}\n\n"
        "## 二、分段原文\n\n"
        f"{transcript}\n\n"
        "## 三、知识关联\n\n"
        f"{knowledge}\n\n"
        f"{after}"
    )


def _markdown_to_html(markdown: str) -> str:
    # html=False ensures any raw HTML in notes/transcripts is escaped, not executed.
    # Wikilink spans are injected *after* rendering via _postprocess_wikilinks.
    if MarkdownIt is not None:
        return MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    return "<pre>" + html.escape(markdown) + "</pre>"


def _collapse_transcript_section(body: str) -> str:
    pattern = re.compile(
        r"<h2>(三、转录原文|四、视频原始转录|三、视频原稿|原始转录)</h2>(.*)\Z",
        flags=re.DOTALL,
    )
    return pattern.sub(
        r'<details class="transcript"><summary>\1</summary>\2</details>',
        body,
    )


def _first_heading(markdown: str) -> str:
    for line in markdown.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _frontmatter_datetime(markdown: str, key: str) -> datetime | None:
    match = re.match(r"^---\s*\n(?P<front>.*?)\n---(?:\s*\n|$)", markdown, flags=re.DOTALL)
    if not match:
        return None
    try:
        frontmatter = yaml.safe_load(match.group("front")) or {}
    except yaml.YAMLError:
        return None
    value = frontmatter.get(key)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)
