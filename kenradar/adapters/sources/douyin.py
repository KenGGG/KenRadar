from __future__ import annotations

import logging
from typing import Any

from kenradar.adapters.protocols import SourceAdapter, SourceItem
from kenradar.adapters.sources import register

logger = logging.getLogger(__name__)


class DouyinSourceAdapter(SourceAdapter):
    """抖音内容源适配器 — 包装现有 vendor 实现"""

    platform = "douyin"

    def __init__(self, config: dict[str, Any]):
        self._config = config
        self._resolver = None  # lazy init

    def _get_resolver(self) -> Any:
        if self._resolver is None:
            from kenradar.core.source_resolver import resolve_douyin_video
            self._resolver = resolve_douyin_video
        return self._resolver

    def fetch_items(self, sec_uid: str, max_count: int = 30, **kwargs: Any) -> list[SourceItem]:
        from kenradar.vendor.douyin_downloader import fetch_user_posts
        items = fetch_user_posts(sec_uid, max_count=max_count, config=self._config)
        return [
            SourceItem(
                id=str(item.get("aweme_id", "")),
                title=str(item.get("desc", "")),
                url=f"https://www.douyin.com/video/{item.get('aweme_id', '')}",
                published_at=str(item.get("create_time", "")),
                author_name=str(item.get("author", {}).get("nickname", "")),
                extra=item,
            )
            for item in (items if isinstance(items, list) else [])
        ]

    def resolve_user(self, url: str | None = None, name: str | None = None, sec_uid: str | None = None) -> dict[str, Any]:
        from kenradar.core.source_resolver import resolve_source
        return resolve_source(url=url, name=name, sec_uid=sec_uid, config=self._config)


# 自动注册
register("douyin", DouyinSourceAdapter)
