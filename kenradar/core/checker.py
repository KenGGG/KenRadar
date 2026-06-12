from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kenradar.core.config import AppConfig
from kenradar.storage.database import Database
from kenradar.vendor.douyin_downloader.api_client import DouyinAPIClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BloggerTarget:
    id: int
    sec_uid: str
    name: str
    url: str


class Checker:
    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.database = database

    def load_targets(self) -> list[BloggerTarget]:
        bloggers = self.config.get("bloggers", []) or []
        if not isinstance(bloggers, list):
            raise ValueError("配置项 bloggers 必须是列表")

        targets: list[BloggerTarget] = []
        for item in bloggers:
            if not isinstance(item, dict) or not item.get("enabled", True):
                continue
            url = str(item.get("url", "")).strip()
            sec_uid = str(item.get("sec_uid") or self._extract_sec_uid(url)).strip()
            if not sec_uid:
                raise ValueError(f"无法从博主配置提取 sec_uid: {item}")
            name = str(item.get("name") or sec_uid).strip()
            blogger_id = self.database.upsert_blogger(url=url, name=name, sec_uid=sec_uid, enabled=True)
            targets.append(BloggerTarget(id=blogger_id, sec_uid=sec_uid, name=name, url=url))
        return targets

    async def fetch_new_awemes(self, target: BloggerTarget) -> list[dict[str, Any]]:
        checkpoint = self.database.get_blogger_checkpoint(target.id)
        last_check_ts = self._checkpoint_timestamp(checkpoint.get("last_check_at"))
        now_ts = int(time.time())
        max_age_hours = float(self.config.get("schedule.max_aweme_age_hours", 36) or 0)
        publish_grace_seconds = int(self.config.get("schedule.publish_time_grace_seconds", 300) or 0)
        oldest_allowed_ts = now_ts - int(max_age_hours * 3600) if max_age_hours > 0 else 0

        async with DouyinAPIClient(self.config.cookies) as api_client:
            response = await api_client.get_user_post(target.sec_uid, max_cursor=0, count=20)

        items = response.get("items") or response.get("aweme_list") or []
        if not isinstance(items, list):
            return []

        new_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            aweme_id = str(item.get("aweme_id") or "").strip()
            if not aweme_id or not self.database.should_process_aweme(aweme_id):
                continue
            if self._is_gallery(item):
                continue
            publish_ts = self._epoch_seconds(item.get("create_time"))
            if not self._publish_time_matches_run_window(
                publish_ts,
                last_check_ts=last_check_ts,
                oldest_allowed_ts=oldest_allowed_ts,
                publish_grace_seconds=publish_grace_seconds,
                aweme_id=aweme_id,
                target=target,
            ):
                continue
            self.database.insert_aweme(target.id, item, status="pending")
            new_items.append(item)

        latest_aweme_id = str(items[0].get("aweme_id")) if items and isinstance(items[0], dict) else None
        self.database.update_blogger_checkpoint(target.id, latest_aweme_id)
        return new_items

    async def fetch_aweme_history(self, target: BloggerTarget, limit: int = 0) -> list[dict[str, Any]]:
        """分页拉取博主历史作品。

        分页行为参考本机 douyin-downloader 的 PostUserModeStrategy：按
        has_more/max_cursor 继续请求，cursor 不推进时停止，避免死循环。
        """
        awemes: list[dict[str, Any]] = []
        seen: set[str] = set()
        max_cursor = 0
        has_more = True

        async with DouyinAPIClient(self.config.cookies) as api_client:
            while has_more:
                request_cursor = max_cursor
                response = await api_client.get_user_post(target.sec_uid, max_cursor=request_cursor, count=20)
                items = response.get("items") or response.get("aweme_list") or []
                if not isinstance(items, list) or not items:
                    break

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    aweme_id = str(item.get("aweme_id") or "").strip()
                    if not aweme_id or aweme_id in seen:
                        continue
                    seen.add(aweme_id)
                    if self._is_gallery(item):
                        continue
                    self.database.insert_aweme(target.id, item, status="pending")
                    awemes.append(item)
                    if limit > 0 and len(awemes) >= limit:
                        self.database.update_blogger_checkpoint(target.id, str(items[0].get("aweme_id") or ""))
                        return awemes

                has_more = bool(response.get("has_more", False))
                try:
                    max_cursor = int(response.get("max_cursor", 0) or 0)
                except (TypeError, ValueError):
                    max_cursor = 0
                if has_more and max_cursor == request_cursor:
                    logger.warning("作品分页 cursor 未推进，停止分页: cursor=%s", max_cursor)
                    break

        if awemes:
            self.database.update_blogger_checkpoint(target.id, str(awemes[0].get("aweme_id") or ""))
        else:
            self.database.update_blogger_checkpoint(target.id, None)
        return awemes

    @staticmethod
    def _extract_sec_uid(url: str) -> str:
        match = re.search(r"/user/([^/?#]+)", url)
        return match.group(1) if match else ""

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
    def _epoch_seconds(value: Any) -> int:
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _checkpoint_timestamp(value: Any) -> int:
        if value in (None, ""):
            return 0
        if isinstance(value, datetime):
            return int(value.timestamp())
        text = str(value).strip()
        if not text:
            return 0
        if text.isdigit():
            return int(text)
        normalized = text.replace("T", " ").replace("Z", "+00:00")
        try:
            return int(datetime.fromisoformat(normalized).timestamp())
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                try:
                    return int(datetime.strptime(text, fmt).timestamp())
                except ValueError:
                    continue
        return 0

    def _publish_time_matches_run_window(
        self,
        publish_ts: int,
        *,
        last_check_ts: int,
        oldest_allowed_ts: int,
        publish_grace_seconds: int,
        aweme_id: str,
        target: BloggerTarget,
    ) -> bool:
        if publish_ts <= 0:
            logger.warning("跳过缺少发布时间的作品: blogger=%s aweme_id=%s", target.name, aweme_id)
            return False
        if oldest_allowed_ts and publish_ts < oldest_allowed_ts:
            logger.info(
                "跳过过旧作品: blogger=%s aweme_id=%s publish_ts=%s oldest_allowed_ts=%s",
                target.name,
                aweme_id,
                publish_ts,
                oldest_allowed_ts,
            )
            return False
        if last_check_ts and publish_ts <= last_check_ts - max(0, publish_grace_seconds):
            logger.info(
                "跳过上次检测前已发布作品: blogger=%s aweme_id=%s publish_ts=%s last_check_ts=%s",
                target.name,
                aweme_id,
                publish_ts,
                last_check_ts,
            )
            return False
        return True
