"""Delivery-only GitHub Pages publication for a current content result."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class PublicationService:
    def __init__(self, database: Any, publisher: Any, sync: Callable[[], Any]):
        self.database = database
        self.publisher = publisher
        self.sync = sync

    def publish_content(self, content_item_id: int, *, sync: bool = True) -> dict[str, Any]:
        bundle = self.database.get_current_bundle(int(content_item_id))
        if not bundle or not bundle.get("note"):
            raise ValueError(f"内容 #{content_item_id} 没有可发布的当前笔记")
        note = bundle["note"]
        note_path = str(note.get("note_path") or "")
        source_hash = str(note.get("content_sha256") or "")
        if not note_path or not source_hash:
            raise ValueError(f"内容 #{content_item_id} 缺少笔记路径或内容哈希")
        existing = self.database.publications.find_success(content_item_id, source_hash)
        if existing:
            return {"status": "success", "skipped": True, "target_url": existing.get("target_url") or ""}

        record = self.database.publications.start(
            content_item_id, source_hash, f"publish:{content_item_id}:{source_hash}"
        )
        try:
            self.publisher.publish_markdown(Path(note_path), str(bundle.get("content", {}).get("content_title") or ""))
            if sync:
                self.sync()
            target_url = str(self.publisher.public_url_for(Path(note_path)) or "")
            self.database.publications.complete(int(record["id"]), target_url)
        except Exception as exc:
            self.database.publications.fail(int(record["id"]), str(exc))
            raise
        return {"status": "success", "skipped": False, "target_url": target_url}

    def publish_batch(self, research_job_id: int) -> dict[str, Any]:
        content_ids = self.database.get_research_job_content_ids(int(research_job_id))
        results = [self.publish_content(content_id, sync=False) for content_id in content_ids]
        if any(not result.get("skipped") for result in results):
            self.sync()
        return {"status": "success", "research_job_id": int(research_job_id), "processed": len(results)}
