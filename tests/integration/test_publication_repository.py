"""PostgreSQL contract tests for V2 publication idempotency."""

from __future__ import annotations

from kenradar.storage.pg_database import Database


def test_publication_idempotency_is_scoped_by_source_hash(content_db: Database, content_item: dict) -> None:
    repository = content_db.publications
    content_id = int(content_item["id"])
    first = repository.start(content_id, "hash-a", "publish:1:hash-a")
    duplicate = repository.start(content_id, "hash-a", "publish:1:hash-a")
    changed = repository.start(content_id, "hash-b", "publish:1:hash-b")

    assert first["id"] == duplicate["id"]
    assert changed["id"] != first["id"]
