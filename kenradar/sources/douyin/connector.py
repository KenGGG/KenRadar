"""Douyin connector — a thin wrapper over the vendored douyin client.

Platform fields (sec_uid, aweme_id, pinned posts, cookies, pagination details)
stay inside this module. The generic layer only sees the descriptors produced
by ``map_source`` / ``map_content``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.sources.contracts import (
    ContentDescriptor,
    ContentPage,
    DownloadResult,
    SourceDescriptor,
)
from kenradar.vendor.douyin_downloader.api_client import DouyinAPIClient

logger = logging.getLogger(__name__)

_PAGE_SIZE = 20


class DouyinConnector:
    platform = "douyin"

    def __init__(self, config: Any):
        self.config = config

    # ── URL matching ──────────────────────────────────────────────────

    def match_url(self, url: str) -> bool:
        from urllib.parse import urlsplit

        host = (urlsplit(str(url or "")).netloc or "").lower()
        return host.endswith("douyin.com") or host.endswith("iesdouyin.com")

    # ── pure mapping (sync, no network) ───────────────────────────────

    def map_source(self, external_source_id: str, display_name: str) -> SourceDescriptor:
        sec_uid = str(external_source_id or "").strip()
        return SourceDescriptor(
            platform=self.platform,
            external_source_id=sec_uid,
            display_name=str(display_name or "").strip() or sec_uid,
            source_url=f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "",
            history_capability="full" if sec_uid else "unknown",
        )

    def map_content(self, raw_aweme: dict[str, Any]) -> ContentDescriptor | None:
        if not isinstance(raw_aweme, dict) or self._is_gallery(raw_aweme):
            return None
        aweme_id = str(raw_aweme.get("aweme_id") or "").strip()
        if not aweme_id:
            return None
        author = raw_aweme.get("author") if isinstance(raw_aweme.get("author"), dict) else {}
        sec_uid = str(author.get("sec_uid") or raw_aweme.get("sec_uid") or "").strip()
        published = self._published_at(raw_aweme.get("create_time"))
        return ContentDescriptor(
            platform=self.platform,
            external_content_id=aweme_id,
            external_source_id=sec_uid,
            title=str(raw_aweme.get("desc") or "").strip() or aweme_id,
            published_at=published,
            media_type="video",
            url=f"https://www.douyin.com/video/{aweme_id}",
            description=str(raw_aweme.get("desc") or ""),
            duration=self._duration(raw_aweme),
            cover_url=self._cover_url(raw_aweme),
            media_url=self._media_url(raw_aweme),
            raw_metadata=raw_aweme,
        )

    # ── resolution ────────────────────────────────────────────────────

    async def resolve_source(self, url: str) -> SourceDescriptor:
        from kenradar.core.source_resolver import resolve_douyin_source

        if self.config is not None and self.config.get('integrations.hermes_v1.safe_network', False):
            from kenradar.core.source_resolver import extract_sec_uid
            from kenradar.integrations.guarded_douyin import GuardedDouyinAPIClient
            from kenradar.integrations.hermes_v1 import ContractError, source_platform
            from kenradar.integrations.safe_network import safe_get, policy_from_config
            from kenradar.integrations.guarded_douyin import validate_profile_url
            validate_profile_url(url)
            sec_uid = extract_sec_uid(url)
            if not sec_uid:
                def canonical():
                    with safe_get(url, source=validate_profile_url, policy=policy_from_config(self.config),
                                  max_bytes=4 * 1024 * 1024, total_timeout=30) as response:
                        return response.url
                url = await asyncio.to_thread(canonical)
                sec_uid = extract_sec_uid(url)
            if not sec_uid:
                raise ContractError('SOURCE_UNAVAILABLE', 'No Douyin source identifier')
            async with GuardedDouyinAPIClient(self.config) as client:
                page = await client.get_user_post(sec_uid, count=1)
            items = page.get('items') or []
            author = items[0].get('author', {}) if items and isinstance(items[0], dict) else {}
            author = author if isinstance(author, dict) else {}
            source = self.map_source(sec_uid, author.get('nickname') or sec_uid)
            avatar = author.get('avatar_thumb') or {}
            urls = avatar.get('url_list') if isinstance(avatar, dict) else []
            from dataclasses import replace
            return replace(source, avatar_url=str(urls[0]) if urls else '')
        # resolve_douyin_source is a sync facade that runs its own event loop,
        # so keep it off the worker loop.
        resolved = await asyncio.to_thread(resolve_douyin_source, self.config, url)
        return SourceDescriptor(
            platform=self.platform,
            external_source_id=resolved.sec_uid,
            display_name=resolved.name,
            source_url=resolved.url,
            avatar_url=resolved.avatar_url,
            history_capability="full",
            raw_metadata={"sec_uid": resolved.sec_uid},
        )

    async def resolve_content(self, url: str) -> ContentDescriptor:
        from kenradar.core.source_resolver import resolve_douyin_video

        if self.config is not None and self.config.get('integrations.hermes_v1.safe_network', False):
            from kenradar.core.source_resolver import extract_aweme_id
            from kenradar.integrations.guarded_douyin import GuardedDouyinAPIClient
            from kenradar.integrations.hermes_v1 import ContractError, source_platform
            from kenradar.integrations.safe_network import safe_get, policy_from_config
            from urllib.parse import urlsplit
            if urlsplit(url).scheme != 'https':
                raise ContractError('UNSAFE_SOURCE_URL', 'Private Douyin content requires HTTPS')
            source_platform(url)
            aweme_id = extract_aweme_id(url)
            if not aweme_id:
                def canonical():
                    with safe_get(url, source=True, policy=policy_from_config(self.config),
                                  max_bytes=4 * 1024 * 1024, total_timeout=30) as response:
                        return response.url
                url = await asyncio.to_thread(canonical)
                aweme_id = extract_aweme_id(url)
            if not aweme_id:
                raise ContractError('SOURCE_UNAVAILABLE', 'No Douyin content identifier')
            async with GuardedDouyinAPIClient(self.config) as client:
                detail = await client.get_video_detail(aweme_id)
            if not detail or str(detail.get('aweme_id') or '') != aweme_id:
                raise ContractError('SOURCE_UNAVAILABLE', 'Douyin metadata unavailable; browser fallback disabled')
            descriptor = self.map_content(detail)
            if descriptor is None:
                raise ContractError('SOURCE_UNAVAILABLE', 'Douyin video metadata unavailable')
            return descriptor
        resolved = await resolve_douyin_video(self.config, url)
        descriptor = self.map_content(resolved.aweme)
        if descriptor is None:
            raise ValueError(f"无法映射抖音作品: {resolved.aweme_id}")
        return descriptor

    # ── listings ──────────────────────────────────────────────────────

    async def list_recent(
        self, source: SourceDescriptor, cursor: str | None = None
    ) -> ContentPage:
        return await self._list_user_post(source, cursor, count=_PAGE_SIZE)

    async def list_history(
        self, source: SourceDescriptor, cursor: str | None = None
    ) -> ContentPage:
        return await self._list_user_post(source, cursor, count=_PAGE_SIZE)

    async def _list_user_post(
        self, source: SourceDescriptor, cursor: str | None, count: int
    ) -> ContentPage:
        max_cursor = int(cursor) if cursor else 0
        cookies = self.config.cookies if self.config is not None else {}
        if self.config is not None and self.config.get('integrations.hermes_v1.safe_network', False):
            from kenradar.integrations.guarded_douyin import GuardedDouyinAPIClient
            client = GuardedDouyinAPIClient(self.config)
        else:
            client = DouyinAPIClient(cookies)
        async with client as api_client:
            response = await api_client.get_user_post(
                source.external_source_id, max_cursor=max_cursor, count=count
            )
        items = response.get("items") or response.get("aweme_list") or []
        if not isinstance(items, list):
            items = []
        descriptors = [
            descriptor
            for descriptor in (self.map_content(item) for item in items if isinstance(item, dict))
            if descriptor is not None
        ]
        has_more = bool(response.get("has_more", False))
        next_cursor = str(response.get("max_cursor") or "") or None
        return ContentPage(
            items=descriptors,
            next_cursor=next_cursor,
            has_more=has_more,
            history_capability="full",
        )

    # ── media ─────────────────────────────────────────────────────────

    async def download(
        self, content: ContentDescriptor, target_dir: Path
    ) -> DownloadResult:
        from kenradar.core.downloader import Downloader

        raw_aweme = content.raw_metadata if isinstance(content.raw_metadata, dict) else {}
        aweme = dict(raw_aweme)
        aweme.setdefault("aweme_id", content.external_content_id)
        if not aweme.get("desc"):
            aweme["desc"] = content.title

        class _NoopDatabase:
            def update_aweme_download(self, *args: Any, **kwargs: Any) -> None:
                return None

        downloader = Downloader(self.config, _NoopDatabase())
        if self.config.get('integrations.hermes_v1.safe_network', False):
            from kenradar.integrations.safe_network import safe_get
            from kenradar.integrations.hermes_v1 import ContractError
            from kenradar.integrations.guarded_douyin import GuardedDouyinAPIClient
            try:
                async with GuardedDouyinAPIClient(self.config) as client:
                    detail = await client.get_video_detail(content.external_content_id)
                    if detail and str(detail.get('aweme_id') or '') != content.external_content_id:
                        raise ContractError('SOURCE_IDENTITY_MISMATCH', 'Download metadata does not match the requested item')
                    detail = detail or aweme
                    if str(detail.get('aweme_id') or '') != content.external_content_id:
                        raise ContractError('SOURCE_IDENTITY_MISMATCH', 'Fallback metadata does not match the requested item')
                    media = downloader._build_video_download(detail, client)
                    if not media:
                        raise ContractError('DOWNLOAD_FAILED', 'No media address available')
                    url, headers = media
                    path = downloader._build_save_path(detail, content.external_source_id or 'douyin')
                    def download():
                        temp = path.with_suffix(path.suffix + '.tmp')
                        try:
                            with safe_get(url, headers=headers, policy=client.policy) as response:
                                with temp.open('wb') as output:
                                    for chunk in response.iter_content():
                                        output.write(chunk)
                            if not temp.stat().st_size:
                                raise ContractError('DOWNLOAD_FAILED', 'Empty media')
                            temp.replace(path)
                        finally:
                            temp.unlink(missing_ok=True)
                    await asyncio.to_thread(download)
                return DownloadResult(success=True, path=path)
            except ContractError as exc:
                return DownloadResult(success=False, error_code=exc.code, error_message=str(exc))
        try:
            path = await downloader.download_aweme(aweme, content.external_source_id or "douyin")
        except Exception as exc:
            logger.warning("抖音连接器下载失败: content=%s error=%s", content.external_content_id, exc)
            return DownloadResult(
                success=False,
                error_code=getattr(exc, 'error_code', 'DOWNLOAD_FAILED'),
                error_message=str(exc),
            )
        return DownloadResult(success=True, path=path)

    # ── platform internals ────────────────────────────────────────────

    @staticmethod
    def _is_gallery(aweme: dict[str, Any]) -> bool:
        aweme_type = aweme.get("aweme_type")
        return bool(
            aweme.get("image_post_info")
            or aweme.get("images")
            or aweme.get("image_list")
            or aweme_type in {2, 68, 150}
        )

    @staticmethod
    def _published_at(create_time: Any) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(float(create_time or 0)))
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _duration(aweme: dict[str, Any]) -> int | None:
        video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
        raw = aweme.get("duration") or video.get("duration")
        try:
            value = int(float(raw or 0))
        except (TypeError, ValueError):
            return None
        return value or None

    @staticmethod
    def _cover_url(aweme: dict[str, Any]) -> str:
        for key in ("cover", "video_cover"):
            cover = aweme.get(key) if isinstance(aweme.get(key), dict) else {}
            for sub in ("origin_cover", "dynamic_cover", "cover"):
                layer = cover.get(sub) if isinstance(cover.get(sub), dict) else {}
                urls = layer.get("url_list")
                if isinstance(urls, list) and urls:
                    return str(urls[0] or "")
        return ""

    @staticmethod
    def _media_url(aweme: dict[str, Any]) -> str:
        video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
        play = video.get("play_addr") if isinstance(video.get("play_addr"), dict) else {}
        urls = play.get("url_list")
        if isinstance(urls, list) and urls:
            return str(urls[0] or "")
        return ""
