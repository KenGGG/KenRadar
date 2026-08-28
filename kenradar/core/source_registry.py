from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from kenradar.core.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BloggerTarget:
    id: int
    sec_uid: str
    name: str
    url: str


class SourceRegistry:
    """PostgreSQL-first source registry with YAML import compatibility."""

    def __init__(self, config: AppConfig, database: Any):
        self.config = config
        self.database = database

    @staticmethod
    def _extract_sec_uid(url: str) -> str:
        match = re.search(r"/user/([^/?#]+)", str(url or ""))
        return match.group(1) if match else ""

    def _config_sources(self) -> list[dict[str, Any]]:
        bloggers = self.config.get("bloggers", []) or []
        if not isinstance(bloggers, list):
            raise ValueError("配置项 bloggers 必须是列表")
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in bloggers:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            sec_uid = str(item.get("sec_uid") or self._extract_sec_uid(url)).strip()
            if not sec_uid:
                raise ValueError(f"无法从博主配置提取 sec_uid: {item}")
            if sec_uid in seen:
                logger.warning("检测到重复来源配置，已跳过: sec_uid=%s", sec_uid)
                continue
            seen.add(sec_uid)
            sources.append(
                {
                    "sec_uid": sec_uid,
                    "name": str(item.get("name") or sec_uid).strip(),
                    "url": url,
                    "category": str(item.get("category") or "").strip(),
                    "enabled": bool(item.get("enabled", True)),
                }
            )
        return sources

    def import_config_sources(self) -> dict[str, int]:
        sources = self._config_sources()
        for source in sources:
            creator_id = self.database.upsert_blogger(
                url=source["url"],
                name=source["name"],
                sec_uid=source["sec_uid"],
                enabled=source["enabled"],
                preserve_existing_enabled=True,
            )
            self.database.upsert_source_subscription(
                platform="douyin",
                source_type="creator",
                source_key=source["sec_uid"],
                display_name=source["name"],
                source_url=source["url"],
                category=source["category"],
                enabled=source["enabled"],
                extra={"creator_id": creator_id, "imported_from_config": True},
                preserve_existing_enabled=True,
            )
        return {"configured": len(sources), "imported": len(sources)}

    @staticmethod
    def _creator_id(row: dict[str, Any]) -> int:
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        try:
            return int(row.get("creator_id") or extra.get("creator_id") or 0)
        except (TypeError, ValueError):
            return 0

    def list_monitor_targets(self) -> list[BloggerTarget]:
        rows = self.database.list_source_subscriptions(platform="douyin")
        if not rows:
            self.import_config_sources()
            rows = self.database.list_source_subscriptions(platform="douyin")
        targets: list[BloggerTarget] = []
        for row in rows:
            if not bool(row.get("enabled")):
                continue
            sec_uid = str(row.get("source_key") or "").strip()
            if not sec_uid:
                continue
            creator_id = self._creator_id(row)
            if creator_id <= 0:
                creator_id = self.database.upsert_blogger(
                    url=str(row.get("source_url") or ""),
                    name=str(row.get("display_name") or sec_uid),
                    sec_uid=sec_uid,
                    enabled=True,
                    preserve_existing_enabled=True,
                )
            targets.append(
                BloggerTarget(
                    id=creator_id,
                    sec_uid=sec_uid,
                    name=str(row.get("display_name") or sec_uid),
                    url=str(row.get("source_url") or ""),
                )
            )
        return targets

    def diagnostics(self) -> dict[str, int]:
        configured = self._config_sources()
        rows = self.database.list_source_subscriptions(platform="douyin")
        config_keys = {row["sec_uid"] for row in configured}
        database_keys = {str(row.get("source_key") or "") for row in rows}
        return {
            "config_total": len(configured),
            "config_enabled": sum(1 for row in configured if row["enabled"]),
            "database_total": len(rows),
            "database_enabled": sum(1 for row in rows if bool(row.get("enabled"))),
            "config_only": len(config_keys - database_keys),
            "database_only": len(database_keys - config_keys),
        }
