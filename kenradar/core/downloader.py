from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from kenradar.core.config import AppConfig
from kenradar.utils.text import sanitize_filename, truncate_filename_bytes
from kenradar.vendor.douyin_downloader.api_client import DouyinAPIClient
from kenradar.vendor.douyin_downloader.file_manager import FileManager

logger = logging.getLogger(__name__)


class Downloader:
    def __init__(self, config: AppConfig, database: Any):
        self.config = config
        self.database = database
        self.download_dir = config.download_dir
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._media_refresh_lock = asyncio.Lock()
        self._media_refresh: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}

    async def download_aweme(self, aweme: dict[str, Any], blogger_name: str) -> Path:
        aweme_id = str(aweme.get("aweme_id") or "").strip()
        if not aweme_id:
            raise ValueError("作品缺少 aweme_id")

        async with DouyinAPIClient(self.config.cookies) as api_client:
            detail = await api_client.get_video_detail(aweme_id) or aweme
            if str(detail.get('aweme_id') or '') != aweme_id:
                from kenradar.sources.contracts import SourceIdentityMismatch
                raise SourceIdentityMismatch('Download metadata does not match the requested item')
            media = self._build_video_download(detail, api_client)
            if not media and str(aweme.get('aweme_id') or '') == aweme_id:
                # A nonempty but incomplete detail response must not erase verified list metadata.
                media = self._build_video_download(aweme, api_client)
                if media:
                    detail = aweme
            if not media:
                refreshed = await self._refresh_author_media(aweme, aweme_id)
                if refreshed:
                    media = self._build_video_download(refreshed, api_client)
                    if media:
                        detail = refreshed
            if not media:
                raise RuntimeError(f"未找到可下载视频地址: {aweme_id}")

            video_url, headers = media
            save_path = self._build_save_path(detail, blogger_name)
            if save_path.exists() and save_path.stat().st_size > 0:
                self.database.update_aweme_download(aweme_id, "done", str(save_path), video_url)
                return save_path
            self._cleanup_temp_files(save_path, aweme_id)
            file_manager = FileManager(str(self.download_dir))
            session = await api_client.get_session()
            ok = False
            rejected_urls: set[str] = set()
            for attempt in range(1, 4):
                ok = await file_manager.download_file(video_url, save_path, session, headers=headers)
                if ok:
                    break
                if attempt < 3:
                    if file_manager.last_error in {"MEDIA_HTTP_403", "MEDIA_HTTP_404", "MEDIA_HTTP_410"}:
                        rejected_urls.add(video_url)
                        alternative = self._build_video_download(detail, api_client, exclude=rejected_urls)
                        if not alternative:
                            alternative = self._build_video_download(aweme, api_client, exclude=rejected_urls)
                        if not alternative or attempt == 2:
                            refreshed = await self._refresh_author_media(aweme, aweme_id)
                            if refreshed:
                                refreshed_media = self._build_video_download(refreshed, api_client, exclude=rejected_urls)
                                if refreshed_media:
                                    alternative = refreshed_media
                                    detail = refreshed
                        if not alternative:
                            break
                        video_url, headers = alternative
                    await asyncio.sleep(attempt * 2)
                    logger.warning("视频下载重试 %s/3: %s", attempt + 1, aweme_id)
            if not ok:
                self._cleanup_temp_files(save_path, aweme_id)
                raise RuntimeError(f"视频下载失败: {aweme_id} ({file_manager.last_error or 'MEDIA_UNKNOWN'})")

        self.database.update_aweme_download(aweme_id, "done", str(save_path), video_url, metadata=detail)
        return save_path

    async def _refresh_author_media(self, aweme: dict[str, Any], aweme_id: str) -> dict[str, Any] | None:
        from kenradar.sources.douyin.connector import DouyinConnector
        from kenradar.vendor.douyin_downloader.browser_resolver import fetch_user_posts_with_browser

        author = aweme.get("author")
        sec_uid = str(author.get("sec_uid") or "") if isinstance(author, dict) else ""
        if not sec_uid or not DouyinConnector(self.config)._browser_source_allowed(sec_uid):
            return None
        async with self._media_refresh_lock:
            refreshed_at, posts = self._media_refresh.get(sec_uid, (0.0, {}))
            if not refreshed_at or time.monotonic() - refreshed_at >= 300:
                try:
                    items = await fetch_user_posts_with_browser(self.config, sec_uid)
                    posts = {item["aweme_id"]: item for item in items}
                except Exception as exc:
                    logger.warning("下载媒体地址刷新失败: %s", type(exc).__name__)
                    posts = {}
                self._media_refresh[sec_uid] = (time.monotonic(), posts)
            return posts.get(aweme_id)

    def _cleanup_temp_files(self, save_path: Path, aweme_id: str) -> None:
        candidates = {save_path.with_suffix(save_path.suffix + ".tmp")}
        if aweme_id:
            try:
                candidates.update(save_path.parent.glob(f"*{aweme_id}*.tmp"))
            except OSError:
                pass
        for path in candidates:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("清理临时下载文件失败: %s, %s", path, exc)

    async def download_awemes_batch(
        self,
        awemes: list[dict[str, Any]],
        blogger_name: str,
        max_workers: int | None = None,
        status_callback: Any | None = None,
    ) -> dict[str, dict[str, Any]]:
        workers = max(1, int(max_workers or self.config.get("download.max_workers", 5) or 5))
        semaphore = asyncio.Semaphore(workers)
        results: dict[str, dict[str, Any]] = {}

        async def _download_one(aweme: dict[str, Any]) -> None:
            aweme_id = str(aweme.get("aweme_id") or "").strip()
            if not aweme_id:
                return
            async with semaphore:
                try:
                    if status_callback:
                        status_callback(aweme_id, "downloading", None)
                    path = await self.download_aweme(aweme, blogger_name)
                    results[aweme_id] = {"status": "success", "video_path": path, "error": ""}
                    if status_callback:
                        status_callback(aweme_id, "downloaded", None)
                except Exception as exc:
                    results[aweme_id] = {"status": "failed", "video_path": None, "error": str(exc)}
                    self.database.update_aweme_download(aweme_id, "failed")
                    if status_callback:
                        status_callback(aweme_id, "failed", str(exc))
                    logger.exception("批量下载失败 aweme_id=%s", aweme_id)

        await asyncio.gather(*(_download_one(aweme) for aweme in awemes))
        return results

    def _build_save_path(self, aweme: dict[str, Any], blogger_name: str) -> Path:
        aweme_id = str(aweme.get("aweme_id") or "unknown")
        title = str(aweme.get("desc") or aweme.get("title") or "no_title")
        create_time = aweme.get("create_time")
        try:
            date_prefix = datetime.fromtimestamp(int(create_time)).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError, OverflowError):
            date_prefix = datetime.now().strftime("%Y-%m-%d")

        folder_name = self._extract_blogger_name(aweme, blogger_name)
        folder = self.download_dir / sanitize_filename(folder_name)
        folder.mkdir(parents=True, exist_ok=True)
        safe_title = sanitize_filename(title)[:70]
        filename_stem = truncate_filename_bytes(
            sanitize_filename(f"{date_prefix}_{safe_title}_{aweme_id}"),
            limit=220,
            fallback=f"{date_prefix}_{aweme_id}",
        )
        filename = f"{filename_stem}.mp4"
        return folder / filename

    @staticmethod
    def _extract_blogger_name(aweme: dict[str, Any], fallback: str) -> str:
        author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
        author_user = aweme.get("author_user_info") if isinstance(aweme.get("author_user_info"), dict) else {}
        return str(
            author.get("nickname")
            or author_user.get("nickname")
            or aweme.get("nickname")
            or aweme.get("author_name")
            or fallback
            or "未知博主"
        )

    def _build_video_download(
        self, aweme: dict[str, Any], api_client: Any, *, exclude: set[str] | None = None
    ) -> tuple[str, dict[str, str]] | None:
        video = aweme.get("video") if isinstance(aweme.get("video"), dict) else {}
        play_addr = self._pick_highest_quality_play_addr(video) or video.get("play_addr", {})
        url_candidates = [url for url in (play_addr.get("url_list") or []) if url]
        if exclude:
            alternate_addresses = [video.get("play_addr")]
            alternate_addresses.extend(
                entry.get("play_addr") for entry in video.get("bit_rate") or [] if isinstance(entry, dict)
            )
            for address in alternate_addresses:
                if isinstance(address, dict):
                    for url in address.get("url_list") or []:
                        if url and url not in url_candidates:
                            url_candidates.append(url)
        url_candidates.sort(key=lambda url: 0 if "watermark=0" in url else 1)

        headers = self._download_headers(api_client)
        for candidate in url_candidates:
            parsed = urlparse(candidate)
            if candidate not in (exclude or ()) and not parsed.netloc.endswith("douyin.com"):
                return candidate, headers

        for candidate in url_candidates:
            if not urlparse(candidate).netloc.endswith("douyin.com"):
                continue
            if "X-Bogus=" not in candidate:
                signed_url, user_agent = api_client.sign_url(candidate)
                if signed_url not in (exclude or ()):
                    return signed_url, self._download_headers(api_client, user_agent)
            elif candidate not in (exclude or ()):
                return candidate, headers

        uri = play_addr.get("uri") or video.get("vid") or video.get("download_addr", {}).get("uri")
        if not uri:
            return None
        signed_url, user_agent = api_client.build_signed_path(
            "/aweme/v1/play/",
            {
                "video_id": uri,
                "ratio": "1080p",
                "line": "0",
                "is_play_url": "1",
                "watermark": "0",
                "source": "PackSourceEnum_PUBLISH",
            },
        )
        return None if signed_url in (exclude or ()) else (signed_url, self._download_headers(api_client, user_agent))

    @staticmethod
    def _download_headers(api_client: Any, user_agent: str | None = None) -> dict[str, str]:
        return {
            "Referer": f"{api_client.BASE_URL}/",
            "Origin": api_client.BASE_URL,
            "Accept": "*/*",
            "User-Agent": user_agent or api_client.headers.get("User-Agent", ""),
        }

    @staticmethod
    def _pick_highest_quality_play_addr(video: dict[str, Any]) -> dict[str, Any] | None:
        bit_rates = video.get("bit_rate") if isinstance(video, dict) else None
        if not isinstance(bit_rates, list):
            return None
        best: dict[str, Any] | None = None
        best_score = -1
        for entry in bit_rates:
            if not isinstance(entry, dict) or not isinstance(entry.get("play_addr"), dict):
                continue
            try:
                bit_rate = int(entry.get("bit_rate") or 0)
                width = int(entry.get("play_addr", {}).get("width") or entry.get("width") or 0)
            except (TypeError, ValueError):
                bit_rate = 0
                width = 0
            score = bit_rate * 10_000 + width
            if score > best_score:
                best_score = score
                best = entry["play_addr"]
        return best
