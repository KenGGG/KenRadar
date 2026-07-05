from __future__ import annotations

from typing import Any


class RetryManager:
    def __init__(self, workflow: Any):
        self.workflow = workflow

    async def retry_summary(self, aweme_id: str) -> dict[str, Any]:
        workflow = self.workflow
        data = workflow._load_aweme_for_retry(aweme_id)
        if not data.get("text_content") and not data.get("text_path"):
            raise ValueError(f"该作品没有可用转录文本: {aweme_id}")
        return workflow._summarize_transcript_row(data, workflow_name="retry_summary")

    async def retry_download(self, aweme_id: str) -> dict[str, Any]:
        workflow = self.workflow
        data = workflow._load_aweme_for_retry(aweme_id)
        aweme = workflow._rebuild_aweme_dict(data)
        blogger_name = str(data.get("nickname") or "未知博主")
        blogger_id = str(data.get("blogger_id") or "")
        item = await workflow._process_aweme_for_push(aweme, blogger_name, blogger_id, workflow_name="retry_download")
        return workflow._retry_result(aweme_id, item, "retry_download")

    async def retry_transcribe(self, aweme_id: str) -> dict[str, Any]:
        workflow = self.workflow
        data = workflow._load_aweme_for_retry(aweme_id)
        video_path = workflow._find_local_video(aweme_id, data)
        if video_path is None:
            raise ValueError(f"找不到本地视频文件，请先重试下载: {aweme_id}")
        aweme = workflow._rebuild_aweme_dict(data)
        blogger_name = str(data.get("nickname") or "未知博主")
        blogger_id = str(data.get("blogger_id") or "")
        item = await workflow._process_aweme_for_push(aweme, blogger_name, blogger_id, workflow_name="retry_transcribe", video_path=video_path)
        return workflow._retry_result(aweme_id, item, "retry_transcribe")

    async def retry_full_pipeline(self, aweme_id: str) -> dict[str, Any]:
        workflow = self.workflow
        data = workflow._load_aweme_for_retry(aweme_id)
        if workflow._find_local_video(aweme_id, data) is not None:
            return await self.retry_transcribe(aweme_id)
        return await self.retry_download(aweme_id)

    async def retry_batch(self, aweme_ids: list[str], retry_from: str = "auto", on_progress: Any = None) -> dict[str, Any]:
        workflow = self.workflow
        cleaned = [str(item).strip() for item in aweme_ids if str(item).strip()]
        stats: dict[str, Any] = {"total": len(cleaned), "success": 0, "failed": 0, "items": []}
        for index, aweme_id in enumerate(cleaned, start=1):
            if on_progress:
                on_progress(index, len(cleaned), aweme_id, "resolving", f"正在解析重试阶段 ({index}/{len(cleaned)})")
            try:
                stage = workflow._resolve_retry_stage(aweme_id, retry_from)
                stage_label = {"download": "下载视频", "transcribe": "转录", "ai": "Agnes AI 整理"}.get(stage, stage)
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
                self.sync_research_items_after_retry(aweme_id, ok, str(result.get("error") or ""))
                if on_progress:
                    status_text = "完成" if ok else "失败"
                    on_progress(index, len(cleaned), aweme_id, "done" if ok else "failed", f"[{status_text}] {aweme_id} ({index}/{len(cleaned)})")
            except Exception as exc:
                stats["failed"] += 1
                stats["items"].append({"aweme_id": aweme_id, "retry_from": retry_from, "status": "failed", "error": str(exc)})
                self.sync_research_items_after_retry(aweme_id, False, str(exc))
                if on_progress:
                    on_progress(index, len(cleaned), aweme_id, "failed", f"[失败] {aweme_id}: {exc} ({index}/{len(cleaned)})")
        if on_progress:
            on_progress(len(cleaned), len(cleaned), "", "completed", f"全部完成: {stats['success']} 成功, {stats['failed']} 失败")
        return stats

    def sync_research_items_after_retry(self, aweme_id: str, ok: bool, error: str = "") -> None:
        if not aweme_id:
            return
        status = "success" if ok else "failed"
        error_message = None if ok else (error or "内容级重试失败")
        with self.workflow.database.connect() as conn:
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
