from __future__ import annotations

import html
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
        if not self.enabled:
            return ""
        source = Path(markdown_path)
        if not source.exists() or source.suffix.lower() != ".md":
            return ""
        output_path = self.html_path_for(source)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_stale_video_pages(source, output_path)
        markdown = source.read_text(encoding="utf-8", errors="replace")
        page_title = title or _first_heading(markdown) or source.stem
        output_path.write_text(self._render_page(markdown, page_title, source), encoding="utf-8")
        if update_index:
            self.write_index()
        return self.public_url_for(source)

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

    def write_index(self) -> Path:
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        pages = []
        for root in (summary_dir(self.config), brief_dir(self.config)):
            for path in sorted(root.glob("**/*.md"), key=lambda item: item.stat().st_mtime, reverse=True)[:200]:
                if not path.is_file():
                    continue
                html_path = self.html_path_for(path)
                if not html_path.exists():
                    continue
                rel = html_path.relative_to(output_dir).as_posix()
                title = _first_heading(path.read_text(encoding="utf-8", errors="replace")) or path.stem
                pages.append((title, rel, datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")))
        source_indexes = self._write_source_indexes(self._collect_note_pages())
        lines = [
            "# KenRadar 发布索引",
            "",
            "这里收录 KenRadar 自动发布到 GitHub Pages 的内容笔记和简报。",
            "",
        ]
        if source_indexes:
            lines.extend(["## 博主目录", ""])
            lines.extend(
                f"- [{label}]({rel}) `共 {count} 篇`"
                for label, rel, count in source_indexes
            )
            lines.append("")
            lines.append("## 最新内容")
            lines.append("")
        if pages:
            for title, rel, updated_at in pages:
                lines.append(f"- [{title}]({rel}) `更新于 {updated_at}`")
        else:
            lines.append("暂无已发布页面。")
        batch_indexes = sorted(
            self.output_dir.glob("batch-notes/*/index.html"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        batch_lines = ["# 批量转化笔记", "", "这里按研究任务收录批量转换完成的笔记。", ""]
        if batch_indexes:
            for index_path in batch_indexes:
                rel = index_path.relative_to(self.output_dir / "batch-notes").as_posix()
                label = index_path.parent.name.replace("-", " ")
                batch_lines.append(f"- [{label}]({rel})")
        else:
            batch_lines.append("暂无已完成的批量转化任务。")
        batch_root = self.output_dir / "batch-notes"
        batch_root.mkdir(parents=True, exist_ok=True)
        (batch_root / "index.html").write_text(
            self._render_page("\n".join(batch_lines), "批量转化笔记", batch_root / "index.md"),
            encoding="utf-8",
        )
        lines.extend(["", "## 批量转化笔记", "", "- [查看批量转化笔记目录](batch-notes/index.html)"])
        index_html = self._render_page("\n".join(lines), "KenRadar 发布索引", output_dir / "index.md")
        path = output_dir / "index.html"
        path.write_text(index_html, encoding="utf-8")
        return path

    def _collect_note_pages(self) -> list[tuple[str, str, str]]:
        pages: list[tuple[str, str, str]] = []
        for path in sorted(summary_dir(self.config).glob("**/*.md"), key=lambda item: item.stat().st_mtime, reverse=True):
            if not path.is_file():
                continue
            html_path = self.html_path_for(path)
            if not html_path.exists():
                continue
            rel = html_path.relative_to(self.output_dir).as_posix()
            title = _first_heading(path.read_text(encoding="utf-8", errors="replace")) or path.stem
            pages.append((title, rel, datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")))
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
                lines.append(f"- [{title}]({filename}) `更新于 {updated_at}`")
            index_path = self.output_dir / index_rel
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(
                self._render_page("\n".join(lines), blogger, index_path.with_suffix(".md")),
                encoding="utf-8",
            )
            rel_text = index_rel.as_posix()
            label = f"{platform} / {blogger}"
            source_indexes.append((label, rel_text, len(entries)))
            platform_groups.setdefault(platform, []).append((blogger, rel_text, len(entries)))

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
            index_path.write_text(
                self._render_page("\n".join(lines), f"{platform} 博主目录", index_path.with_suffix(".md")),
                encoding="utf-8",
            )

        return sorted(source_indexes, key=lambda item: (-item[2], item[0]))

    def publish_research_collection(
        self,
        job_id: int,
        blogger_name: str,
        markdown_paths: list[str | Path],
    ) -> str:
        if not self.enabled:
            return ""
        folder_name = f"job-{int(job_id):04d}-{sanitize_filename(blogger_name or '未知博主', '未知博主')[:48]}"
        collection_dir = self.output_dir / "batch-notes" / folder_name
        collection_dir.mkdir(parents=True, exist_ok=True)
        entries: list[tuple[datetime | None, str, str, str]] = []
        for value in markdown_paths:
            source = Path(value)
            if not source.exists() or source.suffix.lower() != ".md":
                continue
            markdown = source.read_text(encoding="utf-8", errors="replace")
            canonical = self.html_path_for(source)
            if not canonical.exists():
                self.publish_markdown(source, update_index=False)
            if not canonical.exists():
                continue
            destination = collection_dir / canonical.name
            self._remove_stale_collection_pages(source, destination, collection_dir)
            shutil.copy2(canonical, destination)
            title = _first_heading(markdown) or source.stem
            published_at = _frontmatter_datetime(markdown, "published_at")
            published_label = published_at.strftime("%Y-%m-%d %H:%M") if published_at else "时间未知"
            entries.append((published_at, published_label, title, destination.name))

        entries.sort(
            key=lambda entry: (
                entry[0] is not None,
                entry[0] or datetime.min,
                entry[2],
            ),
            reverse=True,
        )

        lines = [
            f"# 批量转化笔记｜{blogger_name}",
            "",
            f"研究任务：`#{int(job_id)}`",
            "",
            f"已收录 {len(entries)} 篇完成转换的笔记。",
            "",
        ]
        lines.extend(
            f"- `{published_label}` [{title}]({filename})"
            for _, published_label, title, filename in entries
        )
        index_path = collection_dir / "index.html"
        index_path.write_text(
            self._render_page("\n".join(lines), f"批量转化笔记｜{blogger_name}", collection_dir / "index.md"),
            encoding="utf-8",
        )
        self.write_index()
        base_url = str(self.config.get("publishing.github_pages.public_base_url", "") or "").strip().rstrip("/")
        if not base_url or "${" in base_url:
            return ""
        return self._public_url_from_rel_path(base_url, index_path.relative_to(self.output_dir).as_posix())

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
        video_id = self._video_id_from_path(source)
        if not video_id:
            return
        for candidate in keep_path.parent.glob(f"*{video_id}*.html"):
            if candidate != keep_path and candidate.is_file():
                candidate.unlink()

    def _remove_stale_collection_pages(self, source: Path, keep_path: Path, collection_dir: Path) -> None:
        video_id = self._video_id_from_path(source)
        if not video_id:
            return
        for candidate in collection_dir.glob(f"*{video_id}*.html"):
            if candidate != keep_path and candidate.is_file():
                candidate.unlink()

    @property
    def output_dir(self) -> Path:
        return self.config.resolve_path(self.config.get("publishing.github_pages.output_dir", "./data/github_pages"))

    def _render_page(self, markdown: str, title: str, source: Path) -> str:
        body = _markdown_to_html(_preprocess_obsidian(markdown))
        body = _collapse_transcript_section(body)
        escaped_title = html.escape(title)
        source_name = html.escape(source.name)
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}｜KenRadar</title>
  <style>
    :root {{ color-scheme: light; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    body {{ margin: 0; background: #f7f7f5; color: #202124; }}
    header {{ border-bottom: 1px solid #e3e1dc; background: #fff; }}
    .bar, main {{ max-width: 920px; margin: 0 auto; padding: 20px; }}
    .brand {{ font-size: 13px; color: #5f6368; letter-spacing: .02em; }}
    h1, h2, h3 {{ line-height: 1.25; color: #111827; }}
    h1 {{ font-size: 30px; margin: 24px 0 16px; }}
    h2 {{ font-size: 22px; margin-top: 34px; border-top: 1px solid #e5e7eb; padding-top: 22px; }}
    h3 {{ font-size: 17px; margin-top: 24px; }}
    p, li {{ font-size: 16px; line-height: 1.8; }}
    a {{ color: #2563eb; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    blockquote {{ margin: 18px 0; padding: 12px 16px; border-left: 4px solid #2563eb; background: #eff6ff; color: #1f2937; }}
    code {{ background: #f1f5f9; padding: 2px 5px; border-radius: 4px; }}
    pre {{ overflow: auto; background: #111827; color: #f9fafb; padding: 16px; border-radius: 8px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 18px 0; background: #fff; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; vertical-align: top; }}
    .meta {{ color: #6b7280; font-size: 13px; }}
    .wikilink {{ display: inline-block; background: #eef2ff; color: #3730a3; padding: 0 6px; border-radius: 4px; }}
    details.transcript {{ margin-top: 34px; border-top: 1px solid #e5e7eb; padding-top: 18px; }}
    details.transcript summary {{ cursor: pointer; font-size: 18px; font-weight: 650; color: #374151; }}
    details.transcript[open] summary {{ margin-bottom: 18px; }}
  </style>
</head>
<body>
  <header><div class="bar"><div class="brand">KenRadar</div><div class="meta">{source_name} · 发布于 {generated_at}</div></div></header>
  <main>{body}</main>
</body>
</html>
"""


def _preprocess_obsidian(markdown: str) -> str:
    text = re.sub(r"^---\s*\n.*?\n---\s*\n", "", markdown, flags=re.DOTALL)
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: f'<span class="wikilink">{html.escape(m.group(2) or m.group(1))}</span>', text)
    text = re.sub(r"^>\s*\[!summary\]\s*$", "> **一句话结论**", text, flags=re.MULTILINE)
    return text


def _markdown_to_html(markdown: str) -> str:
    if MarkdownIt is not None:
        return MarkdownIt("commonmark", {"html": True}).enable("table").render(markdown)
    return "<pre>" + html.escape(markdown) + "</pre>"


def _collapse_transcript_section(body: str) -> str:
    pattern = re.compile(
        r"<h2>(?:四、视频原始转录|三、视频原稿)</h2>(.*)\Z",
        flags=re.DOTALL,
    )
    return pattern.sub(
        r'<details class="transcript"><summary>四、视频原始转录</summary>\1</details>',
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
