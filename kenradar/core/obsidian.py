from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.config import AppConfig
from kenradar.utils.text import sanitize_filename, truncate_text


NOTES_DIR = "notes"
BRIEF_DIR = "briefs"


def obsidian_root(config: AppConfig) -> Path:
    return config.resolve_path(config.get("output.obsidian_root", "./data"))


def note_dir(config: AppConfig, platform: str = "douyin", blogger_name: str = "未知博主") -> Path:
    return obsidian_root(config) / NOTES_DIR / sanitize_filename(platform or "unknown", "unknown") / sanitize_filename(blogger_name or "未知博主", "未知博主")


def summary_dir(config: AppConfig) -> Path:
    return obsidian_root(config) / NOTES_DIR


def brief_dir(config: AppConfig) -> Path:
    return obsidian_root(config) / BRIEF_DIR


def video_base_name(publish_time: str, blogger_name: str, title: str, aweme_id: str) -> str:
    date_part = _date_part(publish_time) or datetime.now().strftime("%Y-%m-%d")
    blogger_part = sanitize_filename(blogger_name or "未知博主", "未知博主")[:32].strip("_")
    title_part = sanitize_filename(title or "无标题", "无标题")[:64].strip("_")
    aweme_part = sanitize_filename(aweme_id or "unknown", "unknown")
    return f"{date_part}_{blogger_part}_{title_part}_{aweme_part}"


def transcript_filename(publish_time: str, blogger_name: str, title: str, aweme_id: str) -> str:
    return f"{video_base_name(publish_time, blogger_name, title, aweme_id)}.md"


def summary_filename(publish_time: str, blogger_name: str, title: str, aweme_id: str) -> str:
    return f"{video_base_name(publish_time, blogger_name, title, aweme_id)}_整理.md"


def note_filename(publish_time: str, brief_title: str, item_id: str) -> str:
    date_part = _date_part(publish_time) or datetime.now().strftime("%Y-%m-%d")
    title_part = sanitize_filename(brief_title or "未命名内容", "未命名内容")[:64].strip("_")
    item_part = sanitize_filename(item_id or "unknown", "unknown")
    return f"{date_part}_{title_part}_{item_part}.md"


def platform_label(platform: str) -> str:
    return {
        "douyin": "抖音",
        "bilibili": "B站",
        "xiaohongshu": "小红书",
        "youtube": "YouTube",
    }.get(platform, platform or "未知平台")


def wiki_link_name(path_or_name: str | Path) -> str:
    name = Path(path_or_name).name
    return name[:-3] if name.endswith(".md") else name


def yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_list(values: list[str], indent: int = 2) -> str:
    pad = " " * indent
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return " []"
    return "\n" + "\n".join(f"{pad}- {yaml_scalar(value)}" for value in cleaned)


def format_ts(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str) and not value.isdigit():
        return value
    try:
        return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(value)


def duration_text(seconds: Any) -> str:
    try:
        total = int(float(seconds or 0))
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        return "未知"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def segment_time(seconds: Any) -> str:
    try:
        total = float(seconds or 0)
    except (TypeError, ValueError):
        total = 0.0
    minutes, secs = divmod(int(total), 60)
    return f"{minutes:02d}:{secs:02d}"


def extract_keywords(*texts: str, limit: int = 6) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    combined = "\n".join(texts)
    for tag in re.findall(r"#([\w\u4e00-\u9fff-]+)", combined):
        if tag and tag not in seen:
            seen.add(tag)
            keywords.append(tag)
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", combined):
        if token in seen or token.isdigit():
            continue
        if len(token) > 24:
            continue
        seen.add(token)
        keywords.append(token)
        if len(keywords) >= limit:
            break
    return keywords[:limit]


def short_summary(text: str, limit: int = 500) -> str:
    cleaned = re.sub(r"\n{3,}", "\n\n", text.strip())
    return truncate_text(cleaned, limit)


def _date_part(value: str) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", value or "")
    return match.group(0) if match else ""
