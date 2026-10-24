"""Delivery-only Feishu notification for a current content result."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class NotificationService:
    def __init__(self, database: Any, pusher: Any):
        self.database = database
        self.pusher = pusher

    def notify_content(self, content_item_id: int) -> dict[str, Any]:
        bundle = self.database.get_current_bundle(int(content_item_id))
        from kenradar.integrations.privacy import require_deliverable
        require_deliverable(bundle)
        if not bundle or not bundle.get("analysis"):
            raise ValueError(f"内容 #{content_item_id} 没有可通知的当前分析")
        content = bundle.get("content") or {}
        analysis = bundle.get("analysis") or {}
        note = bundle.get("note") or {}
        external_id = str(content.get("content_id") or "")
        source_hash = str(analysis.get("result_hash") or note.get("analysis_result_hash") or "")
        if not external_id or not source_hash:
            raise ValueError(f"内容 #{content_item_id} 缺少通知身份或结果哈希")
        existing = self.database.publications.find_notification_success(content_item_id, source_hash)
        if existing:
            return {"status": "success", "skipped": True, "target_url": existing.get("target_url") or ""}

        record = self.database.publications.start_notification(content_item_id, external_id, source_hash)
        item = {
            "aweme_id": external_id,
            "title": str(content.get("content_title") or external_id),
            "blogger_name": "未知来源",
            "text": str(analysis.get("result_text") or ""),
            "summary_status": str(analysis.get("analysis_status") or "success"),
            "note_path": str(note.get("note_path") or ""),
        }
        try:
            self.pusher.push([item])
            publisher = getattr(self.pusher, "publisher", None)
            target_url = ""
            if publisher is not None and note.get("note_path"):
                target_url = str(publisher.public_url_for(Path(str(note["note_path"]))) or "")
            self.database.publications.complete_notification(int(record["id"]), target_url)
        except Exception as exc:
            self.database.publications.fail_notification(int(record["id"]), str(exc))
            raise
        return {"status": "success", "skipped": False}

    def notify_batch(self, research_job_id: int) -> dict[str, Any]:
        content_ids = self.database.get_research_job_content_ids(int(research_job_id))
        results = [self.notify_content(content_id) for content_id in content_ids]
        return {"status": "success", "research_job_id": int(research_job_id), "processed": len(results)}
