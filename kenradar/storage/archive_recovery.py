"""Explicit, insert-only recovery of historical notes; never schedules processing.

The caller prepares candidates and supplies the configured SQLite path. Existing
content (including failures/private rows) and active tasks always win. Original
Markdown bytes are retained; HTML-derived copies must carry their provenance.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import yaml


def metadata(text):
    if text.startswith("---"):
        value = yaml.safe_load(text.split("---", 2)[1])
        if not isinstance(value, dict):
            raise ValueError("Invalid Markdown frontmatter")
        return value
    return {}


def identity(platform, external_id, path="", source_url=""):
    platform = {"抖音": "douyin", "小宇宙": "xiaoyuzhou", "podcast": "xiaoyuzhou"}.get(platform, platform)
    external_id = str(external_id or "")
    if not external_id:
        pattern = r"(?<!\d)\d{16,20}(?!\d)" if platform == "douyin" else r"[0-9a-f]{24}"
        found = re.findall(pattern, Path(path).stem or source_url)
        if not found:
            found = re.findall(pattern, source_url)
        external_id = found[-1] if found else ""
        if not external_id:
            # Early podcast exports were placed in douyin folders and omitted
            # the ID from the Pages catalog. Recover their stable episode suffix.
            suffix = re.search(r"_([a-z0-9]{20,32})$", Path(path).stem)
            external_id = suffix[1] if suffix else ""
    if platform == "douyin" and (re.fullmatch(r"[0-9a-f]{24}", external_id)
                                  or re.fullmatch(r"ck[a-z0-9]{22,30}", external_id)):
        platform = "xiaoyuzhou"
    return platform, external_id


@dataclass
class Node:
    tag: str = "root"
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"br", "hr", "img", "meta", "link", "input", "source", "wbr", "area", "embed"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def html_article_to_markdown(html, source_url):
    parser = ArticleParser()
    parser.feed(html)

    def find(node):
        if isinstance(node, str):
            return None
        if "article-copy" in node.attrs.get("class", "").split():
            return node
        for child in node.children:
            match = find(child)
            if match:
                return match
        return None

    article = find(parser.root)
    if article is None:
        raise ValueError("No recognized article body; refusing navigation-only recovery")

    def render(node):
        if isinstance(node, str):
            return node
        tag = node.tag
        if tag in {"script", "style", "button", "nav"}:
            return ""
        if tag == "table":
            rows = []

            def collect(current):
                if isinstance(current, str):
                    return
                if current.tag == "tr":
                    cells = []
                    for cell in current.children:
                        if isinstance(cell, Node) and cell.tag in {"td", "th"}:
                            value = "".join(render(child) for child in cell.children)
                            cells.append(re.sub(r"\s+", " ", value).strip().replace("|", "\\|"))
                    if cells:
                        rows.append(cells)
                else:
                    for child in current.children:
                        collect(child)

            collect(node)
            if not rows:
                return ""
            width = max(map(len, rows))
            lines = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
            lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
            return "\n\n" + "\n".join(lines) + "\n\n"
        text = "".join(render(child) for child in node.children)
        if re.fullmatch(r"h[1-6]", tag):
            return "\n\n" + "#" * int(tag[1]) + " " + text.strip() + "\n\n"
        if tag in {"p", "div", "details", "section"}:
            return "\n\n" + text.strip() + "\n\n"
        if tag == "summary":
            return "\n\n## " + text.strip() + "\n\n"
        if tag == "blockquote":
            return "\n\n" + "\n".join("> " + line for line in text.strip().splitlines()) + "\n\n"
        if tag == "li":
            return "\n- " + text.strip().replace("\n", "\n  ") + "\n"
        if tag == "br":
            return "\n"
        if tag == "hr":
            return "\n\n---\n\n"
        if tag in {"strong", "b"}:
            return "**" + text + "**"
        if tag in {"em", "i"}:
            return "*" + text + "*"
        if tag == "pre":
            return "\n\n```\n" + text.strip().strip("`") + "\n```\n\n"
        if tag == "code":
            return "`" + text + "`"
        if tag in {"td", "th"}:
            return text.strip() + " | "
        if tag == "tr":
            return "\n| " + text + "\n"
        if tag == "a":
            href = urljoin(source_url, node.attrs.get("href", ""))
            if urlparse(href).scheme in {"https", "http"}:
                return "[" + text + "](" + href + ")"
        if tag == "img":
            return node.attrs.get("alt", "")
        return text

    body = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", render(article)).strip()
    if not body:
        raise ValueError("Empty article body")
    return body + "\n"


def protected(conn, platform, external_id):
    if conn.execute("SELECT 1 FROM content_item c JOIN platform p ON p.id=c.platform_id "
                    "WHERE p.code=? AND c.content_id=?", (platform, external_id)).fetchone():
        return "existing_content"
    # Do not race with queued/running/retrying/paused work, even before content exists.
    for (payload,) in conn.execute("SELECT payload_json FROM task_run WHERE status NOT IN "
                                   "('success','failed','cancelled','skipped')"):
        data = json.loads(payload or "{}")
        if str(data.get("external_content_id") or "") == external_id or external_id in str(data.get("url") or ""):
            return "active_task"
    return ""


def import_note(conn, destination_root, candidate):
    """One short, insert-only transaction; a crash may leave a reusable orphan file."""
    platform, external_id = identity(candidate["platform"], candidate["external_id"])
    if platform not in {"douyin", "xiaoyuzhou"} or not external_id:
        raise ValueError("Missing/unsupported content identity")
    raw = Path(candidate["source_file"]).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != candidate["sha256"]:
        raise ValueError("Recovery source hash changed")
    text = raw.decode("utf-8-sig")
    meta = metadata(text)
    if meta.get("hermes_private") is True or "hermes-private" in str(candidate["source_file"]).lower():
        return "private"
    root = Path(destination_root).resolve()
    destination = (root / candidate["relative_path"]).resolve()
    if not destination.is_relative_to(root) or destination.suffix.lower() != ".md":
        raise ValueError("Unsafe recovery destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("BEGIN IMMEDIATE")
    try:
        reason = protected(conn, platform, external_id)
        if reason:
            conn.rollback()
            return reason
        if destination.exists() and destination.read_bytes() != raw:
            conn.rollback()
            return "existing_file"
        if not destination.exists():
            with destination.open("xb") as stream:
                stream.write(raw)
        conn.execute("INSERT OR IGNORE INTO platform(code,display_name) VALUES (?,?)", (platform, platform))
        pid = conn.execute("SELECT id FROM platform WHERE code=?", (platform,)).fetchone()[0]
        creator = str(meta.get("creator") or candidate.get("creator") or "历史恢复")
        uid = str(meta.get("creator_id") or "archive:" + hashlib.sha256(creator.encode()).hexdigest()[:20])
        if not meta.get("creator_id"):
            matches = conn.execute("SELECT platform_uid FROM creator WHERE platform_id=? AND nickname=?",
                                   (pid, creator)).fetchall()
            if len(matches) == 1:
                uid = matches[0][0]
        conn.execute("INSERT OR IGNORE INTO creator(platform_id,platform_uid,nickname,enabled) VALUES (?,?,?,0)",
                     (pid, uid, creator))
        creator_id = conn.execute("SELECT id FROM creator WHERE platform_id=? AND platform_uid=?", (pid, uid)).fetchone()[0]
        provenance = {"archive_recovery": candidate["provenance"], "recovery_sha256": digest,
                      "recovery_kind": candidate["kind"]}
        title = str(meta.get("title") or candidate.get("title") or destination.stem)
        source_url = str(meta.get("source_url") or candidate.get("source_url") or "")
        conn.execute("INSERT INTO content_item(platform_id,content_id,creator_id,content_type,title,source_url,"
                     "publish_time,download_status,status,discovery_source,extra) VALUES (?,?,?,?,?,?,?,'archived','completed','archive_recovery',?)",
                     (pid, external_id, creator_id, "podcast" if platform == "xiaoyuzhou" else "video", title,
                      source_url, str(meta.get("published_at") or candidate.get("published_at") or "") or None,
                      json.dumps(provenance, ensure_ascii=False)))
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        result = {**provenance, "topics": meta.get("topics") or candidate.get("topics") or [],
                  "value_score": meta.get("value_score"), "summary": candidate.get("summary") or "历史文章恢复"}
        # This is a restored historical result, not a new model execution.
        conn.execute("INSERT INTO ai_analysis(content_item_id,analysis_type,result_json,result_text,model,provider,status) "
                     "VALUES (?,'summary',?,?,?,'archive-recovery','success')",
                     (cid, json.dumps(result, ensure_ascii=False, default=str), text,
                      str(meta.get("ai_model") or "historical-unknown")))
        conn.execute("INSERT INTO content_note(content_item_id,note_type,note_path,title,content_sha256) VALUES (?,'content',?,?,?)",
                     (cid, str(destination), title, digest))
        # Only original Markdown with an explicitly labelled raw section supplies ASR.
        match = re.search(r"^#{1,6}\s+(?:四、)?(?:视频)?原始转录\s*\n(.*)\Z", text, re.M | re.S)
        if candidate["kind"] == "git-original" and match and match[1].strip():
            conn.execute("INSERT INTO transcript(content_item_id,aweme_id,text_content,model,status,source_type) "
                         "VALUES (?,?,?,?,'success','archive-original')",
                         (cid, external_id, match[1].strip(), str(meta.get("transcript_model") or "historical-unknown")))
        conn.commit()
        return "imported"
    except BaseException:
        conn.rollback()
        raise
