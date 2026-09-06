"""Subscription radar: scan due subscriptions and enqueue new content.

Scanning is intentionally read-only with respect to content: it lists recent
items, filters out content already stored, records the discovery and enqueues a
`process_url` task per new item. Heavy work (download, transcribe, AI) happens
in the queue, never inside the scan.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from kenradar.domain.states import normalize_error_code

logger = logging.getLogger(__name__)

# Backoff applied after repeated scan failures: 0 failures -> 1x interval,
# then capped exponential growth so a broken source stops hammering upstream.
_MAX_BACKOFF_MULTIPLIER = 16


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceMonitorService:
    """Scans due subscriptions and feeds the processing queue."""

    def __init__(self, database: Any, connectors: dict[str, Any] | None = None):
        self.database = database
        if connectors is None:
            from kenradar.sources.registry import connectors_for_config

            connectors = connectors_for_config(getattr(database, "config", None))
        self.connectors = connectors or {}
        self.research_job_repo = getattr(database, "research_jobs", None)

    async def scan_due_subscriptions(self, limit: int = 50, scan_scope: str = "recent") -> dict[str, Any]:
        """Scan every due subscription and enqueue newly discovered content.

        scan_scope='recent' only walks the first page; 'full' walks all pages
        (history-capable platforms) to surface backlog beyond the latest window.
        """
        if scan_scope not in ("recent", "full"):
            raise ValueError(f"无效的 scan_scope: {scan_scope}")
        subscriptions = self.database.list_due_subscriptions(limit=limit)
        stats: dict[str, Any] = {
            "scanned": 0,
            "discovered": 0,
            "enqueued": 0,
            "failed": 0,
            "skipped": 0,
        }
        for row in subscriptions:
            subscription_id = int(row.get("id") or 0)
            platform = str(row.get("platform") or "")
            connector = self.connectors.get(platform)
            if connector is None:
                stats["skipped"] += 1
                logger.debug("跳过无连接器的订阅: id=%s platform=%s", subscription_id, platform)
                continue
            stats["scanned"] += 1
            try:
                discovered = await self._scan_one(connector, row, scan_scope=scan_scope)
                stats["discovered"] += discovered
                stats["enqueued"] += discovered
                self._record_scan(row, success=True)
            except Exception as exc:
                stats["failed"] += 1
                self._record_scan(row, success=False, error=str(exc))
                logger.warning(
                    "订阅扫描失败: id=%s platform=%s error=%s", subscription_id, platform, exc
                )
        return stats

    async def _scan_one(self, connector: Any, row: dict[str, Any], scan_scope: str = "recent") -> int:
        from kenradar.sources.contracts import SourceDescriptor

        platform = str(row.get("platform") or "")
        source = SourceDescriptor(
            platform=platform,
            external_source_id=str(row.get("source_key") or ""),
            display_name=str(row.get("display_name") or ""),
            source_url=str(row.get("source_url") or ""),
            feed_url=str(row.get("feed_url") or ""),
            history_capability=str(row.get("history_capability") or "unknown"),
        )
        if not source.external_source_id and not source.feed_url:
            raise ValueError("订阅缺少 source_key 或 feed_url")

        subscription_id = int(row.get("id") or 0)
        discovered = 0
        cursor: str | None = None
        page_count = 0
        while True:
            page = await connector.list_recent(source, cursor=cursor)
            page_count += 1
            for item in page.items:
                if not item.external_content_id:
                    continue
                if self.database.content_exists(platform, item.external_content_id):
                    continue
                self.database.mark_content_discovered(
                    platform, item.external_content_id, subscription_id, item.published_at
                )
                self.database.enqueue_task_run(
                    "process_url",
                    {
                        "url": item.url,
                        "platform": platform,
                        "external_content_id": item.external_content_id,
                        "subscription_id": subscription_id,
                        "discovery_source": "monitor",
                        "push": False,
                        "force": False,
                    },
                    message=f"订阅发现新内容：{item.title or item.external_content_id}",
                    requested_by="monitor",
                    priority=90,
                    idempotency_key=f"monitor:{platform}:{item.external_content_id}",
                )
                discovered += 1
            cursor = getattr(page, "next_cursor", None)
            if scan_scope == "recent" or not cursor or page_count >= 50:
                break
        return discovered

    def _record_scan(self, row: dict[str, Any], *, success: bool, error: str = "") -> None:
        subscription_id = int(row.get("id") or 0)
        interval = int(row.get("check_interval_minutes") or 60)
        failures = int(row.get("consecutive_failures") or 0)
        if success:
            next_failures = 0
            delay = timedelta(minutes=max(1, interval))
            last_success: datetime | None = _now()
            message = ""
        else:
            next_failures = failures + 1
            multiplier = min(_MAX_BACKOFF_MULTIPLIER, 2 ** max(0, next_failures - 1))
            delay = timedelta(minutes=max(1, interval) * multiplier)
            last_success = None
            message = error
        self.database.record_subscription_scan(
            subscription_id,
            success=success,
            next_check_at=_now() + delay,
            last_success_at=last_success,
            last_error=message,
        )
        if not success:
            code = normalize_error_code(_error_code_from_message(error))
            if code:
                logger.info("订阅扫描错误分类: subscription=%s code=%s", subscription_id, code)


    async def scan_subscription_history(
        self, *, subscription_id: int, scan_scope: str = "full"
    ) -> dict[str, Any]:
        """Scan full history of one subscription and create a review job.

        Unlike `scan_due_subscriptions`, this does NOT enqueue processing tasks.
        It records every discovered item into a research_job as `discovered`
        (status='discovered', review_status='pending') so the operator can
        confirm which items to actually process.
        """
        if scan_scope not in ("recent", "full"):
            raise ValueError(f"无效的 scan_scope: {scan_scope}")
        row = self.database.find_subscription_by_id(subscription_id)
        if row is None:
            raise ValueError(f"订阅不存在: {subscription_id}")
        platform = str(row.get("platform") or "")
        connector = self.connectors.get(platform)
        if connector is None:
            raise ValueError(f"无可用连接器: {platform}")

        source = self._build_source_descriptor(row)
        job = self.research_job_repo.create_scan_job(
            platform=platform,
            source_subscription_id=subscription_id,
            scan_scope=scan_scope,
            history_capability=str(row.get("history_capability") or "unknown"),
            creator_name=str(row.get("display_name") or ""),
        )
        job_id = int(job["id"])

        stats: dict[str, Any] = {
            "subscription_id": subscription_id,
            "job_id": job_id,
            "scan_scope": scan_scope,
            "discovered": 0,
            "already_known": 0,
        }
        cursor: str | None = None
        page_count = 0
        while True:
            page = await connector.list_recent(source, cursor=cursor)
            page_count += 1
            for item in page.items:
                if not item.external_content_id:
                    continue
                if self.database.content_exists(platform, item.external_content_id):
                    stats["already_known"] += 1
                    continue
                self.research_job_repo.add_discovered_item(
                    job_id=job_id,
                    external_content_id=item.external_content_id,
                    title=item.title,
                    url=item.url,
                    published_at=item.published_at,
                )
                stats["discovered"] += 1
            cursor = getattr(page, "next_cursor", None)
            # `recent` scope stops after the first page; `full` walks all pages.
            if scan_scope == "recent" or not cursor or page_count >= 50:
                break
        self.database.record_subscription_scan(
            subscription_id,
            success=True,
            next_check_at=_now() + timedelta(minutes=max(1, int(row.get("check_interval_minutes") or 60))),
            last_success_at=_now(),
            last_error="",
        )
        logger.info(
            "历史扫描完成: subscription=%s scope=%s discovered=%s known=%s",
            subscription_id, scan_scope, stats["discovered"], stats["already_known"],
        )
        return stats

    def _build_source_descriptor(self, row: dict[str, Any]) -> Any:
        from kenradar.sources.contracts import SourceDescriptor

        return SourceDescriptor(
            platform=str(row.get("platform") or ""),
            external_source_id=str(row.get("source_key") or ""),
            display_name=str(row.get("display_name") or ""),
            source_url=str(row.get("source_url") or ""),
            feed_url=str(row.get("feed_url") or ""),
            history_capability=str(row.get("history_capability") or "unknown"),
        )

    async def backfill_subscriptions(self, platform: str = "") -> dict[str, Any]:
        """Register sources that already have stored content but no subscription.

        Idempotent: existing subscriptions (matched on source_key) are only
        enriched with a feed URL and history capability when those are missing.
        """
        targets = ["douyin", "xiaoyuzhou"] if not platform else [platform]
        stats: dict[str, Any] = {"examined": 0, "created": 0, "enriched": 0, "skipped": 0}
        for code in targets:
            for row in self.database.list_content_sources_without_subscription(code):
                stats["examined"] += 1
                source_key = str(row.get("platform_uid") or "").strip()
                if not source_key:
                    stats["skipped"] += 1
                    continue
                existing = self.database.find_subscription(code, source_key)
                if existing is not None:
                    if await self._enrich_subscription(code, existing, row):
                        stats["enriched"] += 1
                    continue
                feed_url = await self._discover_feed(code, row)
                self.database.upsert_subscription(
                    platform=code,
                    source_key=source_key,
                    display_name=str(row.get("nickname") or source_key),
                    source_url=str(row.get("profile_url") or ""),
                    feed_url=feed_url,
                    history_capability="full" if feed_url else "limited",
                )
                stats["created"] += 1
        return stats

    async def _enrich_subscription(
        self, code: str, subscription: dict[str, Any], row: dict[str, Any]
    ) -> bool:
        """Fill in a missing feed URL / history capability on an existing row."""
        if str(subscription.get("feed_url") or "").strip():
            return False
        feed_url = await self._discover_feed(code, row)
        if not feed_url:
            return False
        self.database.upsert_subscription(
            platform=code,
            source_key=str(subscription.get("source_key") or ""),
            display_name=str(subscription.get("display_name") or row.get("nickname") or ""),
            source_url=str(subscription.get("source_url") or row.get("profile_url") or ""),
            feed_url=feed_url,
            history_capability="full",
        )
        return True

    async def _discover_feed(self, code: str, row: dict[str, Any]) -> str:
        """Best-effort public RSS discovery; network failures degrade to ''."""
        if code != "xiaoyuzhou":
            return ""
        profile_url = str(row.get("profile_url") or "")
        if profile_url.lower().endswith((".xml", ".rss")) or "/rss" in profile_url.lower():
            return profile_url
        source_key = str(row.get("platform_uid") or "")
        if not source_key:
            return ""
        from kenradar.sources.xiaoyuzhou.feed_discovery import podcast_page_url

        connector = self.connectors.get(code)
        if connector is None:
            return ""
        from urllib.parse import urlsplit

        host = urlsplit(profile_url).netloc.lower()
        page_url = profile_url if host.endswith("xiaoyuzhoufm.com") else podcast_page_url(source_key)
        try:
            html = await asyncio.to_thread(connector._fetch_text, page_url)
        except Exception:
            return ""
        from kenradar.sources.xiaoyuzhou.feed_discovery import discover_feed_url

        return discover_feed_url(html, page_url=page_url)


def _error_code_from_message(error: str) -> str:
    from kenradar.sources.contracts import SourceParseChanged

    text = str(error or "")
    if "页面结构变化" in text or "SOURCE_PARSE_CHANGED" in text:
        return SourceParseChanged.error_code
    return ""
