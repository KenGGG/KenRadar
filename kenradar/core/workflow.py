from __future__ import annotations

import json
import logging
import re
import asyncio
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.ai_json import parse_ai_json
from kenradar.core.checker import BloggerTarget, Checker
from kenradar.core.config import AppConfig
from kenradar.core.downloader import Downloader
from kenradar.core.obsidian import (
    brief_dir,
    format_ts,
    note_dir,
    note_filename,
    platform_label,
    summary_dir,
)
from kenradar.core.organizer import ContentOrganizer
from kenradar.core.gpu_scheduler import GpuResourceManager
from kenradar.core.source_resolver import resolve_douyin_video
from kenradar.core.transcriber import Transcriber
from kenradar.notification.alert import AlertManager
from kenradar.notification.feishu import FeishuPusher
from kenradar.publishing import GithubSyncManager, StaticSitePublisher
from kenradar.storage import create_database
from kenradar.utils.text import sanitize_filename

logger = logging.getLogger(__name__)


class Workflow:
    def __init__(self, config: AppConfig):
        self.config = config
        self.database = create_database(config)
        self.database.initialize()
        self.checker = Checker(config, self.database)
        self.downloader = Downloader(config, self.database)
        self.transcriber = Transcriber(config, self.database)
        self.organizer = ContentOrganizer(config)
        self.alerts = AlertManager(config, self.database)
        self.pusher = FeishuPusher(config, self.database)
        self.publisher = StaticSitePublisher(config)

    async def run_once(self, push: bool = True) -> dict[str, Any]:
        targets = self.checker.load_targets()
        pushed_items: list[dict[str, Any]] = []
        stats = {"bloggers": len(targets), "new_awemes": 0, "downloaded": 0, "transcribed": 0, "summarized": 0, "failed": 0, "pushed": False}

        for target in targets:
            try:
                new_awemes = await self.checker.fetch_new_awemes(target)
            except Exception as exc:
                stats["failed"] += 1
                logger.exception("抓取博主作品失败: %s", target.name)
                self.alerts.error(
                    "crawler",
                    str(exc),
                    title=target.name,
                    context={"sec_uid": target.sec_uid, "url": target.url},
                )
                continue
            stats["new_awemes"] += len(new_awemes)
            download_results = await self.downloader.download_awemes_batch(
                new_awemes,
                target.name,
                max_workers=self._download_max_workers(),
            )
            for aweme in new_awemes:
                aweme_id = str(aweme.get("aweme_id") or "")
                title = str(aweme.get("desc") or aweme.get("title") or "无标题")
                result = download_results.get(aweme_id) or {}
                if result.get("status") != "success":
                    stats["failed"] += 1
                    error = str(result.get("error") or "视频下载失败")
                    logger.error("视频下载失败 aweme_id=%s: %s", aweme_id, error)
                    self.alerts.error("download", error, aweme_id=aweme_id, title=title)
                    continue
                video_path = Path(str(result.get("video_path") or ""))
                if not video_path.exists():
                    stats["failed"] += 1
                    error = f"下载结果缺少本地文件: {video_path}"
                    self.database.update_aweme_download(aweme_id, "failed")
                    self.alerts.error("download", error, aweme_id=aweme_id, title=title)
                    continue
                stats["downloaded"] += 1

                metadata = self._video_metadata(aweme, target.name, target.sec_uid)
                transcript = await self.transcriber.transcribe(aweme_id, video_path, metadata)
                if transcript.get("status") != "success":
                    stats["failed"] += 1
                    self.alerts.error(
                        "whisper",
                        str(transcript.get("error") or "Whisper 转录失败"),
                        aweme_id=aweme_id,
                        title=title,
                        context={"video_path": str(video_path)},
                    )
                    continue

                stats["transcribed"] += 1
                text = str(transcript.get("text") or "")
                summary_text = self.organizer.organize(title, text, metadata)
                if self.organizer.last_error:
                    self.alerts.error(
                        "openai_api",
                        self.organizer.last_error,
                        aweme_id=aweme_id,
                        title=title,
                        context={"workflow": "run_once"},
                    )
                else:
                    stats["summarized"] += 1
                summary_status = "failed" if self.organizer.last_error else "success"
                summary_path = self._write_item_summary(aweme_id, title, summary_text, text, metadata, str(transcript.get("text_path") or ""), summary_status)
                html_url = self._publish_markdown(summary_path, title)
                self.database.upsert_summary(
                    aweme_id=aweme_id,
                    summary_text=summary_text,
                    summary_path=str(summary_path),
                    model=str(self.config.get("ai.organizer.model", "")),
                    status=summary_status,
                    error_message=self.organizer.last_error,
                )
                self._cleanup_download_artifacts(aweme_id, video_path=video_path, transcript=transcript)
                pushed_items.append(
                    {
                        "aweme_id": aweme_id,
                        "blogger_name": target.name,
                        "title": title,
                        "create_time": self._format_timestamp(aweme.get("create_time")),
                        "text": summary_text,
                        "transcript": text,
                        "summary_status": summary_status,
                        "summary_path": str(summary_path),
                        "html_url": html_url,
                        "transcript_file": str(transcript.get("text_path") or ""),
                        "url": f"https://www.douyin.com/video/{aweme_id}",
                        "detail_url": self._detail_url(aweme_id),
                    }
                )

        if push:
            if pushed_items:
                stats["pushed"] = self.pusher.push(pushed_items)
            else:
                stats["pushed"] = self.pusher.push_empty_report(stats)
            if not stats["pushed"]:
                self.alerts.error("feishu_push", "飞书简报推送失败", context={"items": len(pushed_items)})
        return stats

    def _download_max_workers(self) -> int:
        return max(1, int(self.config.get("download.max_workers", 5) or 5))

    async def test_latest(self, limit_per_target: int = 1, push: bool = True) -> dict[str, Any]:
        """强制处理每个启用博主的最新作品，用于端到端验收。"""
        targets = self.checker.load_targets()
        pushed_items: list[dict[str, Any]] = []
        stats = {
            "bloggers": len(targets),
            "fetched": 0,
            "downloaded": 0,
            "transcribed": 0,
            "summarized": 0,
            "failed": 0,
            "pushed": False,
            "items": [],
        }
        for target in targets:
            try:
                awemes = await self.checker.fetch_aweme_history(target, limit=limit_per_target)
            except Exception as exc:
                stats["failed"] += 1
                logger.exception("测试抓取博主最新作品失败: %s", target.name)
                self.alerts.error("crawler", str(exc), title=target.name, context={"workflow": "test_latest"})
                continue
            stats["fetched"] += len(awemes)
            for aweme in awemes:
                item = await self._process_aweme_for_push(aweme, target.name, target.sec_uid, workflow_name="test_latest")
                if item:
                    pushed_items.append(item)
                    stats["downloaded"] += 1
                    stats["transcribed"] += 1
                    if item.get("summary_status") == "success":
                        stats["summarized"] += 1
                    stats["items"].append({"aweme_id": item["aweme_id"], "title": item["title"], "detail_url": item["detail_url"]})
                else:
                    stats["failed"] += 1

        if push and pushed_items:
            stats["pushed"] = self.pusher.push(pushed_items)
            if not stats["pushed"]:
                self.alerts.error("feishu_push", "飞书测试简报推送失败", context={"items": len(pushed_items), "workflow": "test_latest"})
        return stats

    async def _process_aweme_for_push(
        self,
        aweme: dict[str, Any],
        blogger_name: str,
        blogger_id: int | str,
        workflow_name: str,
        research_job_id: int | None = None,
        video_path: Path | None = None,
    ) -> dict[str, Any] | None:
        aweme_id = str(aweme.get("aweme_id") or "")
        title = str(aweme.get("desc") or aweme.get("title") or "无标题")
        if video_path is None:
            try:
                self._mark_research_item(research_job_id, aweme_id, "downloading")
                video_path = await self.downloader.download_aweme(aweme, blogger_name)
            except Exception as exc:
                self.database.update_aweme_download(aweme_id, "failed")
                self._mark_research_item(research_job_id, aweme_id, "failed", str(exc))
                logger.exception("视频下载失败 aweme_id=%s", aweme_id)
                self.alerts.error("download", str(exc), aweme_id=aweme_id, title=title, context={"workflow": workflow_name})
                return None

        metadata = self._video_metadata(aweme, blogger_name, blogger_id)
        existing_transcript = self.database.get_successful_transcript(aweme_id)
        if existing_transcript and str(existing_transcript.get("text_content") or "").strip():
            logger.info("复用已有成功转录，跳过 ASR/Whisper: workflow=%s aweme_id=%s model=%s", workflow_name, aweme_id, existing_transcript.get("model") or "")
            transcript = self._transcript_payload(existing_transcript)
        else:
            self._mark_research_item(research_job_id, aweme_id, "transcribing")
            transcript = await self.transcriber.transcribe(aweme_id, video_path, metadata)
        if transcript.get("status") != "success":
            self._mark_research_item(research_job_id, aweme_id, "failed", str(transcript.get("error") or "Whisper 转录失败"))
            self.alerts.error(
                "whisper",
                str(transcript.get("error") or "Whisper 转录失败"),
                aweme_id=aweme_id,
                title=title,
                context={"video_path": str(video_path), "workflow": workflow_name},
            )
            return None

        text = str(transcript.get("text") or "")
        self._mark_research_item(research_job_id, aweme_id, "summarizing")
        summary_text = self.organizer.organize(title, text, metadata)
        summary_status = "success"
        if self.organizer.last_error:
            summary_status = "failed"
            self.alerts.error("openai_api", self.organizer.last_error, aweme_id=aweme_id, title=title, context={"workflow": workflow_name})
        self._mark_research_item(research_job_id, aweme_id, "noting")
        summary_path = self._write_item_summary(aweme_id, title, summary_text, text, metadata, str(transcript.get("text_path") or ""), summary_status)
        html_url = self._publish_markdown(summary_path, title)
        self.database.upsert_summary(
            aweme_id=aweme_id,
            summary_text=summary_text,
            summary_path=str(summary_path),
            model=str(self.config.get("ai.organizer.model", "")),
            status=summary_status,
            error_message=self.organizer.last_error,
        )
        self._cleanup_download_artifacts(aweme_id, video_path=video_path, transcript=transcript)
        return {
            "aweme_id": aweme_id,
            "blogger_name": blogger_name,
            "title": title,
            "create_time": self._format_timestamp(aweme.get("create_time")),
            "text": summary_text,
            "transcript": text,
            "summary_status": summary_status,
            "summary_path": str(summary_path),
            "html_url": html_url,
            "transcript_file": str(transcript.get("text_path") or ""),
            "url": f"https://www.douyin.com/video/{aweme_id}",
            "detail_url": self._detail_url(aweme_id),
        }

    def _mark_research_item(self, job_id: int | None, aweme_id: str, status: str, error_message: str | None = None) -> None:
        if job_id is None or not aweme_id:
            return
        self.database.upsert_research_job_item(job_id, aweme_id, status, error_message)

    def _fail_research_item(
        self,
        job_id: int,
        aweme_id: str,
        title: str,
        component: str,
        error: str,
        stats: dict[str, Any],
        total: int,
        context: dict[str, Any] | None = None,
    ) -> None:
        stats["failed"] += 1
        self.database.upsert_research_job_item(job_id, aweme_id, "failed", error)
        self.alerts.error(component, error, aweme_id=aweme_id, title=title, context={"job_id": job_id, **(context or {})})
        self._update_research_counts(job_id, stats, total)

    def _research_job_cancelled(self, job_id: int) -> bool:
        return self._research_job_status(job_id) == "cancelled"

    def _research_job_status(self, job_id: int) -> str:
        with self.database.connect() as conn:
            row = conn.execute("SELECT status FROM research_job WHERE id = %s", (job_id,)).fetchone()
        return str(row["status"] or "") if row else ""

    async def _wait_research_job_resumed(self, job_id: int) -> bool:
        while True:
            status = self._research_job_status(job_id)
            if status == "cancelled":
                return False
            if status != "paused":
                return True
            await asyncio.sleep(2)

    async def backfill_blogger(self, target_index: int = 0, limit: int = 0) -> dict[str, Any]:
        targets = self.checker.load_targets()
        if not targets:
            raise ValueError("没有启用的博主配置")
        if target_index < 0 or target_index >= len(targets):
            raise IndexError(f"target_index 超出范围: {target_index}, 当前启用博主数={len(targets)}")

        target = targets[target_index]
        awemes = await self.checker.fetch_aweme_history(target, limit=limit)
        stats: dict[str, Any] = {
            "blogger": target.name,
            "fetched": len(awemes),
            "downloaded": 0,
            "transcribed": 0,
            "skipped": 0,
            "failed": 0,
            "summary_path": "",
        }
        processed: list[dict[str, str]] = []

        for index, aweme in enumerate(awemes, start=1):
            aweme_id = str(aweme.get("aweme_id") or "")
            title = aweme.get("desc") or aweme.get("title") or "无标题"
            if aweme_id and not self.database.should_process_aweme(aweme_id):
                stats["skipped"] += 1
                existing = self.database.get_successful_transcript(aweme_id)
                if existing:
                    summary = self.database.get_summary(aweme_id)
                    processed.append(
                        {
                            "aweme_id": aweme_id,
                            "title": str(title),
                            "create_time": self._format_timestamp(aweme.get("create_time")),
                            "text_path": str(existing.get("text_path") or ""),
                            "text": str(existing.get("text_content") or ""),
                            "summary": str(summary.get("summary_text") or "") if summary else "",
                            "url": f"https://www.douyin.com/video/{aweme_id}",
                            "blogger_name": target.name,
                            "blogger_id": str(target.sec_uid),
                            "transcript_file": str(existing.get("text_path") or ""),
                        }
                    )
                continue
            logger.info("[%s/%s] 处理作品 %s: %s", index, len(awemes), aweme_id, title)
            try:
                video_path = await self.downloader.download_aweme(aweme, target.name)
                stats["downloaded"] += 1
                metadata = self._video_metadata(aweme, target.name, target.sec_uid)
                transcript = await self.transcriber.transcribe(aweme_id, video_path, metadata)
                if transcript.get("status") != "success":
                    stats["failed"] += 1
                    self.alerts.error(
                        "whisper",
                        str(transcript.get("error") or "Whisper 转录失败"),
                        aweme_id=aweme_id,
                        title=str(title),
                        context={"video_path": str(video_path)},
                    )
                    continue
                stats["transcribed"] += 1
                processed.append(
                    {
                        "aweme_id": aweme_id,
                        "title": str(title),
                        "create_time": self._format_timestamp(aweme.get("create_time")),
                        "text_path": str(transcript.get("text_path") or ""),
                        "text": str(transcript.get("text") or ""),
                        "summary": "",
                        "url": f"https://www.douyin.com/video/{aweme_id}",
                        "blogger_name": target.name,
                        "blogger_id": str(target.sec_uid),
                        "transcript_file": str(transcript.get("text_path") or ""),
                    }
                )
            except Exception as exc:
                stats["failed"] += 1
                self.database.update_aweme_download(aweme_id, "failed")
                logger.exception("处理作品失败 aweme_id=%s", aweme_id)
                self.alerts.error("download", str(exc), aweme_id=aweme_id, title=str(title))

        if processed:
            backfill_path = self._write_backfill_summary(target.name, processed)
            stats["summary_path"] = str(backfill_path)
            stats["html_url"] = self._publish_markdown(backfill_path, target.name)
        return stats

    async def summarize_existing(self, limit: int = 0) -> dict[str, Any]:
        rows = self.database.list_transcripts_missing_summary(limit=limit)
        stats = {"found": len(rows), "summarized": 0, "failed": 0}
        for row in rows:
            result = self._summarize_transcript_row(row, workflow_name="summarize_existing")
            stats["summarized" if result.get("status") == "success" else "failed"] += 1
        return stats

    async def research_blogger(
        self,
        blogger: str,
        limit: int = 0,
        push: bool = False,
        force: bool = False,
        since: str = "",
        until: str = "",
    ) -> dict[str, Any]:
        target = self._resolve_research_target(blogger)
        job_id = self.database.create_research_job(
            platform="douyin",
            blogger_id=target.id,
            blogger_name=target.name,
            limit_count=limit,
            since_time=since or None,
            until_time=until or None,
            push_enabled=push,
            force_enabled=force,
        )
        stats: dict[str, Any] = {
            "job_id": job_id,
            "blogger": target.name,
            "fetched": 0,
            "queued": 0,
            "processed": 0,
            "skipped": 0,
            "failed": 0,
            "pushed": False,
        }
        pipeline_mode = str(self.config.get("pipeline.mode", "realtime") or "realtime").strip().lower()
        pushed_items: list[dict[str, Any]] = []
        self.database.update_research_job(job_id, status="running", started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        try:
            logger.info("研究博主开始: job_id=%s blogger=%s limit=%s force=%s since=%s until=%s order=new_to_old", job_id, target.name, limit, force, since, until)
            fetch_limit = limit if limit > 0 else 0
            awemes = await self.checker.fetch_aweme_history(target, limit=fetch_limit)
            awemes = self._filter_awemes_by_time(awemes, since, until)
            if limit > 0:
                awemes = awemes[:limit]
            target = self._target_with_discovered_name(target, awemes)
            stats["blogger"] = target.name
            self.database.update_research_job(job_id, blogger_name=target.name)
            stats["fetched"] = len(awemes)
            stats["queued"] = len(awemes)
            self.database.update_research_job(job_id, total_count=len(awemes), pending_count=len(awemes))

            candidates: list[dict[str, Any]] = []
            for aweme in awemes:
                aweme_id = str(aweme.get("aweme_id") or "")
                if not aweme_id:
                    continue
                if not force and self.database.is_aweme_fully_processed(aweme_id):
                    stats["skipped"] += 1
                    self.database.upsert_research_job_item(job_id, aweme_id, "skipped")
                    self._update_research_counts(job_id, stats, len(awemes))
                    continue
                self.database.upsert_research_job_item(job_id, aweme_id, "pending")
                candidates.append(aweme)

            pushed_items = await self._run_research_pipeline(job_id, target, candidates, awemes, stats)
            if self._research_job_cancelled(job_id):
                self.database.update_research_job(
                    job_id,
                    status="cancelled",
                    pending_count=0,
                    success_count=stats["processed"],
                    failed_count=stats["failed"],
                    skipped_count=stats["skipped"],
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_error="用户取消研究任务",
                )
                stats["cancelled"] = True
                logger.info("研究博主已取消: %s", stats)
                return stats

            if pipeline_mode == "transcribe_only_gpu":
                final_status = "transcribe_only_completed" if not stats["failed"] else ("transcribe_only_partial_failed" if stats["processed"] else "failed")
                self.database.update_research_job(
                    job_id,
                    status=final_status,
                    pending_count=0,
                    success_count=stats["processed"],
                    failed_count=stats["failed"],
                    skipped_count=stats["skipped"],
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_error="" if final_status != "failed" else "GPU 转录清积压任务失败",
                )
                logger.info("研究博主 GPU 转录清积压完成: %s", stats)
                return stats

            final_status = "completed"
            if stats["failed"] and stats["processed"]:
                final_status = "partial_failed"
            elif stats["failed"] and not stats["processed"]:
                final_status = "failed"
            report_path = ""
            report_url = ""
            if final_status in {"completed", "partial_failed"}:
                report = self._write_research_report(job_id, target, stats, pushed_items)
                report_path = str(report)
                report_url = self._publish_markdown(report, target.name)
                stats["report_path"] = report_path
                stats["report_url"] = report_url
                stats.update(self.publish_research_job(job_id))
            if push and pipeline_mode != "transcribe_only_gpu":
                stats["pushed"] = self.pusher.push_research_summary(job_id, target.name, stats)
            self.database.update_research_job(
                job_id,
                status=final_status,
                pending_count=0,
                success_count=stats["processed"],
                failed_count=stats["failed"],
                skipped_count=stats["skipped"],
                report_path=report_path,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_error="" if final_status in {"completed", "partial_failed"} else "研究任务失败",
            )
            logger.info("研究博主完成: %s", stats)
            return stats
        except Exception as exc:
            self.database.update_research_job(
                job_id,
                status="failed",
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                last_error=str(exc),
            )
            self.alerts.error("research", str(exc), title=target.name, context={"job_id": job_id})
            raise

    async def research_video(
        self,
        video: str = "",
        aweme_id: str = "",
        push: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        resolved = await resolve_douyin_video(self.config, video, aweme_id=aweme_id)
        source_url = resolved.url or f"https://www.douyin.com/video/{resolved.aweme_id}"
        creator_uid = resolved.sec_uid or f"single_video:{resolved.aweme_id}"
        profile_url = f"https://www.douyin.com/user/{resolved.sec_uid}" if resolved.sec_uid else source_url
        blogger_id = self.database.upsert_blogger(
            url=profile_url,
            name=resolved.name,
            sec_uid=creator_uid,
            enabled=False,
        )
        self.database.insert_aweme(blogger_id, resolved.aweme, status="pending")

        if not force and self.database.is_aweme_fully_processed(resolved.aweme_id):
            row = self._load_aweme_for_retry(resolved.aweme_id)
            summary = self.database.get_summary(resolved.aweme_id) or {}
            return {
                "aweme_id": resolved.aweme_id,
                "status": "skipped",
                "message": "该视频已完整归档，已复用现有结果",
                "title": str(row.get("title") or resolved.aweme_id),
                "blogger_name": str(row.get("nickname") or resolved.name),
                "summary_path": str(summary.get("summary_path") or ""),
                "detail_url": self._detail_url(resolved.aweme_id),
                "url": source_url,
                "pushed": False,
            }

        item = await self._process_aweme_for_push(
            resolved.aweme,
            resolved.name,
            resolved.sec_uid or creator_uid,
            workflow_name="research_video",
        )
        if not item:
            return {
                "aweme_id": resolved.aweme_id,
                "status": "failed",
                "message": "单视频研究失败，请查看系统告警或运行日志",
                "url": source_url,
                "pushed": False,
            }

        pushed = False
        if push:
            pushed = self.pusher.push([item])
            if not pushed:
                self.alerts.error("feishu_push", "单视频研究结果推送失败", aweme_id=resolved.aweme_id, title=str(item.get("title") or ""), context={"workflow": "research_video"})
        return {
            "aweme_id": resolved.aweme_id,
            "status": "success" if str(item.get("summary_status") or "") == "success" else "partial_failed",
            "title": item.get("title"),
            "blogger_name": item.get("blogger_name"),
            "summary_status": item.get("summary_status"),
            "summary_path": item.get("summary_path"),
            "transcript_file": item.get("transcript_file"),
            "detail_url": item.get("detail_url"),
            "url": source_url,
            "pushed": pushed,
        }

    async def _run_research_pipeline(
        self,
        job_id: int,
        target: BloggerTarget,
        candidates: list[dict[str, Any]],
        awemes: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> list[dict[str, Any]]:
        pipeline_mode = str(self.config.get("pipeline.mode", "realtime") or "realtime").strip().lower()
        if pipeline_mode in {"staged_gpu", "turbo", "time_division", "time_division_gpu"}:
            return await self._run_research_pipeline_staged_gpu(job_id, target, candidates, awemes, stats)

        max_workers = max(1, int(self.config.get("download.max_workers", 2) or 2))
        transcribe_only_gpu = pipeline_mode == "transcribe_only_gpu"
        enable_llm_worker = bool(self.config.get("pipeline.enable_llm_worker", True)) and not transcribe_only_gpu
        if not bool(self.config.get("gpu_scheduler.ollama.enabled", True)):
            enable_llm_worker = False
        configured_batch_size = self.config.get("download.batch_size", max_workers * 3)
        if self.config.get("gpu_scheduler.batch.enabled", True):
            configured_batch_size = self.config.get("gpu_scheduler.batch.download_batch_size", configured_batch_size)
        batch_size = max(1, int(configured_batch_size or max_workers * 3))
        batch_cooldown = max(0.0, float(self.config.get("download.batch_cooldown", 3) or 0))
        retry_failed_downloads = bool(self.config.get("download.retry_failed", True))
        circuit_threshold = max(1, int(self.config.get("download.circuit_breaker_failures", 3) or 3))
        circuit_cooldown = max(0.0, float(self.config.get("download.circuit_breaker_cooldown", 30) or 0))
        max_download_backlog = max(1, int(self.config.get("download.max_transcript_backlog", 20) or 20))
        max_ai_backlog = max(1, int(self.config.get("ai.organizer.max_queue_backlog", 8) or 8))
        transcribe_workers = max(1, int(self.config.get("transcribe.workers", self.config.get("gpu_scheduler.batch.transcription_workers", 2)) or 2))
        if transcribe_only_gpu:
            requested_gpu_workers = max(1, int(self.config.get("transcribe.gpu_workers", self.config.get("ai.whisper.gpu_workers", 1)) or 1))
            if requested_gpu_workers != 1:
                logger.warning("transcribe_only_gpu 模式强制只启动 1 个 GPU Whisper worker: configured=%s effective=1", requested_gpu_workers)
            transcribe_workers = 1
        transcribe_retry_limit = max(0, int(self.config.get("transcribe.retry_limit", self.config.get("ai.whisper.retry_limit", 2)) or 0))
        transcribe_timeout = max(60, int(float(self.config.get("transcribe.max_runtime_minutes", self.config.get("ai.whisper.max_runtime_minutes", 60)) or 60) * 60))
        max_downloaded_waiting_transcribe = max(1, int(self.config.get("pipeline.max_downloaded_waiting_transcribe", max_download_backlog) or max_download_backlog))
        max_transcribed_waiting_summarize = max(1, int(self.config.get("pipeline.max_transcribed_waiting_summarize", max_ai_backlog) or max_ai_backlog))
        stale_reset_minutes = max(1, int(self.config.get("transcribe.stale_reset_minutes", self.config.get("ai.whisper.stale_reset_minutes", 90)) or 90))
        download_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        transcript_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=max(max_download_backlog, max_downloaded_waiting_transcribe))
        ai_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=max(max_ai_backlog, max_transcribed_waiting_summarize))
        pushed_items: list[dict[str, Any]] = []
        total = len(awemes)
        download_fail_count = 0
        download_fail_lock = asyncio.Lock()
        download_circuit_breaker = asyncio.Event()
        download_circuit_breaker.set()
        self._reset_stale_research_items(job_id, stale_reset_minutes)
        self._reset_stale_transcripts(stale_reset_minutes)
        gpu = GpuResourceManager(self.config)
        if transcribe_only_gpu:
            gpu.prepare_whisper_exclusive()
        whisper_model = str(self.config.get("transcribe.model", self.config.get("ai.whisper.model", "")) or "")
        whisper_device = str(self.config.get("transcribe.device", self.config.get("ai.whisper.device", "")) or "")
        whisper_compute = str(self.config.get("transcribe.compute_type", self.config.get("ai.whisper.compute_type", "")) or "")
        whisper_batch = int(self.config.get("transcribe.batch_size", self.config.get("ai.whisper.batch_size", 1)) or 1)
        logger.info(
            "研究流水线运行模式: job_id=%s pipeline.mode=%s whisper_model=%s whisper_device=%s compute_type=%s batch_size=%s llm_worker_enabled=%s gpu_free_vram=%sMB ollama_loaded=%s",
            job_id,
            pipeline_mode,
            whisper_model,
            whisper_device,
            whisper_compute,
            whisper_batch,
            enable_llm_worker,
            gpu.free_vram_mb(),
            gpu.llm_is_loaded(),
        )

        logger.info(
            "研究博主采用 Queue 流水线: job_id=%s candidates=%s download_workers=%s transcribe_workers=%s batch_size=%s cooldown=%ss transcript_backlog=%s ai_backlog=%s retry_failed=%s circuit=%s/%ss transcribe_timeout=%ss transcribe_retry=%s llm_worker_enabled=%s",
            job_id,
            len(candidates),
            max_workers,
            transcribe_workers,
            batch_size,
            batch_cooldown,
            max_download_backlog,
            max_ai_backlog,
            retry_failed_downloads,
            circuit_threshold,
            circuit_cooldown,
            transcribe_timeout,
            transcribe_retry_limit,
            enable_llm_worker,
        )

        async def wait_for_backpressure(queue: asyncio.Queue[Any], threshold: int, worker_type: str, worker_id: int) -> None:
            logged = False
            while queue.qsize() >= threshold and not self._research_job_cancelled(job_id):
                if not logged:
                    logger.warning(
                        "流水线背压触发: job_id=%s worker_type=%s worker=%s queue_size=%s threshold=%s",
                        job_id,
                        worker_type,
                        worker_id,
                        queue.qsize(),
                        threshold,
                    )
                    logged = True
                await asyncio.sleep(max(1.0, min(5.0, batch_cooldown or 2.0)))

        def log_pipeline_snapshot(reason: str) -> None:
            logger.info(
                "[pipeline_status] job_id=%s reason=%s pending=%s downloaded_waiting_transcribe=%s transcribed_waiting_summarize=%s done=%s failed=%s",
                job_id,
                reason,
                download_queue.qsize(),
                transcript_queue.qsize(),
                ai_queue.qsize(),
                int(stats.get("processed", 0)) + int(stats.get("skipped", 0)),
                int(stats.get("failed", 0)),
            )

        async def producer() -> None:
            try:
                for batch_index, batch in enumerate(self._iter_chunks(candidates, batch_size), start=1):
                    if not await self._wait_research_job_resumed(job_id):
                        break
                    if self._research_job_cancelled(job_id):
                        break
                    logger.info("研究博主入队批次: job_id=%s batch=%s size=%s", job_id, batch_index, len(batch))
                    for aweme in batch:
                        await download_queue.put(aweme)
                    if batch_cooldown > 0 and batch_index * batch_size < len(candidates):
                        await asyncio.sleep(batch_cooldown)
            finally:
                for _ in range(max_workers):
                    await download_queue.put(None)

        async def download_worker(worker_id: int) -> None:
            while True:
                aweme = await download_queue.get()
                try:
                    if aweme is None:
                        return
                    if not await self._wait_research_job_resumed(job_id):
                        self.database.upsert_research_job_item(job_id, str(aweme.get("aweme_id") or ""), "cancelled", "用户取消研究任务")
                        continue
                    await download_circuit_breaker.wait()
                    aweme_id = str(aweme.get("aweme_id") or "")
                    title = str(aweme.get("desc") or aweme.get("title") or "无标题")
                    if self._research_job_cancelled(job_id):
                        self.database.upsert_research_job_item(job_id, aweme_id, "cancelled", "用户取消研究任务")
                        continue
                    existing_transcript = self.database.get_successful_transcript(aweme_id)
                    if existing_transcript:
                        logger.info("研究博主跳过下载和转录，复用已有转录: job_id=%s aweme_id=%s", job_id, aweme_id)
                        if enable_llm_worker:
                            await wait_for_backpressure(ai_queue, max_transcribed_waiting_summarize, "download", worker_id)
                            await ai_queue.put({"aweme": aweme, "transcript": self._transcript_payload(existing_transcript)})
                        else:
                            self._mark_research_item(job_id, aweme_id, "transcribed_waiting_summary", "pipeline.mode=transcribe_only_gpu")
                            stats["processed"] += 1
                            self._update_research_counts(job_id, stats, total)
                        continue
                    existing_video_path = self._find_existing_downloaded_video(aweme_id)
                    if existing_video_path is not None:
                        logger.info("研究博主复用已下载视频，直接进入转录队列: job_id=%s aweme_id=%s path=%s", job_id, aweme_id, existing_video_path)
                        self.database.update_aweme_download(aweme_id, "done", str(existing_video_path))
                        self._mark_research_item(job_id, aweme_id, "downloaded")
                        await wait_for_backpressure(transcript_queue, max_downloaded_waiting_transcribe, "download", worker_id)
                        await transcript_queue.put({"aweme": aweme, "video_path": existing_video_path})
                        continue
                    try:
                        self._mark_research_item(job_id, aweme_id, "downloading")
                        video_path = await self.downloader.download_aweme(aweme, target.name)
                    except Exception as exc:
                        if retry_failed_downloads and not self._research_job_cancelled(job_id):
                            logger.warning("研究博主下载失败，单条降速重试: job_id=%s worker=%s aweme_id=%s", job_id, worker_id, aweme_id)
                            await asyncio.sleep(max(2.0, batch_cooldown))
                            try:
                                video_path = await self.downloader.download_aweme(aweme, target.name)
                            except Exception as retry_exc:
                                self._fail_research_item(job_id, aweme_id, title, "download", str(retry_exc), stats, total)
                                await register_download_failure()
                                continue
                        else:
                            self._fail_research_item(job_id, aweme_id, title, "download", str(exc), stats, total)
                            await register_download_failure()
                            continue
                    self._mark_research_item(job_id, aweme_id, "downloaded")
                    await reset_download_failures()
                    await wait_for_backpressure(transcript_queue, max_downloaded_waiting_transcribe, "download", worker_id)
                    await transcript_queue.put({"aweme": aweme, "video_path": video_path})
                finally:
                    download_queue.task_done()

        async def reset_download_failures() -> None:
            nonlocal download_fail_count
            async with download_fail_lock:
                download_fail_count = 0

        async def register_download_failure() -> None:
            nonlocal download_fail_count
            should_pause = False
            async with download_fail_lock:
                download_fail_count += 1
                should_pause = download_fail_count >= circuit_threshold
                if should_pause:
                    logger.warning("连续 %s 次下载失败，全局暂停 %.1f 秒后继续", download_fail_count, circuit_cooldown)
                    download_fail_count = 0
                    download_circuit_breaker.clear()
            if should_pause and circuit_cooldown > 0:
                await asyncio.sleep(circuit_cooldown)
                download_circuit_breaker.set()
            elif should_pause:
                download_circuit_breaker.set()

        async def transcribe_with_retries(worker_id: int, aweme_id: str, video_path: Path, metadata: dict[str, Any], local_transcriber: Transcriber) -> dict[str, Any]:
            last_result: dict[str, Any] = {"status": "failed", "error": "whisper_transcribe_failed"}
            for attempt in range(1, transcribe_retry_limit + 2):
                try:
                    started = asyncio.get_running_loop().time()
                    result = await asyncio.wait_for(local_transcriber.transcribe(aweme_id, video_path, metadata), timeout=transcribe_timeout)
                    elapsed = asyncio.get_running_loop().time() - started
                    result["retry_count"] = attempt - 1
                    logger.info(
                        "[transcribe_worker_%s] done item_id=%s elapsed=%.1fs status=%s retry=%s fail_reason=%s",
                        worker_id,
                        aweme_id,
                        elapsed,
                        result.get("status"),
                        attempt - 1,
                        result.get("fail_reason", ""),
                    )
                    return result
                except asyncio.TimeoutError:
                    last_result = {"status": "failed", "error": f"whisper_timeout: 超过 {transcribe_timeout}s", "fail_reason": "whisper_timeout", "retry_count": attempt - 1}
                    logger.warning("[transcribe_worker_%s] timeout item_id=%s attempt=%s timeout=%ss", worker_id, aweme_id, attempt, transcribe_timeout)
                except Exception as exc:
                    reason = self._classify_transcribe_error(exc)
                    last_result = {"status": "failed", "error": f"{reason}: {exc}", "fail_reason": reason, "retry_count": attempt - 1}
                    logger.warning("[transcribe_worker_%s] failed item_id=%s attempt=%s fail_reason=%s error=%s", worker_id, aweme_id, attempt, reason, exc)
                if attempt <= transcribe_retry_limit:
                    await asyncio.sleep(min(10.0, 2.0 * attempt))
            return last_result

        async def transcribe_worker(worker_id: int) -> None:
            local_transcriber = Transcriber(self.config, self.database)
            while True:
                payload = await transcript_queue.get()
                try:
                    if payload is None:
                        return
                    if not await self._wait_research_job_resumed(job_id):
                        aweme = payload["aweme"]
                        self.database.upsert_research_job_item(job_id, str(aweme.get("aweme_id") or ""), "cancelled", "用户取消研究任务")
                        continue
                    aweme = payload["aweme"]
                    video_path = Path(str(payload["video_path"]))
                    aweme_id = str(aweme.get("aweme_id") or "")
                    title = str(aweme.get("desc") or aweme.get("title") or "无标题")
                    if self._research_job_cancelled(job_id):
                        self.database.upsert_research_job_item(job_id, aweme_id, "cancelled", "用户取消研究任务")
                        continue
                    existing_transcript = self.database.get_successful_transcript(aweme_id)
                    if existing_transcript:
                        logger.info("研究博主跳过重复转录，复用已有转录: job_id=%s aweme_id=%s", job_id, aweme_id)
                        if enable_llm_worker:
                            await wait_for_backpressure(ai_queue, max_transcribed_waiting_summarize, "transcribe", worker_id)
                            await ai_queue.put({"aweme": aweme, "transcript": self._transcript_payload(existing_transcript), "video_path": str(video_path)})
                        else:
                            self._mark_research_item(job_id, aweme_id, "transcribed_waiting_summary", "pipeline.mode=transcribe_only_gpu")
                            stats["processed"] += 1
                            self._update_research_counts(job_id, stats, total)
                        continue
                    metadata = self._video_metadata(aweme, target.name, target.sec_uid)
                    self._mark_research_item(job_id, aweme_id, "transcribing")
                    if enable_llm_worker:
                        await wait_for_backpressure(ai_queue, max_transcribed_waiting_summarize, "transcribe", worker_id)
                    transcript = await transcribe_with_retries(worker_id, aweme_id, video_path, metadata, local_transcriber)
                    if transcript.get("status") != "success":
                        error = str(transcript.get("error") or "Whisper 转录失败")
                        self._fail_research_item(job_id, aweme_id, title, "whisper", error, stats, total, {"video_path": str(video_path)})
                        continue
                    if enable_llm_worker:
                        await ai_queue.put({"aweme": aweme, "transcript": transcript, "video_path": str(video_path)})
                    else:
                        duration = float(transcript.get("duration") or (transcript.get("segments") or {}).get("duration") or 0.0)
                        elapsed = float(transcript.get("elapsed") or 0.0)
                        next_status = "transcribed_waiting_summary"
                        self._mark_research_item(job_id, aweme_id, next_status, "pipeline.mode=transcribe_only_gpu")
                        stats["processed"] += 1
                        self._update_research_counts(job_id, stats, total)
                        logger.info(
                            "[transcribe_gpu_worker] done worker_id=%s item_id=%s duration=%.1fs elapsed=%.1fs rtf=%.2fx model=%s device=%s compute=%s batch=%s text_chars=%s vad_retry=%s next_status=%s",
                            worker_id,
                            aweme_id,
                            duration,
                            elapsed,
                            (duration / elapsed) if elapsed > 0 else 0.0,
                            transcript.get("model") or whisper_model,
                            transcript.get("device") or whisper_device,
                            transcript.get("compute_type") or whisper_compute,
                            transcript.get("batch_size") or whisper_batch,
                            len(str(transcript.get("text") or "")),
                            bool(transcript.get("vad_retry")),
                            next_status,
                        )
                    log_pipeline_snapshot(f"transcribed:{aweme_id}")
                finally:
                    transcript_queue.task_done()

        async def ai_worker() -> None:
            while True:
                payload = await ai_queue.get()
                try:
                    if payload is None:
                        return
                    if not await self._wait_research_job_resumed(job_id):
                        aweme = payload["aweme"]
                        self.database.upsert_research_job_item(job_id, str(aweme.get("aweme_id") or ""), "cancelled", "用户取消研究任务")
                        continue
                    aweme = payload["aweme"]
                    transcript = payload["transcript"]
                    aweme_id = str(aweme.get("aweme_id") or "")
                    title = str(aweme.get("desc") or aweme.get("title") or "无标题")
                    if self._research_job_cancelled(job_id):
                        self.database.upsert_research_job_item(job_id, aweme_id, "cancelled", "用户取消研究任务")
                        continue
                    text = str(transcript.get("text") or "")
                    self._mark_research_item(job_id, aweme_id, "summarizing")
                    metadata = self._video_metadata(aweme, target.name, target.sec_uid)
                    summary_text = await asyncio.to_thread(self.organizer.organize, title, text, metadata)
                    summary_status = "success"
                    organizer_error = self.organizer.last_error
                    if organizer_error:
                        if self._is_ollama_gpu_required_error(organizer_error):
                            self._fail_research_item(job_id, aweme_id, title, "ollama_gpu", organizer_error, stats, total)
                            self.database.update_research_job(
                                job_id,
                                status="paused",
                                last_error=organizer_error,
                            )
                            self.alerts.error(
                                "ollama_gpu",
                                organizer_error,
                                aweme_id=aweme_id,
                                title=title,
                                context={"workflow": f"research_blog_{job_id}", "action": "paused_ai_queue"},
                            )
                            logger.error("Ollama GPU 强制检查失败，已暂停 AI 队列: job_id=%s aweme_id=%s error=%s", job_id, aweme_id, organizer_error)
                            continue
                        summary_status = "failed"
                        self.alerts.error("openai_api", organizer_error, aweme_id=aweme_id, title=title, context={"workflow": f"research_blog_{job_id}"})
                    self._mark_research_item(job_id, aweme_id, "noting")
                    summary_path = self._write_item_summary(
                        aweme_id,
                        title,
                        summary_text,
                        text,
                        metadata,
                        str(transcript.get("text_path") or ""),
                        summary_status,
                    )
                    html_url = self._publish_markdown(summary_path, title)
                    self.database.upsert_summary(
                        aweme_id=aweme_id,
                        summary_text=summary_text,
                        summary_path=str(summary_path),
                        model=str(self.config.get("ai.organizer.model", "")),
                        status=summary_status,
                        error_message=organizer_error,
                    )
                    self._cleanup_download_artifacts(
                        aweme_id,
                        video_path=Path(str(payload["video_path"])) if payload.get("video_path") else None,
                        transcript=transcript,
                    )
                    item = {
                        "aweme_id": aweme_id,
                        "blogger_name": target.name,
                        "title": title,
                        "create_time": self._format_timestamp(aweme.get("create_time")),
                        "text": summary_text,
                        "transcript": text,
                        "summary_status": summary_status,
                        "summary_path": str(summary_path),
                        "html_url": html_url,
                        "transcript_file": str(transcript.get("text_path") or ""),
                        "url": f"https://www.douyin.com/video/{aweme_id}",
                        "detail_url": self._detail_url(aweme_id),
                    }
                    stats["processed"] += 1
                    pushed_items.append(item)
                    self.database.upsert_research_job_item(job_id, aweme_id, "success")
                    self._update_research_counts(job_id, stats, total)
                except Exception as exc:
                    aweme = payload.get("aweme", {}) if isinstance(payload, dict) else {}
                    aweme_id = str(aweme.get("aweme_id") or "")
                    title = str(aweme.get("desc") or aweme.get("title") or "无标题")
                    self._fail_research_item(job_id, aweme_id, title, "research", str(exc), stats, total)
                    logger.exception("研究博主 AI/笔记阶段失败: job_id=%s aweme_id=%s", job_id, aweme_id)
                finally:
                    ai_queue.task_done()

        producer_task = asyncio.create_task(producer())
        download_tasks = [asyncio.create_task(download_worker(index + 1)) for index in range(max_workers)]
        transcribe_tasks = [asyncio.create_task(transcribe_worker(index + 1)) for index in range(transcribe_workers)]
        ai_task = asyncio.create_task(ai_worker()) if enable_llm_worker else None
        await producer_task
        await download_queue.join()
        for _ in range(transcribe_workers):
            await transcript_queue.put(None)
        await transcript_queue.join()
        await asyncio.gather(*transcribe_tasks)
        if ai_task is not None:
            await ai_queue.put(None)
            await ai_queue.join()
            await asyncio.gather(*download_tasks, ai_task)
        else:
            await asyncio.gather(*download_tasks)
        return pushed_items

    async def _run_research_pipeline_staged_gpu(
        self,
        job_id: int,
        target: BloggerTarget,
        candidates: list[dict[str, Any]],
        awemes: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> list[dict[str, Any]]:
        total = len(awemes)
        logger.info("研究流水线进入 staged GPU 模式: job_id=%s candidates=%s", job_id, len(candidates))
        previous_config = self.config
        previous_transcriber = self.transcriber
        qwen_asr_enabled = bool(self.config.get("ai.qwen_asr.enabled", False))
        phase_overrides: dict[str, Any] = {
            "pipeline.mode": "transcribe_only_gpu",
            "pipeline.enable_llm_worker": False,
        }
        if qwen_asr_enabled:
            phase_overrides.update(
                {
                    "transcribe.device": "cpu",
                    "transcribe.compute_type": self.config.get("ai.whisper.cpu_compute_type", "int8"),
                    "ai.whisper.device": "cpu",
                    "ai.whisper.compute_type": self.config.get("ai.whisper.cpu_compute_type", "int8"),
                    "gpu_scheduler.whisper.allow_gpu": False,
                    "gpu_scheduler.whisper.default_device": "cpu",
                }
            )
        else:
            phase_overrides.update(
                {
                    "gpu_scheduler.mode": "whisper_exclusive",
                    "gpu_scheduler.whisper.allow_gpu": True,
                    "gpu_scheduler.whisper.default_device": "cuda",
                    "transcribe.device": "cuda",
                    "transcribe.compute_type": self.config.get("gpu_scheduler.turbo.whisper_compute_type", "float16"),
                    "ai.whisper.device": "cuda",
                    "ai.whisper.compute_type": self.config.get("gpu_scheduler.turbo.whisper_compute_type", "float16"),
                }
            )
        phase_config = self._config_with_overrides(phase_overrides)
        phase_processed_start = int(stats.get("processed", 0))
        try:
            self.config = phase_config
            self.transcriber = Transcriber(phase_config, self.database)
            if qwen_asr_enabled:
                logger.info("staged 转录阶段使用 Qwen3-ASR 优先、Whisper CPU 回退: job_id=%s", job_id)
            else:
                GpuResourceManager(phase_config).prepare_turbo_whisper_phase()
            await self._run_research_pipeline(job_id, target, candidates, awemes, stats)
        finally:
            try:
                self.transcriber.release_model()
            finally:
                self.config = previous_config
                self.transcriber = previous_transcriber

        transcribed_count = max(0, int(stats.get("processed", 0)) - phase_processed_start)
        stats["processed"] = phase_processed_start
        self._update_research_counts(job_id, stats, total)
        qwen_asr_was_stopped = False
        if qwen_asr_enabled:
            qwen_asr_was_stopped = self._stop_qwen_asr_for_llm(job_id)
        GpuResourceManager(self.config).prepare_turbo_llm_phase()
        logger.info("staged GPU 转录阶段完成: job_id=%s transcribed_or_reused=%s failed=%s", job_id, transcribed_count, stats.get("failed", 0))
        if self._research_job_cancelled(job_id):
            return []
        try:
            return await self._run_research_ai_phase(job_id, target, candidates, awemes, stats)
        finally:
            if qwen_asr_was_stopped:
                GpuResourceManager(self.config).unload_ollama_models()
                self._start_qwen_asr_after_llm(job_id)

    def _qwen_asr_container_name(self) -> str:
        return str(self.config.get("ai.qwen_asr.container_name", "kenradar-qwen3-asr") or "kenradar-qwen3-asr").strip()

    def _stop_qwen_asr_for_llm(self, job_id: int) -> bool:
        if not bool(self.config.get("ai.qwen_asr.stop_before_llm", True)):
            return False
        name = self._qwen_asr_container_name()
        if not name:
            return False
        try:
            inspect = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if inspect.returncode != 0 or inspect.stdout.strip().lower() != "true":
                return False
            subprocess.run(["docker", "stop", name], check=True, capture_output=True, text=True, timeout=60)
            logger.info("为 Ollama AI 阶段停止 Qwen3-ASR 容器: job_id=%s container=%s", job_id, name)
            return True
        except Exception as exc:
            message = f"停止 Qwen3-ASR 容器失败: {exc}"
            logger.warning("%s job_id=%s container=%s", message, job_id, name)
            self.alerts.error("qwen_asr", message, title=f"研究任务 #{job_id}", context={"job_id": job_id, "container": name})
            return False

    def _start_qwen_asr_after_llm(self, job_id: int) -> None:
        if not bool(self.config.get("ai.qwen_asr.restart_after_llm", True)):
            return
        name = self._qwen_asr_container_name()
        if not name:
            return
        try:
            subprocess.run(["docker", "start", name], check=True, capture_output=True, text=True, timeout=60)
            logger.info("AI 阶段结束后恢复 Qwen3-ASR 容器: job_id=%s container=%s", job_id, name)
        except Exception as exc:
            message = f"恢复 Qwen3-ASR 容器失败: {exc}"
            logger.warning("%s job_id=%s container=%s", message, job_id, name)
            self.alerts.error("qwen_asr", message, title=f"研究任务 #{job_id}", context={"job_id": job_id, "container": name})

    async def _run_research_ai_phase(
        self,
        job_id: int,
        target: BloggerTarget,
        candidates: list[dict[str, Any]],
        awemes: list[dict[str, Any]],
        stats: dict[str, Any],
    ) -> list[dict[str, Any]]:
        pushed_items: list[dict[str, Any]] = []
        total = len(awemes)
        for aweme in candidates:
            if not await self._wait_research_job_resumed(job_id):
                self.database.upsert_research_job_item(job_id, str(aweme.get("aweme_id") or ""), "cancelled", "用户取消研究任务")
                continue
            aweme_id = str(aweme.get("aweme_id") or "")
            title = str(aweme.get("desc") or aweme.get("title") or "无标题")
            if self._research_job_cancelled(job_id):
                self.database.upsert_research_job_item(job_id, aweme_id, "cancelled", "用户取消研究任务")
                continue
            transcript_row = self.database.get_successful_transcript(aweme_id)
            if not transcript_row:
                logger.info("staged GPU AI 阶段跳过无成功转录条目: job_id=%s aweme_id=%s", job_id, aweme_id)
                continue
            transcript = self._transcript_payload(transcript_row)
            text = str(transcript.get("text") or "")
            try:
                self._mark_research_item(job_id, aweme_id, "summarizing")
                metadata = self._video_metadata(aweme, target.name, target.sec_uid)
                summary_text = await asyncio.to_thread(self.organizer.organize, title, text, metadata)
                summary_status = "success"
                organizer_error = self.organizer.last_error
                if organizer_error:
                    if self._is_ollama_gpu_required_error(organizer_error):
                        self._fail_research_item(job_id, aweme_id, title, "ollama_gpu", organizer_error, stats, total)
                        self.database.update_research_job(job_id, status="paused", last_error=organizer_error)
                        self.alerts.error(
                            "ollama_gpu",
                            organizer_error,
                            aweme_id=aweme_id,
                            title=title,
                            context={"workflow": f"research_blog_{job_id}", "action": "paused_ai_queue"},
                        )
                        logger.error("Ollama GPU 强制检查失败，已暂停 staged AI 阶段: job_id=%s aweme_id=%s error=%s", job_id, aweme_id, organizer_error)
                        continue
                    summary_status = "failed"
                    self.alerts.error("openai_api", organizer_error, aweme_id=aweme_id, title=title, context={"workflow": f"research_blog_{job_id}"})
                self._mark_research_item(job_id, aweme_id, "noting")
                summary_path = self._write_item_summary(
                    aweme_id,
                    title,
                    summary_text,
                    text,
                    metadata,
                    str(transcript.get("text_path") or ""),
                    summary_status,
                )
                html_url = self._publish_markdown(summary_path, title)
                self.database.upsert_summary(
                    aweme_id=aweme_id,
                    summary_text=summary_text,
                    summary_path=str(summary_path),
                    model=str(self.config.get("ai.organizer.model", "")),
                    status=summary_status,
                    error_message=organizer_error,
                )
                self._cleanup_download_artifacts(aweme_id, transcript=transcript)
                item = {
                    "aweme_id": aweme_id,
                    "blogger_name": target.name,
                    "title": title,
                    "create_time": self._format_timestamp(aweme.get("create_time")),
                    "text": summary_text,
                    "transcript": text,
                    "summary_status": summary_status,
                    "summary_path": str(summary_path),
                    "html_url": html_url,
                    "transcript_file": str(transcript.get("text_path") or ""),
                    "url": f"https://www.douyin.com/video/{aweme_id}",
                    "detail_url": self._detail_url(aweme_id),
                }
                stats["processed"] += 1
                pushed_items.append(item)
                self.database.upsert_research_job_item(job_id, aweme_id, "success")
                self._update_research_counts(job_id, stats, total)
            except Exception as exc:
                self._fail_research_item(job_id, aweme_id, title, "research", str(exc), stats, total)
                logger.exception("staged GPU AI/笔记阶段失败: job_id=%s aweme_id=%s", job_id, aweme_id)
        return pushed_items

    @staticmethod
    def _is_ollama_gpu_required_error(error: str | None) -> bool:
        text = str(error or "")
        return "Ollama GPU 强制模式" in text or "模型未使用 GPU" in text

    def _reset_stale_research_items(self, job_id: int, stale_reset_minutes: int) -> None:
        try:
            with self.database.connect() as conn:
                conn.execute(
                    """
                    UPDATE research_job_item
                    SET status='pending',
                        error_message=COALESCE(error_message || E'\n', '') || %s,
                        updated_at=NOW()
                    WHERE job_id = %s
                      AND status IN ('running', 'downloading', 'downloaded', 'transcribing', 'summarizing', 'noting')
                      AND updated_at < NOW() - (%s * INTERVAL '1 minute')
                    """,
                    (f"stale_reset: 超过 {stale_reset_minutes} 分钟未更新，已重置为可处理状态", job_id, stale_reset_minutes),
                )
        except Exception as exc:
            logger.warning("重置 stale 研究条目失败: job_id=%s error=%s", job_id, exc)

    def _reset_stale_transcripts(self, stale_reset_minutes: int) -> None:
        try:
            with self.database.connect() as conn:
                conn.execute(
                    """
                    UPDATE transcript
                    SET status='failed',
                        error_message=COALESCE(error_message || E'\n', '') || %s,
                        updated_at=NOW()
                    WHERE status = 'running'
                      AND updated_at < NOW() - (%s * INTERVAL '1 minute')
                    """,
                    (f"stale_reset: 超过 {stale_reset_minutes} 分钟未更新，已标记为可重试失败状态", stale_reset_minutes),
                )
        except Exception as exc:
            logger.warning("重置 stale 转录记录失败: error=%s", exc)

    @staticmethod
    def _classify_transcribe_error(exc: BaseException | str) -> str:
        text = str(exc).lower()
        if "timeout" in text or "超时" in text:
            return "whisper_timeout"
        if "not found" in text or "no such file" in text or "不存在" in text:
            return "download_file_missing"
        if "empty" in text or "未产生有效转录文本" in text:
            return "empty_audio"
        if "too short" in text or "过短" in text:
            return "transcript_too_short"
        if (
            "out of memory" in text
            or ("cuda" in text and "memory" in text)
            or "oom" in text
            or "failed to allocate" in text
            or ("target device or backend do not support" in text and any(token in text for token in ("float16", "int8_float16", "cuda")))
        ):
            return "cuda_oom"
        if "audio" in text or "ffmpeg" in text:
            return "audio_extract_failed"
        if "vad" in text:
            return "vad_retry_failed"
        if "whisper" in text:
            return "whisper_transcribe_failed"
        return "unknown_error"

    def _write_research_report(self, job_id: int, target: BloggerTarget, stats: dict[str, Any], processed_items: list[dict[str, Any]]) -> Path:
        output_dir = brief_dir(self.config)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        safe_name = sanitize_filename(target.name or "unknown")
        path = output_dir / f"research_{safe_name}_{timestamp}.md"
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT i.aweme_id, i.status, i.error_message, COALESCE(a.title, i.aweme_id) AS title,
                       a.create_time, s.summary_path
                FROM research_job_item i
                LEFT JOIN aweme a ON a.aweme_id = i.aweme_id
                LEFT JOIN summary s ON s.aweme_id = i.aweme_id
                WHERE i.job_id = %s
                ORDER BY a.create_time DESC, i.id DESC
                """,
                (job_id,),
            ).fetchall()
        success_rows = [dict(row) for row in rows if str(row["status"]) == "success"]
        failed_rows = [dict(row) for row in rows if str(row["status"]) in {"failed", "cancelled"}]
        status_counts: dict[str, int] = {}
        for row in rows:
            status = str(row["status"] or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        lines = [
            f"# 研究报告 | {target.name} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "## 任务概况",
            "",
            f"- 任务 ID: {job_id}",
            f"- 研究博主: {target.name}",
            f"- 抓取作品: {stats.get('fetched', 0)}",
            f"- 处理成功: {stats.get('processed', 0)}",
            f"- 失败: {stats.get('failed', 0)}",
            f"- 跳过: {stats.get('skipped', 0)}",
            "",
            "## 阶段分布",
            "",
            *(f"- {status}: {count}" for status, count in sorted(status_counts.items())),
            "",
            "## 成功条目索引",
            "",
            "| # | 标题 | 发布时间 | 笔记 |",
            "|---|---|---|---|",
        ]
        if success_rows:
            for index, row in enumerate(success_rows, start=1):
                title = self._md_cell(row.get("title"))
                publish_time = self._md_cell(self._format_timestamp(row.get("create_time")))
                note_path = str(row.get("summary_path") or "")
                note_url = self.publisher.public_url_for(note_path) if note_path else ""
                note = f"[{Path(note_path).name}]({note_url or note_path})" if note_path else ""
                lines.append(f"| {index} | {title} | {publish_time} | {self._md_cell(note)} |")
        else:
            lines.append("| - | 暂无 | - | - |")
        lines.extend(["", "## 失败条目", "", "| aweme_id | 标题 | 错误 |", "|---|---|---|"])
        if failed_rows:
            for row in failed_rows:
                lines.append(
                    f"| {self._md_cell(row.get('aweme_id'))} | {self._md_cell(row.get('title'))} | {self._md_cell(row.get('error_message'))} |"
                )
        else:
            lines.append("| - | 暂无 | - |")
        lines.extend(["", "## 系统说明", "", "本报告由 KenRadar 研究博主功能自动生成，完整原稿请进入对应单条内容笔记查看。", ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    async def retry_summary(self, aweme_id: str) -> dict[str, Any]:
        data = self._load_aweme_for_retry(aweme_id)
        if not data.get("text_content") and not data.get("text_path"):
            raise ValueError(f"该作品没有可用转录文本: {aweme_id}")
        return self._summarize_transcript_row(data, workflow_name="retry_summary")

    async def retry_download(self, aweme_id: str) -> dict[str, Any]:
        data = self._load_aweme_for_retry(aweme_id)
        aweme = self._rebuild_aweme_dict(data)
        blogger_name = str(data.get("nickname") or "未知博主")
        blogger_id = str(data.get("blogger_id") or "")
        item = await self._process_aweme_for_push(aweme, blogger_name, blogger_id, workflow_name="retry_download")
        return self._retry_result(aweme_id, item, "retry_download")

    async def retry_transcribe(self, aweme_id: str) -> dict[str, Any]:
        data = self._load_aweme_for_retry(aweme_id)
        video_path = self._find_local_video(aweme_id, data)
        if video_path is None:
            raise ValueError(f"找不到本地视频文件，请先重试下载: {aweme_id}")
        aweme = self._rebuild_aweme_dict(data)
        blogger_name = str(data.get("nickname") or "未知博主")
        blogger_id = str(data.get("blogger_id") or "")
        item = await self._process_aweme_for_push(aweme, blogger_name, blogger_id, workflow_name="retry_transcribe", video_path=video_path)
        return self._retry_result(aweme_id, item, "retry_transcribe")

    async def retry_full_pipeline(self, aweme_id: str) -> dict[str, Any]:
        data = self._load_aweme_for_retry(aweme_id)
        if self._find_local_video(aweme_id, data) is not None:
            return await self.retry_transcribe(aweme_id)
        return await self.retry_download(aweme_id)

    async def retry_batch(self, aweme_ids: list[str], retry_from: str = "auto", on_progress: Any = None) -> dict[str, Any]:
        cleaned = [str(item).strip() for item in aweme_ids if str(item).strip()]
        stats: dict[str, Any] = {"total": len(cleaned), "success": 0, "failed": 0, "items": []}
        for index, aweme_id in enumerate(cleaned, start=1):
            if on_progress:
                on_progress(index, len(cleaned), aweme_id, "resolving", f"正在解析重试阶段 ({index}/{len(cleaned)})")
            try:
                stage = self._resolve_retry_stage(aweme_id, retry_from)
                stage_label = {"download": "下载视频", "transcribe": "Whisper 转录", "ai": "Ollama AI 分析"}.get(stage, stage)
                if on_progress:
                    on_progress(index, len(cleaned), aweme_id, stage, f"正在{stage_label} ({index}/{len(cleaned)})")
                if stage == "download":
                    result = await self.retry_download(aweme_id)
                elif stage == "transcribe":
                    result = await self.retry_transcribe(aweme_id)
                elif stage == "ai":
                    result = await self.retry_summary(aweme_id)
                else:
                    result = await self.retry_full_pipeline(aweme_id)
                ok = str(result.get("status") or "") == "success"
                stats["success" if ok else "failed"] += 1
                stats["items"].append({"aweme_id": aweme_id, "retry_from": stage, **result})
                self._sync_research_items_after_retry(aweme_id, ok, str(result.get("error") or ""))
                if on_progress:
                    status_text = "完成" if ok else "失败"
                    on_progress(index, len(cleaned), aweme_id, "done" if ok else "failed", f"[{status_text}] {aweme_id} ({index}/{len(cleaned)})")
            except Exception as exc:
                stats["failed"] += 1
                stats["items"].append({"aweme_id": aweme_id, "retry_from": retry_from, "status": "failed", "error": str(exc)})
                self._sync_research_items_after_retry(aweme_id, False, str(exc))
                if on_progress:
                    on_progress(index, len(cleaned), aweme_id, "failed", f"[失败] {aweme_id}: {exc} ({index}/{len(cleaned)})")
        if on_progress:
            on_progress(len(cleaned), len(cleaned), "", "completed", f"全部完成: {stats['success']} 成功, {stats['failed']} 失败")
        return stats

    def _sync_research_items_after_retry(self, aweme_id: str, ok: bool, error: str = "") -> None:
        """Reflect content-level retry results in any related research job rows."""
        if not aweme_id:
            return
        status = "success" if ok else "failed"
        error_message = None if ok else (error or "内容级重试失败")
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE research_job_item
                SET status = %s,
                    error_message = %s,
                    updated_at = NOW()
                WHERE aweme_id = %s
                  AND status IN (
                    'failed', 'cancelled', 'pending', 'running', 'downloading', 'downloaded',
                    'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting'
                  )
                """,
                (status, error_message, aweme_id),
            )
            rows = conn.execute(
                """
                SELECT job_id,
                       COUNT(*) AS total_count,
                       COUNT(*) FILTER (WHERE status IN ('pending', 'running', 'downloading', 'downloaded', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting')) AS pending_count,
                       COUNT(*) FILTER (WHERE status = 'success') AS success_count,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                       COUNT(*) FILTER (WHERE status = 'skipped') AS skipped_count
                FROM research_job_item
                WHERE job_id IN (SELECT job_id FROM research_job_item WHERE aweme_id = %s)
                GROUP BY job_id
                """,
                (aweme_id,),
            ).fetchall()
            for row in rows:
                total = int(row["total_count"] or 0)
                pending = int(row["pending_count"] or 0)
                success = int(row["success_count"] or 0)
                failed = int(row["failed_count"] or 0)
                skipped = int(row["skipped_count"] or 0)
                if pending:
                    job_status = "running"
                elif failed and success:
                    job_status = "partial_failed"
                elif failed:
                    job_status = "failed"
                elif success + skipped >= total:
                    job_status = "completed"
                else:
                    job_status = "completed"
                conn.execute(
                    """
                    UPDATE research_job
                    SET total_count = %s,
                        pending_count = %s,
                        success_count = %s,
                        failed_count = %s,
                        skipped_count = %s,
                        status = %s,
                        last_error = CASE WHEN %s = 0 THEN '' ELSE last_error END,
                        finished_at = CASE WHEN %s = 0 THEN COALESCE(finished_at, NOW()) ELSE finished_at END,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (total, pending, success, failed, skipped, job_status, failed, pending, int(row["job_id"])),
                )

    async def refresh_old_notes_with_ollama(self, limit: int = 0, dry_run: bool = False) -> dict[str, Any]:
        """Regenerate legacy Markdown notes with the current Obsidian template via Ollama only."""
        rows = self._list_legacy_note_rows(limit=limit)
        stats: dict[str, Any] = {
            "job_id": None,
            "total": len(rows),
            "processed": 0,
            "failed": 0,
            "skipped": 0,
            "dry_run": dry_run,
            "ollama_model": self._ollama_provider().get("model", ""),
        }
        if dry_run or not rows:
            return stats

        job_id = self.database.create_research_job(
            platform="douyin",
            blogger_id=None,
            blogger_name="旧 Markdown 笔记 Ollama 升级",
            limit_count=len(rows),
            since_time=None,
            until_time=None,
            push_enabled=False,
            force_enabled=True,
        )
        stats["job_id"] = job_id
        self.database.update_research_job(
            job_id,
            status="running",
            total_count=len(rows),
            pending_count=len(rows),
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        for row in rows:
            self.database.upsert_research_job_item(job_id, str(row.get("aweme_id") or ""), "pending")

        previous_config = self.config
        previous_organizer = self.organizer
        self.config = self._ollama_only_config()
        self.organizer = ContentOrganizer(self.config)
        ollama_model = str(stats.get("ollama_model") or self.config.get("ai.organizer.model", ""))
        logger.info("旧 Markdown 笔记升级开始: job_id=%s total=%s provider=ollama model=%s", job_id, len(rows), ollama_model)
        try:
            for index, row in enumerate(rows, start=1):
                aweme_id = str(row.get("aweme_id") or "")
                try:
                    self.database.upsert_research_job_item(job_id, aweme_id, "summarizing")
                    logger.info(
                        "调用 Ollama 升级旧笔记: job_id=%s progress=%s/%s aweme_id=%s model=%s",
                        job_id,
                        index,
                        len(rows),
                        aweme_id,
                        ollama_model,
                    )
                    result = self._summarize_transcript_row(row, workflow_name="refresh_old_notes_ollama")
                    if result.get("status") == "success":
                        stats["processed"] += 1
                        self.database.upsert_research_job_item(job_id, aweme_id, "success")
                        logger.info("Ollama 旧笔记升级成功: job_id=%s progress=%s/%s aweme_id=%s", job_id, index, len(rows), aweme_id)
                    else:
                        stats["failed"] += 1
                        error = str(result.get("error") or "Ollama 整理失败")
                        self.database.upsert_research_job_item(job_id, aweme_id, "failed", error)
                        logger.error("Ollama 旧笔记升级失败: job_id=%s progress=%s/%s aweme_id=%s error=%s", job_id, index, len(rows), aweme_id, error)
                    self._update_research_counts(job_id, stats, len(rows))
                except Exception as exc:
                    stats["failed"] += 1
                    self.database.upsert_research_job_item(job_id, aweme_id, "failed", str(exc))
                    self._update_research_counts(job_id, stats, len(rows))
                    logger.exception("旧 Markdown 笔记升级失败: aweme_id=%s", aweme_id)
        finally:
            self.config = previous_config
            self.organizer = previous_organizer

        final_status = "completed" if not stats["failed"] else ("partial_failed" if stats["processed"] else "failed")
        self.database.update_research_job(
            job_id,
            status=final_status,
            pending_count=0,
            success_count=stats["processed"],
            failed_count=stats["failed"],
            skipped_count=stats["skipped"],
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_error="" if final_status in {"completed", "partial_failed"} else "旧 Markdown 笔记升级失败",
        )
        logger.info("旧 Markdown 笔记升级结束: job_id=%s status=%s processed=%s failed=%s", job_id, final_status, stats["processed"], stats["failed"])
        return stats

    def _list_legacy_note_rows(self, limit: int = 0) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT a.aweme_id, a.title, a.aweme_type, a.create_time, a.duration, a.video_url, a.cover_url,
                       a.local_path, a.download_status, a.blogger_id AS db_blogger_id,
                       a.extra,
                       COALESCE(b.sec_uid, b.id::text) AS blogger_id, b.nickname,
                       t.text_content, t.text_path, t.status AS transcript_status,
                       s.status AS summary_status, s.summary_path
                FROM aweme a
                LEFT JOIN blogger b ON b.id = a.blogger_id
                JOIN transcript t ON t.aweme_id = a.aweme_id AND t.status = 'success'
                LEFT JOIN summary s ON s.aweme_id = a.aweme_id
                ORDER BY a.create_time DESC, a.id DESC
                """
            ).fetchall()
        legacy: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            note_path = self._resolve_existing_project_path(data.get("summary_path"))
            if note_path is None:
                continue
            if self._is_current_obsidian_video_note(note_path):
                continue
            data["summary_path"] = str(note_path)
            legacy.append(data)
            if limit > 0 and len(legacy) >= limit:
                break
        return legacy

    def _ollama_only_config(self) -> AppConfig:
        raw = deepcopy(self.config.raw)
        organizer = ((raw.setdefault("ai", {})).setdefault("organizer", {}))
        ollama_provider = self._ollama_provider()
        if not ollama_provider:
            raise ValueError("配置中没有启用的 Ollama organizer provider")
        organizer["providers"] = [ollama_provider]
        organizer["model"] = ollama_provider.get("model", organizer.get("model", ""))
        organizer["api_type"] = "ollama"
        organizer["endpoint"] = ollama_provider.get("endpoint", organizer.get("endpoint", "http://127.0.0.1:11434/v1"))
        organizer["max_concurrent"] = 1
        organizer["rpm_limit"] = 0
        return AppConfig(raw=raw, path=self.config.path)

    def _ollama_provider(self) -> dict[str, Any]:
        providers = self.config.get("ai.organizer.providers", []) or []
        if isinstance(providers, list):
            for provider in providers:
                if not isinstance(provider, dict):
                    continue
                if str(provider.get("api_type") or "").lower() == "ollama" and provider.get("enabled", True):
                    return dict(provider)
        return {}

    def _resolve_existing_project_path(self, value: Any) -> Path | None:
        text = str(value or "").strip()
        if not text:
            return None
        candidates = [Path(text)]
        if text.startswith("/home/ken/Projects/KenRadar"):
            candidates.append(self.config.root_dir / text.removeprefix("/home/ken/Projects/KenRadar").lstrip("/"))
        if not Path(text).is_absolute():
            candidates.append((self.config.root_dir / text).resolve())
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _is_current_obsidian_video_note(path: Path) -> bool:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:1200]
        except OSError:
            return False
        return head.startswith("---") and re.search(r"(?m)^type:\s*video_note\s*$", head) is not None

    async def retry_research_failed(self, job_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            job = conn.execute("SELECT * FROM research_job WHERE id = %s", (job_id,)).fetchone()
            rows = conn.execute(
                """
                SELECT i.aweme_id
                FROM research_job_item i
                WHERE i.job_id = %s AND i.status = 'failed' AND i.aweme_id IS NOT NULL AND i.aweme_id != ''
                ORDER BY i.id
                """,
                (job_id,),
            ).fetchall()
        if job is None:
            raise ValueError(f"未找到研究任务: {job_id}")
        awemes = [self._rebuild_aweme_dict(self._load_aweme_for_retry(str(row["aweme_id"]))) for row in rows]
        if not awemes:
            return {"source_job_id": job_id, "job_id": None, "total": 0, "processed": 0, "failed": 0, "message": "没有可重试的失败条目"}
        target = BloggerTarget(
            id=job["blogger_id"],
            sec_uid=str(job["blogger_id"] or ""),
            name=str(job["blogger_name"] or "未知博主"),
            url="",
        )
        new_job_id = self.database.create_research_job(
            platform=str(job["platform"] or "douyin"),
            blogger_id=job["blogger_id"],
            blogger_name=f"{target.name} 失败重试",
            limit_count=len(awemes),
            since_time=None,
            until_time=None,
            push_enabled=False,
            force_enabled=True,
        )
        stats: dict[str, Any] = {"job_id": new_job_id, "source_job_id": job_id, "blogger": target.name, "fetched": len(awemes), "queued": len(awemes), "processed": 0, "skipped": 0, "failed": 0, "pushed": False}
        self.database.update_research_job(new_job_id, status="running", total_count=len(awemes), pending_count=len(awemes), started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        for aweme in awemes:
            self.database.upsert_research_job_item(new_job_id, str(aweme.get("aweme_id") or ""), "pending")
        pushed_items = await self._run_research_pipeline(new_job_id, target, awemes, awemes, stats)
        final_status = "completed" if not stats["failed"] else ("partial_failed" if stats["processed"] else "failed")
        report_path = ""
        report_url = ""
        if final_status in {"completed", "partial_failed"}:
            report = self._write_research_report(new_job_id, target, stats, pushed_items)
            report_path = str(report)
            report_url = self._publish_markdown(report, target.name)
            stats["report_path"] = report_path
            stats["report_url"] = report_url
            stats.update(self.publish_research_job(new_job_id))
        self.database.update_research_job(
            new_job_id,
            status=final_status,
            pending_count=0,
            success_count=stats["processed"],
            failed_count=stats["failed"],
            skipped_count=stats["skipped"],
            report_path=report_path,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_error="" if final_status in {"completed", "partial_failed"} else "失败条目重试任务失败",
        )
        return stats

    def publish_research_job(self, job_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            job = conn.execute(
                "SELECT id, blogger_name, status FROM research_job WHERE id = %s",
                (job_id,),
            ).fetchone()
            rows = conn.execute(
                """
                SELECT DISTINCT n.note_path
                FROM research_job_item rji
                JOIN content_item ci ON ci.content_id = rji.aweme_id
                JOIN content_note n ON n.content_item_id = ci.id AND n.note_type = 'content'
                WHERE rji.job_id = %s
                  AND rji.status IN ('success', 'skipped')
                  AND n.note_path IS NOT NULL
                  AND n.note_path != ''
                ORDER BY n.note_path
                """,
                (job_id,),
            ).fetchall()
        if job is None:
            raise ValueError(f"未找到研究任务: {job_id}")
        paths = [Path(str(row["note_path"])) for row in rows]
        collection_url = self.publisher.publish_research_collection(
            job_id,
            str(job["blogger_name"] or "未知博主"),
            paths,
        )
        sync_result: dict[str, Any] = {"ok": True, "enabled": False, "message": "GitHub 同步未启用"}
        try:
            manager = GithubSyncManager(self.config)
            sync_result = manager.sync()
            if sync_result.get("enabled"):
                manager.write_last_sync(sync_result)
        except Exception as exc:
            logger.exception("批量研究 GitHub 同步失败: job_id=%s", job_id)
            self.alerts.error(
                "github_sync",
                str(exc),
                title=f"研究任务 #{job_id}",
                context={"job_id": job_id, "collection_url": collection_url},
            )
            sync_result = {"ok": False, "message": str(exc)}
        return {
            "batch_notes_count": len(paths),
            "batch_notes_url": collection_url,
            "github_synced": bool(sync_result.get("ok") and sync_result.get("enabled")),
            "github_sync_message": str(sync_result.get("message") or ""),
        }

    async def restart_research_job(self, job_id: int) -> dict[str, Any]:
        with self.database.connect() as conn:
            job = conn.execute("SELECT * FROM research_job WHERE id = %s", (job_id,)).fetchone()
        if job is None:
            raise ValueError(f"未找到研究任务: {job_id}")
        target = self._research_target_from_job(dict(job))
        reason = f"用户重启研究任务，原任务 #{job_id} 已取消"
        self.database.update_research_job(
            job_id,
            status="cancelled",
            pending_count=0,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_error=reason,
        )
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE research_job_item
                SET status='cancelled',
                    error_message=%s,
                    updated_at=NOW()
                WHERE job_id = %s
                  AND status IN ('pending', 'running', 'downloading', 'downloaded', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting')
                """,
                (reason, job_id),
            )
        return await self.research_blogger(
            blogger=target.sec_uid or target.name,
            limit=int(job["limit_count"] or 0),
            push=bool(job["push_enabled"]),
            force=bool(job["force_enabled"]),
            since=str(job["since_time"] or ""),
            until=str(job["until_time"] or ""),
        )

    def _research_target_from_job(self, job: dict[str, Any]) -> BloggerTarget:
        creator_id = job.get("creator_id") or job.get("blogger_id")
        name = str(job.get("creator_name") or job.get("blogger_name") or "").strip()
        if creator_id:
            try:
                with self.database.connect() as conn:
                    row = conn.execute(
                        """
                        SELECT id, platform_uid, nickname, profile_url
                        FROM creator
                        WHERE id = %s
                        """,
                        (creator_id,),
                    ).fetchone()
                if row:
                    sec_uid = str(row["platform_uid"] or "").strip()
                    nickname = str(row["nickname"] or name or sec_uid).strip()
                    url = str(row["profile_url"] or (f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "")).strip()
                    if sec_uid:
                        return BloggerTarget(id=int(row["id"]), sec_uid=sec_uid, name=nickname or sec_uid, url=url)
            except Exception as exc:
                logger.warning("根据研究任务 creator_id 恢复博主失败: job_id=%s creator_id=%s error=%s", job.get("id"), creator_id, exc)
        return self._resolve_research_target(name or str(job.get("blogger_id") or ""))

    def _load_aweme_for_retry(self, aweme_id: str) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT a.aweme_id, a.title, a.aweme_type, a.create_time, a.duration, a.video_url, a.cover_url,
                       a.local_path, a.download_status, a.blogger_id AS db_blogger_id,
                       a.extra,
                       COALESCE(b.sec_uid, b.id::text) AS blogger_id, b.nickname,
                       t.text_content, t.text_path, t.status AS transcript_status,
                       s.status AS summary_status
                FROM aweme a
                LEFT JOIN blogger b ON b.id = a.blogger_id
                LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
                LEFT JOIN summary s ON s.aweme_id = a.aweme_id
                WHERE a.aweme_id = %s
                """,
                (aweme_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"未找到作品: {aweme_id}")
        return dict(row)

    def _rebuild_aweme_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        aweme_id = str(row.get("aweme_id") or "")
        nickname = str(row.get("nickname") or "未知博主")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        rebuilt = dict(extra)
        rebuilt.update({
            "aweme_id": aweme_id,
            "desc": str(row.get("title") or rebuilt.get("desc") or "无标题"),
            "title": str(row.get("title") or rebuilt.get("title") or "无标题"),
            "aweme_type": row.get("aweme_type") if row.get("aweme_type") is not None else rebuilt.get("aweme_type"),
            "create_time": row.get("create_time") or rebuilt.get("create_time"),
            "duration": row.get("duration") or rebuilt.get("duration"),
            "video_url": row.get("video_url") or rebuilt.get("video_url"),
            "cover_url": row.get("cover_url") or rebuilt.get("cover_url"),
            "local_path": row.get("local_path") or rebuilt.get("local_path"),
            "sec_uid": str(row.get("blogger_id") or rebuilt.get("sec_uid") or ""),
        })
        author = rebuilt.get("author") if isinstance(rebuilt.get("author"), dict) else {}
        author.setdefault("nickname", nickname)
        author.setdefault("sec_uid", str(row.get("blogger_id") or ""))
        rebuilt["author"] = author
        return rebuilt

    def _find_local_video(self, aweme_id: str, row: dict[str, Any]) -> Path | None:
        candidates: list[Path] = []
        if row.get("local_path"):
            candidates.append(Path(str(row["local_path"])))
        candidates.extend(sorted(self.config.download_dir.glob(f"**/*{aweme_id}*.mp4"), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True))
        for path in candidates:
            if path.exists() and path.is_file() and path.stat().st_size > 0:
                return path
        return None

    def _find_existing_downloaded_video(self, aweme_id: str) -> Path | None:
        try:
            row = self._load_aweme_for_retry(aweme_id)
        except Exception:
            row = {"aweme_id": aweme_id}
        return self._find_local_video(aweme_id, row)

    def _resolve_retry_stage(self, aweme_id: str, retry_from: str) -> str:
        requested = str(retry_from or "auto").strip().lower()
        aliases = {"whisper": "transcribe", "transcript": "transcribe", "summary": "ai", "openai_api": "ai", "openai": "ai", "full": "auto"}
        requested = aliases.get(requested, requested)
        if requested in {"download", "transcribe", "ai"}:
            return requested
        row = self._load_aweme_for_retry(aweme_id)
        if str(row.get("download_status") or "") == "failed":
            return "download"
        if str(row.get("transcript_status") or "pending") == "failed":
            return "transcribe"
        if str(row.get("summary_status") or "pending") == "failed":
            return "ai"
        return "auto"

    @staticmethod
    def _retry_result(aweme_id: str, item: dict[str, Any] | None, workflow_name: str) -> dict[str, Any]:
        if not item:
            return {"aweme_id": aweme_id, "status": "failed", "workflow": workflow_name}
        status = "success" if str(item.get("summary_status") or "") == "success" else "failed"
        return {"aweme_id": aweme_id, "status": status, "workflow": workflow_name, "summary_path": item.get("summary_path"), "detail_url": item.get("detail_url"), "error": "" if status == "success" else "AI 整理失败，已生成降级笔记"}

    def _summarize_transcript_row(self, row: dict[str, Any], workflow_name: str) -> dict[str, Any]:
        aweme_id = str(row.get("aweme_id") or "")
        title = str(row.get("title") or "无标题")
        original_text = str(row.get("text_content") or "")
        if not original_text and row.get("text_path"):
            path = Path(str(row["text_path"]))
            if path.exists():
                original_text = path.read_text(encoding="utf-8", errors="replace")
        metadata = {
            "platform": "douyin",
            "title": title,
            "publish_time": self._format_timestamp(row.get("create_time")),
            "video_url": str(row.get("video_url") or f"https://www.douyin.com/video/{aweme_id}"),
            "cover_url": str(row.get("cover_url") or ""),
            "duration": row.get("duration") or 0,
            "blogger_name": str(row.get("nickname") or "未知博主"),
            "blogger_id": str(row.get("blogger_id") or ""),
        }
        summary_text = self.organizer.organize(title, original_text, metadata)
        if self.organizer.last_error:
            self.alerts.error(
                "openai_api",
                self.organizer.last_error,
                aweme_id=aweme_id,
                title=title,
                context={"workflow": workflow_name, "text_path": row.get("text_path")},
            )
        summary_status = "failed" if self.organizer.last_error else "success"
        summary_path = self._write_item_summary(aweme_id, title, summary_text, original_text, metadata, str(row.get("text_path") or ""), summary_status)
        html_url = self._publish_markdown(summary_path, title)
        self.database.upsert_summary(
            aweme_id=aweme_id,
            summary_text=summary_text,
            summary_path=str(summary_path),
            model=str(self.config.get("ai.organizer.model", "")),
            status=summary_status,
            error_message=self.organizer.last_error,
        )
        self._cleanup_download_artifacts(aweme_id, transcript=row)
        return {"aweme_id": aweme_id, "status": summary_status, "summary_path": str(summary_path), "html_url": html_url, "error": self.organizer.last_error}

    def _write_backfill_summary(self, blogger_name: str, items: list[dict[str, str]]) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in blogger_name).strip("_") or "blogger"
        output_dir = brief_dir(self.config)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{safe_name}_backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        lines = [
            f"# {blogger_name} 历史视频整理",
            "",
            f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 视频数量: {len(items)}",
            "",
            "## 视频索引",
            "",
        ]
        for index, item in enumerate(items, start=1):
            original_text = self._load_original_text(item)
            if item.get("summary"):
                self.organizer.last_error = None
                organized_text = item["summary"]
            else:
                organized_text = self.organizer.organize(item["title"], original_text, item)
            if self.organizer.last_error:
                self.alerts.error(
                    "openai_api",
                    self.organizer.last_error,
                    aweme_id=item.get("aweme_id"),
                    title=item.get("title"),
                    context={"text_path": item.get("text_path")},
                )
            summary_status = "failed" if self.organizer.last_error else "success"
            metadata = {
                "title": item["title"],
                "publish_time": item.get("create_time", ""),
                "video_url": item.get("url", ""),
                "blogger_name": item.get("blogger_name") or blogger_name,
                "blogger_id": item.get("blogger_id", ""),
            }
            summary_path = self._write_item_summary(
                item["aweme_id"],
                item["title"],
                organized_text,
                original_text,
                metadata,
                item.get("transcript_file") or item.get("text_path", ""),
                summary_status,
            )
            html_url = self._publish_markdown(summary_path, item["title"])
            self.database.upsert_summary(
                aweme_id=item["aweme_id"],
                summary_text=organized_text,
                summary_path=str(summary_path),
                model=str(self.config.get("ai.organizer.model", "")),
                status=summary_status,
                error_message=self.organizer.last_error,
            )
            self._cleanup_download_artifacts(item["aweme_id"], transcript=item)
            lines.extend(
                [
                    f"### {index}. {item['title']}",
                    "",
                    f"- 发布时间: {item['create_time']}",
                    f"- 原视频: {item['url']}",
                    f"- 发布页面: {html_url or '未启用'}",
                    f"- 转录文件: {item['text_path']}",
                    "",
                    organized_text,
                    "",
                    "## 原文转录",
                    "",
                    original_text or "无原文转录。",
                    "",
                    "---",
                    "",
                ]
            )
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _write_item_summary(
        self,
        aweme_id: str,
        title: str,
        summary_text: str,
        original_text: str,
        metadata: dict[str, Any] | None = None,
        transcript_path: str = "",
        summary_status: str = "success",
    ) -> Path:
        metadata = metadata or {}
        platform = str(metadata.get("platform") or "douyin")
        blogger_name = str(metadata.get("blogger_name") or "未知博主")
        blogger_id = str(metadata.get("blogger_id") or "")
        publish_time = str(metadata.get("publish_time") or "")
        video_url = str(metadata.get("video_url") or f"https://www.douyin.com/video/{aweme_id}")
        summary_model = str(self.config.get("ai.organizer.model", ""))
        transcript_model = str(self.config.get("ai.whisper.model", "large-v3-turbo"))
        organized = self._normalize_ai_output(summary_text, title, original_text, summary_status, aweme_id)
        brief_title = organized["brief_title"]
        topics = self._obsidian_topics(organized, title, summary_text)
        entities = self._obsidian_entities(organized, title, summary_text)
        note_tags = self._obsidian_tags(platform, topics)
        output_dir = note_dir(self.config, platform, blogger_name)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / note_filename(publish_time, brief_title, aweme_id)
        self._remove_stale_item_notes(aweme_id, path)
        lines = [
            "---",
            "type: video_note",
            f"platform: {self._yaml_str(platform_label(platform))}",
            f"creator: {self._yaml_str(blogger_name)}",
            f"creator_id: {self._yaml_str(blogger_id)}",
            f"video_id: {self._yaml_str(aweme_id)}",
            f"source_url: {self._yaml_str(video_url)}",
            f"original_title: {self._yaml_str(title)}",
            f"title: {self._yaml_str(brief_title)}",
            f"published_at: {self._yaml_str(publish_time or '')}",
            f"ai_model: {self._yaml_str(summary_model)}",
            f"transcript_model: {self._yaml_str(transcript_model)}",
            "topics:",
            *self._yaml_list(topics),
            "tags:",
            *self._yaml_list(note_tags),
            "status: processed",
            f"value_score: {self._yaml_number(organized.get('value_score'))}",
            "---",
            "",
            f"# {brief_title}",
            "",
            "## 一、内容简述",
            "",
            self._render_content_summary(organized),
            "",
            "## 二、知识关联",
            "",
            self._render_knowledge_links(topics, entities),
            "",
            "## 三、分段原文",
            "",
            self._render_corrected_transcript(organized),
            "",
            "## 四、视频原始转录",
            "",
            "> 以下内容由 Whisper 自动转录生成，可能存在错字、断句错误或语义遗漏，请以原视频为准。",
            "",
            original_text or "无转录文本。",
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _remove_stale_item_notes(self, aweme_id: str, keep_path: Path) -> None:
        if not aweme_id:
            return
        keep = keep_path.resolve()
        for candidate in summary_dir(self.config).glob(f"**/*{aweme_id}*.md"):
            try:
                if candidate.resolve() != keep:
                    candidate.unlink()
            except OSError:
                logger.warning("删除旧内容笔记失败: %s", candidate)

    def cleanup_processed_downloads(self, dry_run: bool = False) -> dict[str, Any]:
        download_root = self.config.download_dir.resolve()
        stats: dict[str, Any] = {"scanned": 0, "eligible_items": 0, "files": 0, "bytes": 0, "dry_run": dry_run}
        grouped: dict[str, list[Path]] = {}
        try:
            files = [path for path in download_root.glob("**/*") if path.is_file()]
        except OSError as exc:
            logger.warning("扫描下载目录失败: %s", exc)
            return stats

        for path in files:
            if not self._is_download_artifact(path):
                continue
            aweme_id = self._extract_aweme_id_from_artifact(path)
            if not aweme_id:
                continue
            grouped.setdefault(aweme_id, []).append(path)

        stats["scanned"] = sum(len(paths) for paths in grouped.values())
        for aweme_id, paths in grouped.items():
            if not self._has_persisted_note_and_transcript(aweme_id):
                continue
            stats["eligible_items"] += 1
            stats["files"] += len(paths)
            stats["bytes"] += sum(path.stat().st_size for path in paths if path.exists())
            if not dry_run:
                self._cleanup_download_artifacts(aweme_id)
        return stats

    def _cleanup_download_artifacts(
        self,
        aweme_id: str,
        video_path: Path | str | None = None,
        transcript: dict[str, Any] | None = None,
    ) -> int:
        if not aweme_id or not self.config.get("ai.whisper.cleanup_video", True):
            return 0

        download_root = self.config.download_dir.resolve()
        candidates: set[Path] = set()

        def add_candidate(value: Any) -> None:
            if not value:
                return
            path = Path(str(value))
            try:
                resolved = path.resolve()
            except OSError:
                return
            try:
                if not resolved.is_relative_to(download_root):
                    return
            except AttributeError:
                if download_root not in resolved.parents and resolved != download_root:
                    return
            candidates.add(resolved)

        add_candidate(video_path)
        for key in ("text_path", "txt_path", "json_path"):
            add_candidate((transcript or {}).get(key))
        try:
            for candidate in download_root.glob(f"**/*{aweme_id}*"):
                if candidate.is_file() and self._is_download_artifact(candidate):
                    add_candidate(candidate)
        except OSError as exc:
            logger.debug("扫描下载临时文件失败: aweme_id=%s error=%s", aweme_id, exc)

        removed = 0
        for path in sorted(candidates):
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    removed += 1
            except OSError as exc:
                logger.warning("清理下载临时文件失败: aweme_id=%s path=%s error=%s", aweme_id, path, exc)

        if removed:
            logger.info("已清理下载临时文件: aweme_id=%s files=%s", aweme_id, removed)
        clear_paths = getattr(self.database, "clear_transcript_paths", None)
        if callable(clear_paths):
            clear_paths(aweme_id)
        self._prune_empty_download_dirs(download_root)
        return removed

    @staticmethod
    def _is_download_artifact(path: Path) -> bool:
        return (
            path.name.endswith(".mp4")
            or path.name.endswith(".tmp")
            or path.name.endswith(".transcript.txt")
            or path.name.endswith(".transcript.json")
        )

    @staticmethod
    def _extract_aweme_id_from_artifact(path: Path) -> str:
        matches = re.findall(r"(?<!\d)(\d{16,20})(?!\d)", path.name)
        return matches[-1] if matches else ""

    def _has_persisted_note_and_transcript(self, aweme_id: str) -> bool:
        transcript = self.database.get_successful_transcript(aweme_id)
        if not transcript or not str(transcript.get("text_content") or "").strip():
            return False
        summary = self.database.get_summary(aweme_id)
        summary_path = str((summary or {}).get("summary_path") or "").strip()
        if not summary_path:
            return False
        path = Path(summary_path)
        if not path.is_absolute():
            path = self.config.root_dir / path
        return path.exists()

    def _prune_empty_download_dirs(self, download_root: Path) -> None:
        try:
            dirs = sorted((path for path in download_root.glob("**/*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True)
        except OSError:
            return
        for path in dirs:
            try:
                path.rmdir()
            except OSError:
                pass

    def _normalize_ai_output(self, summary_text: str, title: str, original_text: str, summary_status: str, aweme_id: str = "") -> dict[str, Any]:
        fallback_summary = "AI 整理结果解析失败，需人工查看视频原稿。"
        fallback_sections = [
            {
                "title": "原稿待人工核对",
                "content": "本条视频已完成 Whisper 转录，但 AI 结构化摘要解析失败，请以视频原稿为准。",
            }
        ]
        if summary_status == "failed":
            return {
                "brief_title": self._clean_note_title(title, "", aweme_id),
                "brief_summary": fallback_summary,
                "content_sections": fallback_sections,
                "corrected_transcript_sections": [],
            }
        parsed = self._parse_ai_json(summary_text)
        if parsed:
            clean_sections = self._normalize_ai_sections(
                parsed.get("content_sections") or parsed.get("sections") or parsed.get("key_points")
            )
            brief_summary = self._clean_summary_value(
                parsed.get("brief_summary") or parsed.get("one_sentence") or parsed.get("summary")
            )
            importance_score = self._score_value(parsed.get("importance_score"), parsed.get("importance_level"))
            novelty_score = self._score_value(parsed.get("novelty_score"))
            information_density = self._score_value(parsed.get("information_density"))
            business_relevance = self._score_value(parsed.get("business_relevance"))
            value_score = self._score_value(parsed.get("value_score")) or self._average_score(
                importance_score,
                novelty_score,
                information_density,
                business_relevance,
            )
            return {
                "brief_title": self._clean_note_title(parsed.get("brief_title") or parsed.get("title"), title, aweme_id),
                "brief_summary": self._limit_plain_text(brief_summary or fallback_summary, 180),
                "content_sections": clean_sections or fallback_sections,
                "corrected_transcript_sections": self._validated_corrected_transcript_sections(
                    parsed.get("corrected_transcript_sections")
                    or parsed.get("corrected_transcript")
                    or parsed.get("transcript_sections"),
                    original_text,
                ),
                "content_category": self._clean_summary_value(parsed.get("content_category")),
                "keywords": self._string_list(parsed.get("keywords")),
                "tags": self._string_list(parsed.get("tags")),
                "importance_score": importance_score,
                "novelty_score": novelty_score,
                "information_density": information_density,
                "business_relevance": business_relevance,
                "value_score": value_score,
                "recommended_action": str(parsed.get("recommended_action") or "").strip(),
                "deep_research_suggested": bool(parsed.get("deep_research_suggested")),
            }
        readable = self._extract_readable_ai_text(summary_text)
        if readable:
            lines = [line.strip(" -•\t") for line in readable.splitlines() if line.strip()]
            brief = self._limit_plain_text(lines[0], 180)
            core_text = self._limit_plain_text("\n".join(lines[1:]) or brief, 250)
            fallback_sections = [{"title": "核心要点1", "content": core_text}]
            fallback_scores = self._fallback_scores_from_text(" ".join([title, readable, original_text[:1200]]))
            fallback_tags = self._infer_reusable_topics(" ".join([title, readable, original_text[:1200]])) or ["投资策略"]
            return {
                "brief_title": self._clean_note_title(title, "", aweme_id),
                "brief_summary": brief or fallback_summary,
                "content_sections": fallback_sections,
                "corrected_transcript_sections": [],
                "content_category": fallback_tags[0] if fallback_tags else "",
                "keywords": fallback_tags[:8],
                "tags": fallback_tags[:5],
                "importance_score": fallback_scores["importance_score"],
                "novelty_score": fallback_scores["novelty_score"],
                "information_density": fallback_scores["information_density"],
                "business_relevance": fallback_scores["business_relevance"],
                "value_score": fallback_scores["value_score"],
                "recommended_action": fallback_scores["recommended_action"],
                "recommendation_reason": "AI 返回非 JSON，系统按可读摘要保守评估",
                "deep_research_suggested": fallback_scores["value_score"] >= 4.2,
            }
        return {
            "brief_title": self._clean_note_title(title, "", aweme_id),
            "brief_summary": fallback_summary,
            "content_sections": fallback_sections,
            "corrected_transcript_sections": [],
            "content_category": "",
            "keywords": [],
            "tags": ["其他"],
            "importance_score": 0.0,
            "novelty_score": 0.0,
            "information_density": 0.0,
            "business_relevance": 0.0,
            "value_score": 0.0,
            "recommended_action": "",
            "deep_research_suggested": False,
        }

    @staticmethod
    def _parse_ai_json(summary_text: str) -> dict[str, Any] | None:
        return parse_ai_json(summary_text)

    @staticmethod
    def _parse_ai_json_loose(text: str) -> Any:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        candidate = match.group(0)
        repaired_missing_section_object = re.sub(
            r'(\n\s*},\s*\n)(\s*)("title"\s*:)',
            r'\1\2{\n\2  \3',
            candidate,
        )
        repaired_nested_section_array = re.sub(
            r'(\n\s*},\s*\n)\s*"content_sections"\s*:\s*\[\s*\n',
            r'\1',
            candidate,
            count=1,
        )
        if repaired_nested_section_array != candidate:
            repaired_nested_section_array = re.sub(r"\n\s*\]\s*\n\}\s*$", "\n}", repaired_nested_section_array)
            repaired_nested_section_array = re.sub(r"\n\s{2}\}\s*\n\}\s*$", "\n}", repaired_nested_section_array)
        repairs = [
            candidate,
            repaired_missing_section_object,
            repaired_nested_section_array,
            re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)"', r'\1"\2"', candidate),
            re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', candidate),
        ]
        seen: set[str] = set()
        for repaired in repairs:
            if repaired in seen:
                continue
            seen.add(repaired)
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _render_content_summary(organized: dict[str, Any]) -> str:
        one_sentence = str(organized.get("brief_summary") or "AI 整理结果解析失败，需人工查看视频原稿。").strip()
        sections = organized.get("content_sections")
        if not isinstance(sections, list):
            sections = []
        lines: list[str] = []
        lines.extend(["### （一）一句话结论", "", "> [!summary]"])
        for line in one_sentence.splitlines() or [one_sentence]:
            lines.append(f"> {line.strip()}")
        lines.extend(["", "### （二）核心内容", ""])
        clean_sections = [section for section in sections if isinstance(section, dict)]
        if not clean_sections:
            clean_sections = [
                {
                    "title": "原稿待人工核对",
                    "content": "本条视频已完成 Whisper 转录，但 AI 结构化摘要解析失败，请以视频原稿为准。",
                }
            ]
        for index, section in enumerate(clean_sections[:5], start=1):
            title = str(section.get("title") or f"核心要点{index}").strip()
            content = str(section.get("content") or "原文未明确说明。").strip()
            lines.extend([f"{index}. **{title}**  ", f"   {content}", ""])
        return "\n".join(lines).strip()

    @staticmethod
    def _render_corrected_transcript(organized: dict[str, Any]) -> str:
        sections = organized.get("corrected_transcript_sections")
        if not isinstance(sections, list) or not sections:
            return (
                "> [!warning]\n"
                "> 本次 AI 未生成可核验的纠错分段原文。为避免把未经纠错的文字误标为修正版，"
                "请查看下方“视频原始转录”，或从详情页重新生成 AI 整理。"
            )
        lines = [
            "> 以下内容保持博主原意和论述顺序，仅修正明显错别字、ASR 识别错误、标点与断句。",
            "",
        ]
        for index, section in enumerate(sections, start=1):
            title = str(section.get("title") or f"段落 {index}").strip()
            content = str(section.get("content") or "").strip()
            if not content:
                continue
            lines.extend([f"### {index}. {title}", "", content, ""])
        return "\n".join(lines).strip()

    def _video_metadata(self, aweme: dict[str, Any], blogger_name: str, blogger_id: int | str) -> dict[str, Any]:
        aweme_id = str(aweme.get("aweme_id") or "")
        author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
        author_user = aweme.get("author_user_info") if isinstance(aweme.get("author_user_info"), dict) else {}
        nickname = (
            author.get("nickname")
            or author_user.get("nickname")
            or aweme.get("nickname")
            or aweme.get("author_name")
            or blogger_name
        )
        sec_uid = (
            author.get("sec_uid")
            or author_user.get("sec_uid")
            or aweme.get("sec_uid")
            or blogger_id
        )
        return {
            "platform": "douyin",
            "aweme_id": aweme_id,
            "title": str(aweme.get("desc") or aweme.get("title") or "无标题"),
            "blogger_name": str(nickname or blogger_name or "未知博主"),
            "blogger_id": str(sec_uid or blogger_id or ""),
            "publish_time": format_ts(aweme.get("create_time")),
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "video_url": self._public_video_url(aweme_id, str(aweme.get("video_url") or "")),
            "cover_url": str(aweme.get("cover_url") or ""),
            "duration": aweme.get("duration") or 0,
        }

    @staticmethod
    def _normalize_ai_sections(value: Any) -> list[dict[str, str]]:
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            return []
        sections: list[dict[str, str]] = []
        for index, section in enumerate(value[:5], start=1):
            if isinstance(section, dict):
                title = Workflow._clean_section_title(
                    section.get("title") or section.get("heading") or section.get("name"),
                    f"核心要点{index}",
                )
                content = Workflow._clean_summary_value(
                    section.get("content") or section.get("summary") or section.get("text") or section.get("description")
                )
            else:
                title = f"核心要点{index}"
                content = Workflow._clean_summary_value(section)
            if content:
                sections.append({"title": title, "content": Workflow._limit_plain_text(content, 250)})
        return sections

    @staticmethod
    def _normalize_corrected_transcript_sections(value: Any) -> list[dict[str, str]]:
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            return []
        sections: list[dict[str, str]] = []
        for index, section in enumerate(value[:40], start=1):
            if not isinstance(section, dict):
                continue
            title = Workflow._clean_section_title(
                section.get("title") or section.get("heading") or section.get("name"),
                f"段落 {index}",
            )
            content = Workflow._clean_transcript_paragraph(
                section.get("content") or section.get("text") or section.get("paragraph")
            )
            if content:
                sections.append({"title": title, "content": content})
        return sections

    @staticmethod
    def _validated_corrected_transcript_sections(value: Any, original_text: str) -> list[dict[str, str]]:
        sections = Workflow._normalize_corrected_transcript_sections(value)
        original_length = len(re.sub(r"\s+", "", str(original_text or "")))
        corrected_length = sum(len(re.sub(r"\s+", "", section["content"])) for section in sections)
        if original_length >= 200 and corrected_length < original_length * 0.65:
            logger.warning(
                "AI 纠错分段疑似不完整，已阻止写入修正版: original_chars=%s corrected_chars=%s",
                original_length,
                corrected_length,
            )
            return []
        return sections

    @staticmethod
    def _clean_transcript_paragraph(value: Any) -> str:
        if value is None or isinstance(value, (dict, list)):
            return ""
        text = str(value).strip()
        text = re.sub(r"^```(?:text|markdown)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if Workflow._looks_like_json(text):
            return ""
        return text[:6000].strip()

    @staticmethod
    def _clean_note_title(value: Any, fallback: str, aweme_id: str) -> str:
        text = Workflow._clean_summary_value(value) or Workflow._clean_summary_value(fallback) or aweme_id or "未命名视频"
        text = re.sub(r"#\S+", "", text)
        text = re.sub(r"\s+", " ", text).strip(" #_-，。,.|")
        if not text or Workflow._looks_like_json(text):
            text = aweme_id or "未命名视频"
        return text[:40].rstrip(" #_-，。,.|") or aweme_id or "未命名视频"

    @staticmethod
    def _clean_section_title(value: Any, fallback: str) -> str:
        text = Workflow._clean_summary_value(value) or fallback
        text = re.sub(r"\s+", " ", text).strip(" #_-，。,.|")
        return text[:30].rstrip(" #_-，。,.|") or fallback

    @staticmethod
    def _clean_summary_value(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return ""
        text = str(value).strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        if Workflow._looks_like_json(text):
            return ""
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    @staticmethod
    def _limit_plain_text(value: str, limit: int) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip(" ，。,.；;") + "。"

    @staticmethod
    def _looks_like_json(text: str) -> bool:
        stripped = text.strip()
        return stripped.startswith("{") or stripped.startswith("[")

    @staticmethod
    def _extract_readable_ai_text(summary_text: str) -> str:
        text = Workflow._clean_summary_value(summary_text)
        if not text:
            return ""
        lines = []
        for line in text.splitlines():
            cleaned = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip()
            cleaned = cleaned.strip("`")
            if cleaned and not Workflow._looks_like_json(cleaned):
                lines.append(cleaned)
        return "\n".join(lines[:6]).strip()

    @staticmethod
    def _string_list(value: Any, limit: int = 12) -> list[str]:
        if isinstance(value, list):
            raw = value
        elif isinstance(value, str):
            raw = re.split(r"[,，/、\n;；]+", value)
        else:
            raw = []
        result: list[str] = []
        seen: set[str] = set()
        for item in raw:
            text = re.sub(r"\s+", " ", str(item or "")).strip(" #[]`'\"，。,.；;：:")
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
            if len(result) >= limit:
                break
        return result

    @staticmethod
    def _score_value(value: Any, level: Any = None) -> float:
        try:
            score = float(value)
            if score > 0:
                return max(1.0, min(5.0, score))
        except (TypeError, ValueError):
            pass
        level_text = str(level or "")
        if level_text == "高":
            return 4.5
        if level_text == "中":
            return 3.0
        if level_text == "低":
            return 2.0
        return 0.0

    @staticmethod
    def _average_score(*values: float) -> float:
        scores = [float(value) for value in values if value]
        if not scores:
            return 0.0
        return round(sum(scores) / len(scores), 1)

    @staticmethod
    def _fallback_scores_from_text(text: str) -> dict[str, Any]:
        value = str(text or "")
        information_density = 3.0
        business_relevance = 3.0
        novelty_score = 3.0
        importance_score = 3.0
        if len(value) > 1200 or len(re.findall(r"\d+(?:\.\d+)?%?", value)) >= 5:
            information_density = 3.5
        if any(word in value for word in ["投资", "配置", "估值", "业绩", "需求", "供给", "ROE", "公司", "板块", "行业"]):
            business_relevance = 3.5
        if any(word in value for word in ["AI", "算力", "半导体", "芯片", "新能源", "电力", "券商", "有色", "创新药", "港股", "A股"]):
            importance_score = 3.5
        if any(word in value for word in ["拐点", "超预期", "周期", "催化", "新高", "反转", "爆发", "国产化"]):
            novelty_score = 3.5
        value_score = round((importance_score + novelty_score + information_density + business_relevance) / 4, 1)
        action = "review" if value_score >= 3.0 else "archive"
        if value_score >= 4.2:
            action = "research"
        return {
            "importance_score": importance_score,
            "novelty_score": novelty_score,
            "information_density": information_density,
            "business_relevance": business_relevance,
            "value_score": value_score,
            "recommended_action": action,
        }

    @staticmethod
    def _yaml_str(value: Any) -> str:
        text = str(value or "")
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'

    @staticmethod
    def _yaml_number(value: Any) -> str:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return "0"
        if score <= 0:
            return "0"
        return f"{score:.1f}".rstrip("0").rstrip(".")

    @classmethod
    def _yaml_list(cls, values: list[str]) -> list[str]:
        if not values:
            return ["  []"]
        return [f"  - {cls._yaml_str(value)}" for value in values]

    @staticmethod
    def _obsidian_tags(platform: str, topics: list[str]) -> list[str]:
        platform_name = platform_label(platform)
        tags = ["KenRadar", "视频笔记", platform_name]
        for topic in topics:
            if len(tags) >= 10:
                break
            if topic not in tags:
                tags.append(topic)
        return tags

    @staticmethod
    def _obsidian_topics(organized: dict[str, Any], title: str, summary_text: str) -> list[str]:
        source_terms: list[str] = []
        source_terms.extend(Workflow._string_list(organized.get("tags")))
        source_terms.extend(Workflow._string_list(organized.get("keywords")))
        category = Workflow._clean_summary_value(organized.get("content_category"))
        if category and category != "未分类":
            source_terms.append(category)
        text = " ".join(
            [
                title,
                str(organized.get("brief_title") or ""),
                str(organized.get("brief_summary") or ""),
                summary_text[:2000],
            ]
        )
        source_terms.extend(Workflow._infer_reusable_topics(text))

        topics: list[str] = []
        seen: set[str] = set()
        for term in source_terms:
            normalized = Workflow._normalize_topic(term)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            topics.append(normalized)
            if len(topics) >= 10:
                break
        for fallback in Workflow._infer_reusable_topics(text):
            if len(topics) >= 5:
                break
            if fallback not in seen:
                seen.add(fallback)
                topics.append(fallback)
        return topics[:10]

    @staticmethod
    def _infer_reusable_topics(text: str) -> list[str]:
        rules = [
            ("AI", "AI产业"),
            ("人工智能", "AI产业"),
            ("算力", "算力中心"),
            ("半导体", "半导体"),
            ("芯片", "半导体"),
            ("港股", "港股市场"),
            ("A股", "股票市场"),
            ("股票", "股票市场"),
            ("宏观", "宏观经济"),
            ("汇率", "宏观经济"),
            ("降息", "货币政策"),
            ("流动性", "货币政策"),
            ("房地产", "房地产"),
            ("地产", "房地产"),
            ("新能源车", "新能源车"),
            ("汽车", "新能源车"),
            ("储能", "新能源"),
            ("电芯", "新能源"),
            ("商业航天", "商业航天"),
            ("创新药", "创新药"),
            ("医药", "医药行业"),
            ("红利", "红利资产"),
            ("高股息", "红利资产"),
            ("策略", "投资策略"),
            ("配置", "资产配置"),
        ]
        topics: list[str] = []
        for keyword, topic in rules:
            if keyword in text and topic not in topics:
                topics.append(topic)
        return topics

    @staticmethod
    def _normalize_topic(value: str) -> str:
        text = re.sub(r"\s+", "", str(value or "")).strip(" #[]`'\"，。,.；;：:")
        if not text:
            return ""
        replacements = {
            "宏观策略": "宏观经济",
            "行业配置": "资产配置",
            "风险提示": "",
            "其他": "",
            "投资策略": "投资策略",
            "港股": "港股市场",
            "A股": "股票市场",
        }
        text = replacements.get(text, text)
        if not text or len(text) > 16:
            return ""
        if re.search(r"\d{3,}", text):
            return ""
        if any(word in text for word in ["建议重点", "报告提供", "视频内容", "本地降级", "原文未明确"]):
            return ""
        return text

    @staticmethod
    def _obsidian_entities(organized: dict[str, Any], title: str, summary_text: str) -> list[str]:
        text = " ".join(
            [
                title,
                str(organized.get("brief_title") or ""),
                str(organized.get("brief_summary") or ""),
                " ".join(Workflow._string_list(organized.get("keywords"))),
                " ".join(Workflow._string_list(organized.get("tags"))),
                summary_text[:3000],
            ]
        )
        candidates: list[str] = []
        known = [
            "摩根士丹利", "高盛", "瑞银", "中金", "中信建投", "国泰海通", "国金证券", "东吴证券", "方正证券",
            "招商证券", "广发证券", "银河证券", "西部证券", "开源证券", "野村证券", "伯恩斯坦",
            "腾讯", "阿里巴巴", "美团", "京东", "比亚迪", "吉利", "宁德时代", "台积电", "英伟达", "海康威视",
        ]
        candidates.extend(name for name in known if name in text)
        patterns = [
            r"[\u4e00-\u9fa5A-Za-z0-9]{2,16}(?:证券|银行|基金|资本|集团|控股|科技|生物|医药|电气|股份|汽车|能源)",
            r"[A-Za-z][A-Za-z0-9 .&-]{1,24}(?:AI|Cloud|Bank|Capital|Securities|Group|Tech|Energy)",
        ]
        for pattern in patterns:
            candidates.extend(match.group(0).strip() for match in re.finditer(pattern, text))
        entities: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            cleaned = re.sub(r"\s+", " ", candidate).strip(" #[]`'\"，。,.；;：:")
            if not cleaned or cleaned in seen or len(cleaned) > 24:
                continue
            if cleaned in {"高新技术", "流动性因素", "经济周期", "创新药", "红利资产", "生物科技", "高端制造业科技"}:
                continue
            if any(word in cleaned for word in ["的", "可能", "这一类", "因素", "业务", "领域"]):
                continue
            seen.add(cleaned)
            entities.append(cleaned)
            if len(entities) >= 8:
                break
        return entities

    @staticmethod
    def _render_knowledge_links(topics: list[str], entities: list[str]) -> str:
        def wikilink(value: str) -> str:
            clean = str(value or "").replace("[", "").replace("]", "").replace("|", "-").strip()
            return f"- [[{clean}]]" if clean else ""

        topic_lines = [wikilink(topic) for topic in topics if topic]
        entity_lines = [wikilink(entity) for entity in entities if entity]
        if not topic_lines:
            topic_lines = ["- 暂无明确主题"]
        if not entity_lines:
            entity_lines = ["- 暂无明确机构或公司"]
        return "\n".join(
            [
                "### 相关主题",
                "",
                *topic_lines,
                "",
                "### 相关机构/公司",
                "",
                *entity_lines,
            ]
        )

    @staticmethod
    def _md_cell(value: Any) -> str:
        text = str(value or "").replace("\n", " ").replace("|", "\\|").strip()
        return text or "未知"

    @staticmethod
    def _infer_category(title: str, summary_text: str) -> str:
        text = f"{title}\n{summary_text}"
        for keyword, category in [
            ("算力", "科技/算力"),
            ("半导体", "科技/半导体"),
            ("芯片", "科技/半导体"),
            ("公司", "公司研究"),
            ("招股书", "资本市场"),
            ("指数", "市场观察"),
        ]:
            if keyword in text:
                return category
        return "未分类"

    @staticmethod
    def _extract_summary_sections(summary_text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current = ""
        for line in summary_text.splitlines():
            match = re.match(r"^\s{0,3}#{1,4}\s+(.+?)\s*$", line)
            if match:
                current = Workflow._normalize_summary_heading(match.group(1))
                sections.setdefault(current, [])
                continue
            if current:
                sections.setdefault(current, []).append(line)
        return {key: "\n".join(value).strip() for key, value in sections.items() if "\n".join(value).strip()}

    @staticmethod
    def _normalize_summary_heading(value: str) -> str:
        value = re.sub(r"^[一二三四五六七八九十0-9]+[.、．]\s*", "", value.strip())
        aliases = {
            "1. 背景": "背景",
            "2. 核心观点": "核心观点",
            "3. 关键事实": "关键事实",
            "4. 作者判断": "作者判断",
            "核心内容预览": "核心摘要",
            "后续跟踪": "后续跟踪问题",
        }
        return aliases.get(value, value)

    def _detail_url(self, aweme_id: str) -> str:
        base_url = str(self.config.get("app.web_base_url", "http://172.30.10.150:8765") or "http://172.30.10.150:8765").rstrip("/")
        return f"{base_url}/aweme?id={aweme_id}"

    def _publish_markdown(self, path: Path, title: str = "") -> str:
        try:
            return self.publisher.publish_markdown(path, title)
        except Exception as exc:
            logger.warning("发布 Markdown 到 GitHub Pages 输出目录失败: path=%s error=%s", path, exc)
            return ""

    def _resolve_research_target(self, value: str) -> BloggerTarget:
        keyword = str(value or "").strip()
        if not keyword:
            raise ValueError("必须指定研究博主名称、sec_uid 或主页链接")
        targets = self.checker.load_targets()
        for target in targets:
            if keyword in {target.name, target.sec_uid, target.url}:
                return target
            if keyword in target.name or keyword in target.sec_uid or keyword in target.url:
                return target

        sec_uid = Checker._extract_sec_uid(keyword)
        url = keyword if keyword.startswith("http") else ""
        if not sec_uid and keyword.startswith("MS4w"):
            sec_uid = keyword
            url = f"https://www.douyin.com/user/{sec_uid}"
        if not sec_uid:
            raise ValueError(f"无法匹配或解析研究博主: {keyword}")
        name = sec_uid
        blogger_id = self.database.upsert_blogger(url=url or f"https://www.douyin.com/user/{sec_uid}", name=name, sec_uid=sec_uid, enabled=False)
        return BloggerTarget(id=blogger_id, sec_uid=sec_uid, name=name, url=url or f"https://www.douyin.com/user/{sec_uid}")

    def _target_with_discovered_name(self, target: BloggerTarget, awemes: list[dict[str, Any]]) -> BloggerTarget:
        for aweme in awemes:
            name = self._extract_aweme_author_name(aweme)
            if name and name != target.sec_uid:
                self.database.upsert_blogger(url=target.url, name=name, sec_uid=target.sec_uid, enabled=self._is_configured_sec_uid(target.sec_uid))
                return BloggerTarget(id=target.id, sec_uid=target.sec_uid, name=name, url=target.url)
        return target

    def _is_configured_sec_uid(self, sec_uid: str) -> bool:
        bloggers = self.config.get("bloggers", []) or []
        if not isinstance(bloggers, list):
            return False
        for item in bloggers:
            if not isinstance(item, dict):
                continue
            configured = str(item.get("sec_uid") or Checker._extract_sec_uid(str(item.get("url") or "")))
            if configured == sec_uid and bool(item.get("enabled", True)):
                return True
        return False

    @staticmethod
    def _extract_aweme_author_name(aweme: dict[str, Any]) -> str:
        author = aweme.get("author") if isinstance(aweme.get("author"), dict) else {}
        author_user = aweme.get("author_user_info") if isinstance(aweme.get("author_user_info"), dict) else {}
        return str(
            author.get("nickname")
            or author_user.get("nickname")
            or aweme.get("nickname")
            or aweme.get("author_name")
            or ""
        ).strip()

    @staticmethod
    def _filter_awemes_by_time(awemes: list[dict[str, Any]], since: str = "", until: str = "") -> list[dict[str, Any]]:
        since_ts = Workflow._date_to_timestamp(since, start=True) if since else None
        until_ts = Workflow._date_to_timestamp(until, start=False) if until else None
        result = []
        for aweme in awemes:
            try:
                create_time = int(aweme.get("create_time") or 0)
            except (TypeError, ValueError):
                create_time = 0
            if since_ts is not None and create_time and create_time < since_ts:
                continue
            if until_ts is not None and create_time and create_time > until_ts:
                continue
            result.append(aweme)
        return result

    @staticmethod
    def _date_to_timestamp(value: str, start: bool) -> int:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"日期格式必须为 YYYY-MM-DD: {value}") from exc
        if not start:
            dt = dt.replace(hour=23, minute=59, second=59)
        return int(dt.timestamp())

    def _update_research_counts(self, job_id: int, stats: dict[str, Any], total: int) -> None:
        pending = max(0, total - int(stats.get("processed", 0)) - int(stats.get("failed", 0)) - int(stats.get("skipped", 0)))
        self.database.update_research_job(
            job_id,
            total_count=total,
            pending_count=pending,
            success_count=int(stats.get("processed", 0)),
            failed_count=int(stats.get("failed", 0)),
            skipped_count=int(stats.get("skipped", 0)),
        )

    @staticmethod
    def _iter_chunks(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
        chunk_size = max(1, int(size or 1))
        return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]

    def _config_with_overrides(self, overrides: dict[str, Any]) -> AppConfig:
        raw = deepcopy(self.config.raw)
        for dotted_key, value in overrides.items():
            target: dict[str, Any] = raw
            parts = dotted_key.split(".")
            for key in parts[:-1]:
                current = target.get(key)
                if not isinstance(current, dict):
                    current = {}
                    target[key] = current
                target = current
            target[parts[-1]] = value
        return AppConfig(raw=raw, path=self.config.path)

    @staticmethod
    def _transcript_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "success",
            "text": str(row.get("text_content") or ""),
            "text_path": str(row.get("text_path") or ""),
            "txt_path": str(row.get("text_path") or ""),
            "json_path": str(row.get("json_path") or ""),
            "model": str(row.get("model") or ""),
        }

    @staticmethod
    def _public_video_url(aweme_id: str, raw_url: str = "") -> str:
        if aweme_id and (not raw_url or "/aweme/v1/play/" in raw_url):
            return f"https://www.douyin.com/video/{aweme_id}"
        return raw_url

    @staticmethod
    def _load_original_text(item: dict[str, str]) -> str:
        text = str(item.get("text") or "").strip()
        if text:
            return text
        text_path = str(item.get("text_path") or "")
        if not text_path:
            return ""
        path = Path(text_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        try:
            return datetime.fromtimestamp(int(value)).strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError, OSError, OverflowError):
            return ""
