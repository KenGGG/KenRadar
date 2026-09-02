"""Discover a public RSS feed for a xiaoyuzhou podcast.

Discovery only uses public page metadata: the HTML ``<link rel="alternate">``
feed hint, an explicit feed URL supplied by the caller, or feed links embedded
in the page. No login tokens and no private endpoints.
"""

from __future__ import annotations

import re
from typing import Any

_FEED_LINK_PATTERN = re.compile(
    r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]+href=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_FEED_LINK_PATTERN_REVERSED = re.compile(
    r"<link[^>]+href=[\"']([^\"']+)[\"'][^>]+type=[\"']application/(?:rss|atom)\+xml[\"']",
    re.IGNORECASE,
)


def discover_feed_url(html: str, page_url: str = "", explicit_url: str = "") -> str:
    """Return the best public feed URL for a podcast page, or an empty string."""
    explicit = str(explicit_url or "").strip()
    if explicit:
        return explicit
    for pattern in (_FEED_LINK_PATTERN, _FEED_LINK_PATTERN_REVERSED):
        match = pattern.search(html or "")
        if match:
            return match.group(1).strip()
    return ""


def looks_like_podcast_page(url: str) -> bool:
    return "/podcast/" in str(url or "")


def episode_page_url(episode_id: str) -> str:
    return f"https://www.xiaoyuzhoufm.com/episode/{episode_id}"


def podcast_page_url(podcast_id: str) -> str:
    return f"https://www.xiaoyuzhoufm.com/podcast/{podcast_id}"


def stable_content_id(raw_metadata: dict[str, Any], source_url: str, media_url: str) -> str:
    """Prefer GUID, then canonical URL, then a hash of the media URL."""
    guid = str((raw_metadata or {}).get("guid") or "").strip()
    if guid:
        return guid
    canonical = str(source_url or "").strip()
    if canonical:
        return canonical
    import hashlib

    media = str(media_url or "").strip()
    if media:
        return hashlib.sha256(media.encode("utf-8")).hexdigest()[:32]
    return ""
