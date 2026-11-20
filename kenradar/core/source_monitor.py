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

    def __init__(self, database: Any, connectors: dict[str, Any] | None = None, max_pending_tasks: int = 0):
        self.database = database
        if connectors is None:
            from kenradar.sources.registry import connectors_for_config

            connectors = connectors_for_config(getattr(database, "config", None))
        self.connectors = connectors or {}
        self.research_job_repo = getattr(database, "research_jobs", None)
        self.max_pending_tasks = max(0, int(max_pending_tasks or 0))

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
            "backpressure": False,
            "errors": [],
        }
        if self.max_pending_tasks and self.database.count_pending_task_runs() >= self.max_pending_tasks:
            stats["backpressure"] = True
            logger.info("订阅扫描暂停入队：待处理任务已达上限 %s", self.max_pending_tasks)
            return stats
        self._scan_remaining = max(0, self.max_pending_tasks - self.database.count_pending_task_runs()) if self.max_pending_tasks else None
        for row in subscriptions:
            if self._scan_remaining == 0:
                stats["backpressure"] = True
                break
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
                if self._scan_remaining == 0:
                    stats["backpressure"] = True
                else:
                    self._record_scan(row, success=True)
            except Exception as exc:
                stats["failed"] += 1
                stats["errors"].append({"subscription_id": subscription_id, "platform": platform, "error": str(exc)})
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
        # Validate the complete bounded walk before any discovery or enqueue writes.
        # A valid first page followed by a broken cursor is not a successful scan.
        pages = [page async for page in self._list_pages(connector, source, scan_scope)]
        fill_name = getattr(self.database, "fill_source_display_name", None)
        if platform == "douyin" and fill_name and source.display_name in ("", source.external_source_id):
            for item in (item for page in pages for item in page.items):
                author = item.raw_metadata.get("author")
                if not isinstance(author, dict) or author.get("sec_uid") != source.external_source_id:
                    continue
                nickname = str(author.get("nickname") or "").strip()
                if nickname and nickname != source.external_source_id:
                    fill_name(subscription_id, source.external_source_id, nickname)
                    break
        for page in pages:
            for item in page.items:
                if not item.external_content_id:
                    continue
                if self.database.content_exists(platform, item.external_content_id):
                    if getattr(self, "_scan_remaining", None) == 0:
                        return discovered
                    if self._enqueue_failed_stage_recovery(platform, item.external_content_id, subscription_id):
                        if getattr(self, "_scan_remaining", None) is not None:
                            self._scan_remaining -= 1
                    continue
                if getattr(self, "_scan_remaining", None) == 0:
                    return discovered
                self.database.mark_content_discovered(
                    platform, item.external_content_id, subscription_id, item.published_at
                )
                podcast_snapshot = {}
                if platform == 'xiaoyuzhou':
                    podcast_snapshot['item'] = {
                        'platform': platform, 'creator': source.display_name,
                        'creator_id': item.external_source_id or source.external_source_id,
                        'content_id': item.external_content_id, 'source_url': item.url,
                        'original_title': item.title,
                        'published_at': item.published_at.isoformat() if item.published_at else None,
                        'media_type': item.media_type, 'duration': item.duration,
                        'description': item.description, 'cover_url': item.cover_url,
                        'media_url': item.media_url,
                        'raw_metadata': {**item.raw_metadata, 'feed_url': source.feed_url},
                    }
                self.database.enqueue_task_run(
                    "process_url",
                    {
                        "url": item.url,
                        "platform": platform,
                        "external_content_id": item.external_content_id,
                        "subscription_id": subscription_id,
                        "day": getattr(self, 'business_day', ''),
                        "discovery_source": "monitor",
                        "push": False,
                        "force": False,
                        **podcast_snapshot,
                    },
                    message=f"订阅发现新内容：{item.title or item.external_content_id}",
                    requested_by="monitor",
                    priority=90,
                    idempotency_key=f"process-url:{item.url}",
                )
                discovered += 1
                if getattr(self, "_scan_remaining", None) is not None:
                    self._scan_remaining -= 1
        return discovered

    def _enqueue_failed_stage_recovery(self, platform: str, external_id: str, subscription_id: int) -> bool:
        config = getattr(self.database, 'config', None)
        if platform not in ('douyin', 'xiaoyuzhou') or config is None or config.get('schedule.mode') != 'subscription_daily':
            return False
        content = self.database.find_content_item(platform, external_id)
        if not content:
            return False
        bundle = self.database.get_current_bundle(content['id'])
        transcript, analysis = bundle.get('transcript') or {}, bundle.get('analysis') or {}
        if transcript.get('status') == 'success' and (analysis.get('status') in ('failed','degraded')
                or (platform == 'xiaoyuzhou' and not analysis.get('status'))):
            stage = 'podcast_organize' if platform == 'xiaoyuzhou' else 'retry_summary'
        elif platform == 'xiaoyuzhou' and transcript.get('status') != 'success':
            stage = 'process_url'
        elif platform == 'douyin' and transcript.get('status') == 'failed':
            stage = 'retry_transcribe'
        elif platform == 'douyin' and content.get('download_status') == 'failed':
            stage = 'retry_download'
        elif transcript.get('status') == 'success' and analysis.get('status') == 'success' and (bundle.get('note') or {}).get('content_sha256'):
            # Recover a demonstrated failed delivery, not every historical note
            # whose migrated database happens not to contain a receipt.
            from sqlalchemy import select
            publication = self.database.table('publication_log')
            with self.database.connect() as conn:
                failed_publication = conn.execute(select(publication.c.id).where(
                    publication.c.content_item_id == content['id'],
                    publication.c.source_hash == bundle['note']['content_sha256'],
                    publication.c.status == 'failed')).fetchone()
            if not failed_publication or self.database.publications.find_success(content['id'], bundle['note']['content_sha256']):
                return False
            stage = 'publish_content'
        else:
            return False
        updated = str(content.get('updated_at') or '')
        try:
            age = _now() - datetime.fromisoformat(updated.replace('Z','+00:00'))
        except (ValueError, TypeError):
            return False
        if age < timedelta(minutes=max(0, int(config.get('schedule.recovery_cooldown_minutes',60)))):
            return False
        from sqlalchemy import select
        table = self.database.table('task_run')
        key = f'monitor-recovery:{platform}:{external_id}:{stage}'
        if stage == 'publish_content':
            key += ':' + bundle['note']['content_sha256']
        # Reuse one bounded durable retry task for this stage, never a daily unbounded resubmission.
        with self.database.connect() as conn:
            if conn.execute(select(table.c.id).where(table.c.idempotency_key == key)).fetchone():
                return False
        payload = {'aweme_id':external_id,'external_content_id':external_id,'platform':platform,
             'content_item_id':content['id'],'day':getattr(self, 'business_day', ''),
             'subscription_id':subscription_id,'push':False,'force':False,'trigger':'monitor_recovery'}
        if stage in ('podcast_organize', 'process_url'):
            # Automatic recovery is limited to normal subscription work, not
            # old authorized history batches merely present in an RSS feed.
            from sqlalchemy import func
            with self.database.connect() as conn:
                monitor_failure = conn.execute(select(table.c.id).where(
                    table.c.status == 'failed',
                    func.json_extract(table.c.payload_json, '$.platform') == platform,
                    func.json_extract(table.c.payload_json, '$.external_content_id') == external_id,
                    func.json_extract(table.c.payload_json, '$.discovery_source') == 'monitor'
                )).fetchone()
            if not monitor_failure:
                return False
            creator = self.database.get_creator(content['creator_id']) or {}
            payload['item'] = {
                'platform': platform, 'creator': creator.get('name') or creator.get('nickname') or '',
                'creator_id': str(creator.get('platform_uid') or creator.get('creator_id') or ''),
                'content_id': external_id, 'source_url': content.get('source_url') or '',
                'original_title': content.get('title') or external_id,
                'published_at': str(content.get('publish_time') or '') or None, 'media_type': 'audio',
                'duration': content.get('duration'), 'description': content.get('description'),
                'cover_url': content.get('cover_url'), 'media_url': content.get('media_url'),
                'raw_metadata': dict(content.get('extra') or {})}
        self.database.enqueue_task_run(stage, payload,
            message=f'订阅失败阶段恢复：{stage} {external_id}',requested_by='monitor',priority=80,
            idempotency_key=key,max_attempts=3)
        self.recovery_enqueued = getattr(self,'recovery_enqueued',0) + 1
        return True

    async def _list_pages(self, connector: Any, source: Any, scan_scope: str):
        cursor = None
        seen = set()
        for page_count in range(1, 51):
            page = await connector.list_recent(source, cursor=cursor)
            yield page
            if scan_scope == "recent" or not page.has_more:
                return
            next_cursor = getattr(page, "next_cursor", None)
            if not next_cursor or next_cursor == cursor or next_cursor in seen:
                raise RuntimeError("SOURCE_INCOMPLETE: missing or repeated pagination cursor")
            if page_count == 50:
                raise RuntimeError("SOURCE_INCOMPLETE: pagination page limit reached")
            seen.add(next_cursor)
            cursor = next_cursor

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
        try:
            async for page in self._list_pages(connector, source, scan_scope):
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
        except Exception as exc:
            self._record_scan(row, success=False, error=str(exc))
            raise
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
