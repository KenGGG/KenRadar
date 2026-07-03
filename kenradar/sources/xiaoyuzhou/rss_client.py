from __future__ import annotations

import email.utils
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

from kenradar.sources.base import ContentItem

ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


class RssParseError(ValueError):
    pass


def parse_rss(xml_text: str, feed_url: str = "") -> list[ContentItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise RssParseError(f"RSS XML 解析失败: {exc}") from exc

    channel = root.find("channel")
    if channel is None:
        raise RssParseError("RSS 缺少 channel 节点")

    show_title = _text(channel, "title") or "未知播客"
    show_id = _stable_id(feed_url or show_title)
    channel_image = _itunes_image(channel) or _rss_image(channel)
    items: list[ContentItem] = []
    for entry in channel.findall("item"):
        title = _text(entry, "title") or "未命名单集"
        source_url = _text(entry, "link") or feed_url
        guid = _text(entry, "guid") or source_url or title
        enclosure = entry.find("enclosure")
        audio_url = enclosure.get("url") if enclosure is not None else ""
        duration = _duration_seconds(_text(entry, f"{ITUNES_NS}duration"))
        image = _itunes_image(entry) or channel_image
        items.append(
            ContentItem(
                platform="xiaoyuzhou",
                creator=show_title,
                creator_id=show_id,
                content_id=str(guid),
                source_url=source_url,
                original_title=title,
                published_at=_parse_date(_text(entry, "pubDate")),
                media_type="audio",
                duration=duration,
                description=_text(entry, "description"),
                cover_url=image,
                media_url=audio_url,
                raw_metadata={
                    "source": "rss",
                    "feed_url": feed_url,
                    "show_title": show_title,
                    "show_id": show_id,
                    "guid": guid,
                    "audio_url": audio_url,
                },
            )
        )
    return items


def _text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    return (child.text or "").strip() if child is not None and child.text else ""


def _itunes_image(node: ET.Element) -> str:
    image = node.find(f"{ITUNES_NS}image")
    return (image.get("href") or "").strip() if image is not None else ""


def _rss_image(node: ET.Element) -> str:
    image = node.find("image")
    if image is None:
        return ""
    return _text(image, "url")


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    parsed = email.utils.parsedate_to_datetime(value)
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _duration_seconds(value: str) -> int | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    parts = value.split(":")
    if not all(re.fullmatch(r"\d+", part or "") for part in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _stable_id(value: str) -> str:
    cleaned = re.sub(r"\W+", "-", value.strip()).strip("-").lower()
    return cleaned[:128] or "xiaoyuzhou"
