from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

from kenradar.core.config import AppConfig
from kenradar.sources.base import ContentItem
from kenradar.sources.xiaoyuzhou.audio_downloader import AudioDownloader
from kenradar.sources.xiaoyuzhou.page_parser import parse_page
from kenradar.sources.xiaoyuzhou.rss_client import parse_rss


class XiaoyuzhouAdapter:
    def __init__(self, config: AppConfig):
        self.config = config
        self.downloader = AudioDownloader(config)

    def resolve_source(self, url_or_config: str) -> list[ContentItem]:
        value = str(url_or_config or "").strip()
        if not value:
            return []
        text = self._fetch_text(value)
        if self._looks_like_rss(value, text):
            return parse_rss(text, feed_url=value)
        return parse_page(text, page_url=value)

    def fetch_latest(self, source_config: dict[str, Any]) -> list[ContentItem]:
        if not bool(self.config.get("sources.xiaoyuzhou.enabled", False)):
            return []
        feed_url = str(source_config.get("feed_url") or source_config.get("url") or "").strip()
        if not feed_url:
            return []
        items = self.resolve_source(feed_url)
        limit = int(self.config.get("sources.xiaoyuzhou.max_episodes_per_check", 5) or 5)
        return items[: max(0, limit)]

    def download_media(self, item: ContentItem) -> Path | None:
        return self.downloader.download(item)

    def _fetch_text(self, url: str) -> str:
        timeout = int(self.config.get("sources.xiaoyuzhou.request_timeout_seconds", 30) or 30)
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "KenRadar/0.1"})
        response.raise_for_status()
        return response.text

    @staticmethod
    def _looks_like_rss(url: str, text: str) -> bool:
        if re.search(r"<rss\b|<feed\b", text[:500], flags=re.IGNORECASE):
            return True
        return url.lower().endswith((".xml", ".rss"))
