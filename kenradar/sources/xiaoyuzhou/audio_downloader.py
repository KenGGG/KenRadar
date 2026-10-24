from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from kenradar.core.config import AppConfig
from kenradar.sources.base import ContentItem
from kenradar.utils.text import sanitize_filename, truncate_filename_bytes

logger = logging.getLogger(__name__)

ALLOWED_AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav"}


class AudioDownloader:
    def __init__(self, config: AppConfig):
        self.config = config
        self.temp_dir = config.resolve_path(config.get("sources.xiaoyuzhou.audio_temp_dir", "data/tmp/podcast_audio"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def download(self, item: ContentItem) -> Path | None:
        audio_url = item.media_url or str(item.raw_metadata.get("audio_url") or "")
        if not audio_url:
            item.failure_reason = "missing_audio_url"
            return None
        suffix = _suffix_from_url(audio_url)
        if suffix not in ALLOWED_AUDIO_SUFFIXES:
            item.failure_reason = f"unsupported_audio_type:{suffix or 'unknown'}"
            return None
        filename = truncate_filename_bytes(
            sanitize_filename(f"{item.content_id}_{item.original_title}") + suffix,
            limit=180,
            fallback=f"{sanitize_filename(item.content_id, 'episode')}{suffix}",
        )
        target = self.temp_dir / filename
        if target.exists() and target.stat().st_size > 0:
            item.local_path = str(target)
            return target
        tmp = target.with_suffix(target.suffix + ".tmp")
        timeout = int(self.config.get("sources.xiaoyuzhou.request_timeout_seconds", 30) or 30)
        try:
            if self.config.get('integrations.hermes_v1.safe_network', False):
                from kenradar.integrations.safe_network import safe_get
                request = safe_get(audio_url, timeout=timeout)
            else:
                request = requests.get(audio_url, stream=True, timeout=timeout)
            with request as response:
                response.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            fh.write(chunk)
            if tmp.stat().st_size <= 0:
                raise RuntimeError("downloaded_audio_empty")
            tmp.replace(target)
            item.local_path = str(target)
            item.failure_reason = None
            return target
        except Exception as exc:
            from kenradar.integrations.hermes_v1 import ContractError
            tmp.unlink(missing_ok=True)
            if isinstance(exc, ContractError):
                raise
            item.failure_reason = str(exc)
            logger.warning("小宇宙音频下载失败: episode=%s error=%s", item.content_id, exc)
            return None


def _suffix_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix
