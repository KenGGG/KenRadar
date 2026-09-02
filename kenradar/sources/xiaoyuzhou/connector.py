"""Xiaoyuzhou connector wrapping the existing page/RSS parsers and audio downloader."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from kenradar.sources.base import ContentItem
from kenradar.sources.contracts import (
    ContentDescriptor,
    ContentPage,
    DownloadResult,
    SourceDescriptor,
    SourceParseChanged,
)
from kenradar.sources.xiaoyuzhou.feed_discovery import discover_feed_url

logger = logging.getLogger(__name__)


class XiaoyuzhouConnector:
    platform = "xiaoyuzhou"

    def __init__(self, config: Any):
        self.config = config

    # ── URL matching ──────────────────────────────────────────────────

    def match_url(self, url: str) -> bool:
        from urllib.parse import urlsplit

        host = (urlsplit(str(url or "")).netloc or "").lower()
        return host.endswith("xiaoyuzhoufm.com")

    # ── pure mapping (sync, no network) ───────────────────────────────

    def map_source(
        self,
        external_source_id: str,
        display_name: str,
        source_url: str,
        feed_url: str = "",
        raw_metadata: dict[str, Any] | None = None,
    ) -> SourceDescriptor:
        feed = str(feed_url or "").strip()
        return SourceDescriptor(
            platform=self.platform,
            external_source_id=str(external_source_id or "").strip(),
            display_name=str(display_name or "").strip() or "未知播客",
            source_url=str(source_url or "").strip(),
            feed_url=feed,
            # A discoverable public RSS feed is our only enumerable history;
            # without it we only promise the currently embedded page data.
            history_capability="full" if feed else "limited",
            raw_metadata=raw_metadata or {},
        )

    def map_content(self, item: ContentItem) -> ContentDescriptor:
        return ContentDescriptor(
            platform=self.platform,
            external_content_id=str(item.content_id),
            external_source_id=str(item.creator_id or ""),
            title=str(item.original_title or ""),
            published_at=item.published_at,
            media_type=str(item.media_type or "audio"),
            url=str(item.source_url or ""),
            description=str(item.description or ""),
            duration=item.duration,
            cover_url=str(item.cover_url or ""),
            media_url=str(item.media_url or ""),
            raw_metadata=dict(item.raw_metadata or {}),
        )

    # ── resolution ────────────────────────────────────────────────────

    async def resolve_source(self, url: str) -> SourceDescriptor:
        text = await asyncio.to_thread(self._fetch_text, url)
        feed_url = ""
        show_title = ""
        show_id = ""
        if self._looks_like_rss(url, text):
            from kenradar.sources.xiaoyuzhou.rss_client import parse_rss

            items = parse_rss(text, feed_url=url)
            if items:
                show_title = str(items[0].creator or "")
                show_id = str(items[0].creator_id or "")
            feed_url = url
        else:
            from kenradar.sources.xiaoyuzhou.page_parser import parse_page

            feed_url = discover_feed_url(text, page_url=url)
            try:
                items = parse_page(text, page_url=url)
                if items:
                    show_title = str(items[0].creator or "")
                    show_id = str(items[0].creator_id or "")
            except Exception:
                items = []
            if not items and not feed_url:
                raise SourceParseChanged("小宇宙页面未解析出节目或 RSS feed")
        if not show_id:
            from kenradar.sources.xiaoyuzhou.rss_client import _stable_id

            show_id = _stable_id(url)
        return self.map_source(
            external_source_id=show_id,
            display_name=show_title,
            source_url=url,
            feed_url=feed_url,
        )

    async def resolve_content(self, url: str) -> ContentDescriptor:
        text = await asyncio.to_thread(self._fetch_text, url)
        from kenradar.sources.xiaoyuzhou.page_parser import parse_page

        try:
            items = parse_page(text, page_url=url)
        except Exception as exc:
            raise SourceParseChanged(f"小宇宙单集页面解析失败: {exc}") from exc
        target_id = url.rstrip("/").rsplit("/", 1)[-1]
        for item in items:
            if str(item.content_id) == target_id:
                return self.map_content(item)
        if items:
            return self.map_content(items[0])
        raise SourceParseChanged("小宇宙页面未解析出单集数据")

    # ── listings ──────────────────────────────────────────────────────

    async def list_recent(
        self, source: SourceDescriptor, cursor: str | None = None
    ) -> ContentPage:
        return await self._list_feed(source, cursor)

    async def list_history(
        self, source: SourceDescriptor, cursor: str | None = None
    ) -> ContentPage:
        return await self._list_feed(source, cursor)

    async def _list_feed(self, source: SourceDescriptor, cursor: str | None) -> ContentPage:
        feed_url = str(source.feed_url or "").strip()
        if not feed_url:
            # No enumerable feed: only the currently embedded page data is public.
            return ContentPage(items=[], next_cursor=None, has_more=False, history_capability="limited")
        from kenradar.sources.xiaoyuzhou.rss_client import parse_rss

        text = await asyncio.to_thread(self._fetch_text, feed_url)
        try:
            items = parse_rss(text, feed_url=feed_url)
        except Exception as exc:
            raise SourceParseChanged(f"小宇宙 RSS 解析失败: {exc}") from exc
        if not items:
            raise SourceParseChanged("小宇宙 RSS 未解析出任何单集")
        descriptors = [self.map_content(item) for item in items]
        if cursor:
            seen_before = set(cursor.split(","))
            descriptors = [d for d in descriptors if d.external_content_id not in seen_before]
        return ContentPage(
            items=descriptors,
            next_cursor=None,
            has_more=False,
            history_capability="full",
        )

    # ── media ─────────────────────────────────────────────────────────

    async def download(
        self, content: ContentDescriptor, target_dir: Path
    ) -> DownloadResult:
        from kenradar.sources.base import ContentItem
        from kenradar.sources.xiaoyuzhou.audio_downloader import AudioDownloader

        legacy = ContentItem(
            platform=self.platform,
            creator="",
            creator_id=content.external_source_id,
            content_id=content.external_content_id,
            source_url=content.url,
            original_title=content.title,
            published_at=content.published_at,
            media_type=content.media_type or "audio",
            duration=content.duration,
            description=content.description,
            cover_url=content.cover_url,
            media_url=content.media_url,
            raw_metadata=content.raw_metadata,
        )
        downloader = AudioDownloader(self.config)
        try:
            path = await asyncio.to_thread(downloader.download, legacy)
        except Exception as exc:
            logger.warning("小宇宙连接器下载失败: content=%s error=%s", content.external_content_id, exc)
            return DownloadResult(success=False, error_code="DOWNLOAD_FAILED", error_message=str(exc))
        if path is None:
            return DownloadResult(
                success=False,
                error_code="DOWNLOAD_FAILED",
                error_message=str(legacy.failure_reason or "音频下载失败"),
            )
        return DownloadResult(success=True, path=path, media_url=content.media_url)

    # ── internals ─────────────────────────────────────────────────────

    def _fetch_text(self, url: str) -> str:
        import requests

        timeout = 30
        if self.config is not None:
            timeout = int(self.config.get("sources.xiaoyuzhou.request_timeout_seconds", 30) or 30)
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "KenRadar/0.1"})
        response.raise_for_status()
        return response.text

    @staticmethod
    def _looks_like_rss(url: str, text: str) -> bool:
        import re

        if re.search(r"<rss\b|<feed\b", text[:500], flags=re.IGNORECASE):
            return True
        return url.lower().endswith((".xml", ".rss"))
