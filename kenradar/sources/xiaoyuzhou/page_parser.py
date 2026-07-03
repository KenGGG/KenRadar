from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from kenradar.sources.base import ContentItem


class XiaoyuzhouPageParseError(ValueError):
    pass


def parse_page(html: str, page_url: str = "") -> list[ContentItem]:
    payload = _extract_next_data(html)
    nodes = list(_walk_dicts(payload))
    podcast = _find_podcast(nodes)
    episodes = [node for node in nodes if _looks_like_episode(node)]
    if not episodes:
        raise XiaoyuzhouPageParseError("公开页面中未找到可解析的 episode 数据")

    show_title = str((podcast or {}).get("title") or (podcast or {}).get("name") or "未知播客")
    show_id = str((podcast or {}).get("pid") or (podcast or {}).get("id") or "")
    return [_episode_to_item(ep, show_title, show_id, page_url) for ep in episodes]


def _extract_next_data(html: str) -> dict[str, Any]:
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not match:
        raise XiaoyuzhouPageParseError("页面缺少 __NEXT_DATA__ 公开数据")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise XiaoyuzhouPageParseError(f"__NEXT_DATA__ JSON 解析失败: {exc}") from exc


def _walk_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_dicts(child))
    return found


def _find_podcast(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    for node in nodes:
        if (node.get("type") == "PODCAST" or node.get("podcastId") or node.get("pid")) and (node.get("title") or node.get("name")):
            return node
    return None


def _looks_like_episode(node: dict[str, Any]) -> bool:
    if not (node.get("eid") or node.get("episodeId") or node.get("id")):
        return False
    if not (node.get("title") or node.get("name")):
        return False
    return bool(
        node.get("audio")
        or node.get("audioUrl")
        or node.get("mediaUrl")
        or node.get("enclosure")
        or node.get("duration")
        or node.get("pubDate")
        or node.get("shownotes")
    )


def _episode_to_item(episode: dict[str, Any], show_title: str, show_id: str, page_url: str) -> ContentItem:
    episode_id = str(episode.get("eid") or episode.get("episodeId") or episode.get("id") or "")
    podcast = episode.get("podcast") if isinstance(episode.get("podcast"), dict) else {}
    creator = str(podcast.get("title") or podcast.get("name") or show_title or "未知播客")
    creator_id = str(podcast.get("pid") or podcast.get("id") or show_id or "")
    source_url = str(episode.get("url") or episode.get("link") or f"https://www.xiaoyuzhoufm.com/episode/{episode_id}")
    audio = episode.get("audio") if isinstance(episode.get("audio"), dict) else {}
    enclosure = episode.get("enclosure") if isinstance(episode.get("enclosure"), dict) else {}
    media = episode.get("media") if isinstance(episode.get("media"), dict) else {}
    media_source = media.get("source") if isinstance(media.get("source"), dict) else {}
    image = episode.get("image") if isinstance(episode.get("image"), dict) else {}
    audio_url = str(
        episode.get("audioUrl")
        or episode.get("mediaUrl")
        or audio.get("url")
        or enclosure.get("url")
        or media_source.get("url")
        or ""
    )
    return ContentItem(
        platform="xiaoyuzhou",
        creator=creator,
        creator_id=creator_id,
        content_id=episode_id,
        source_url=source_url or page_url,
        original_title=str(episode.get("title") or episode.get("name") or "未命名单集"),
        published_at=_parse_datetime(episode.get("pubDate") or episode.get("publishedAt") or episode.get("createdAt")),
        media_type="audio",
        duration=_duration(episode.get("duration") or audio.get("duration")),
        description=str(episode.get("description") or episode.get("shownotes") or ""),
        cover_url=str(episode.get("coverUrl") or episode.get("imageUrl") or image.get("url") or image.get("picUrl") or ""),
        media_url=audio_url,
        raw_metadata={
            "source": "page",
            "page_url": page_url,
            "show_id": creator_id,
            "episode_id": episode_id,
            "audio_url": audio_url,
            "episode": episode,
        },
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000
        return datetime.fromtimestamp(raw)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


def _duration(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
