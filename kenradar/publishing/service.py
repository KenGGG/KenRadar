"""Delivery-only GitHub Pages publication for a current content result."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class PublicationService:
    def __init__(self, database: Any, publisher: Any, sync: Callable[[], Any]):
        self.database = database
        self.publisher = publisher
        self.sync = sync

    def publish_content(self, content_item_id: int, *, sync: bool = True, force: bool = False) -> dict[str, Any]:
        bundle = self.database.get_current_bundle(int(content_item_id))
        from kenradar.integrations.privacy import require_deliverable
        require_deliverable(bundle)
        if not bundle or not bundle.get("note"):
            raise ValueError(f"内容 #{content_item_id} 没有可发布的当前笔记")
        note = bundle["note"]
        note_path = str(note.get("note_path") or "")
        source_hash = str(note.get("content_sha256") or "")
        if not note_path or not source_hash:
            raise ValueError(f"内容 #{content_item_id} 缺少笔记路径或内容哈希")
        existing = self.database.publications.find_success(content_item_id, source_hash)
        if existing and not force:
            return {"status": "success", "skipped": True, "target_url": existing.get("target_url") or ""}

        record = self.database.publications.start(
            content_item_id, source_hash, f"publish:{content_item_id}:{source_hash}"
        )
        config = getattr(self.publisher, 'config', None)
        isolated_sync = bool(sync and config is not None and config.get('publishing.github_sync.enabled', False))
        try:
            if isolated_sync:
                self.publisher.publish_markdown(Path(note_path), str(note.get("title") or ""), update_index=False)
            else:
                self.publisher.publish_markdown(Path(note_path), str(note.get("title") or ""))
            import hashlib
            artifact_path = self.publisher.html_path_for(Path(note_path))
            # Static UTF-8 projection is committed with LF line endings;
            # Windows worktree CRLF must not alter the remote artifact receipt.
            artifact_hash = hashlib.sha256(artifact_path.read_text(encoding='utf8').encode('utf8')).hexdigest()
            target_url = str(self.publisher.public_url_for(Path(note_path)) or "")
            if sync:
                # Publish a single article from fresh origin, preserving remote
                # indexes and leaving unrelated local commits untouched.
                if isolated_sync:
                    from kenradar.publishing.github_sync import GithubSyncManager
                    manager = GithubSyncManager(config)
                    receipt = manager.sync_single_article(artifact_path, str(note.get('title') or ''))
                    if not receipt.get('pushed'):
                        raise RuntimeError('PUBLICATION_PENDING: article was not pushed')
                    artifact_hash = receipt['artifact_sha256']
                    manager.write_last_sync(receipt)
                else:
                    self.sync()
                self.database.publications.complete(int(record["id"]), target_url, artifact_sha256=artifact_hash)
        except Exception as exc:
            self.database.publications.fail(int(record["id"]), str(exc))
            raise
        return {"status": "success" if sync else "pending", "skipped": False, "target_url": target_url,
                "publication_id": int(record['id']), "artifact_sha256": artifact_hash}

    def publish_batch(self, research_job_id: int) -> dict[str, Any]:
        content_ids = self.database.get_research_job_content_ids(int(research_job_id))
        results = []
        try:
            for content_id in content_ids:
                results.append(self.publish_content(content_id, sync=False))
            pending = [result for result in results if not result.get('skipped')]
            if pending:
                self.sync()
                for result in pending:
                    self.database.publications.complete(result['publication_id'], result['target_url'],
                                                        artifact_sha256=result['artifact_sha256'])
        except Exception as exc:
            for result in results:
                if not result.get('skipped'):
                    self.database.publications.fail(result['publication_id'], str(exc))
            raise
        return {"status": "success", "research_job_id": int(research_job_id), "processed": len(results)}
