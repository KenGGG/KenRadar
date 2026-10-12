"""Independent delivery audit, sharing the worker's fenced transactions."""
from sqlalchemy import insert, select, update, literal, union_all
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


class PublicationRepository:
    def __init__(self, database):
        self.database = database

    def _start(self, table, values, key):
        t = self.database.table(table)
        with self.database.connect(write=True) as conn:
            stmt = sqlite_insert(t).values(**values).on_conflict_do_nothing().returning(t)
            row = conn.execute(stmt).fetchone()
            if row is None:
                row = conn.execute(select(t).where(t.c.idempotency_key == key)).fetchone()
            return dict(row)

    def start(self, content_item_id, source_hash, idempotency_key):
        return self._start("publication_log", dict(content_item_id=content_item_id, source_hash=source_hash,
            idempotency_key=idempotency_key, status="running"), idempotency_key)

    def start_notification(self, content_item_id, external_id, source_hash):
        key = f"notify:{content_item_id}:{source_hash}"
        return self._start("push_log", dict(content_item_id=content_item_id, aweme_id=str(external_id),
            batch_id=f"content:{content_item_id}", channel="feishu", message_type="card", status="running", idempotency_key=key), key)

    def _update(self, table, record_id, **values):
        from .sqlite_database import utc_now
        t = self.database.table(table)
        with self.database.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == record_id).values(updated_at=utc_now(), **values))

    def complete(self, publication_id, target_url=""):
        from .sqlite_database import utc_now
        self._update("publication_log", publication_id, status="success", target_url=target_url,
            error_message=None, completed_at=utc_now())

    def fail(self, publication_id, error_message):
        self._update("publication_log", publication_id, status="failed", error_message=error_message)

    def complete_notification(self, push_log_id, target_url=""):
        from .sqlite_database import utc_now
        self._update("push_log", push_log_id, status="success", target_url=target_url, error_message=None, pushed_at=utc_now())

    def fail_notification(self, push_log_id, error_message):
        self._update("push_log", push_log_id, status="failed", error_message=error_message)

    def find_success(self, content_item_id, source_hash):
        t = self.database.table("publication_log")
        with self.database.connect() as conn:
            row = conn.execute(select(t).where(t.c.content_item_id == content_item_id,
                t.c.source_hash == source_hash, t.c.status == "success").order_by(t.c.id.desc()).limit(1)).fetchone()
            return dict(row) if row else None

    def find_notification_success(self, content_item_id, source_hash):
        t = self.database.table("push_log")
        with self.database.connect() as conn:
            row = conn.execute(select(t).where(t.c.content_item_id == content_item_id,
                t.c.idempotency_key == f"notify:{content_item_id}:{source_hash}", t.c.status == "success")).fetchone()
            return dict(row) if row else None

    def list_operations(self, content_item_id, limit=100):
        p, n = self.database.table("publication_log"), self.database.table("push_log")
        fields = lambda t: (t.c.id, t.c.status, t.c.target_url, t.c.error_message, t.c.attempt_count)
        stmt = union_all(select(literal("publication").label("operation"), *fields(p), p.c.created_at, p.c.updated_at, p.c.completed_at)
            .where(p.c.content_item_id == content_item_id), select(literal("notification"), *fields(n),
            n.c.pushed_at.label("created_at"), n.c.updated_at, n.c.pushed_at.label("completed_at"))
            .where(n.c.content_item_id == content_item_id, n.c.idempotency_key.is_not(None))).subquery()
        with self.database.connect() as conn:
            return [dict(r) for r in conn.execute(select(stmt).order_by(stmt.c.created_at.desc(), stmt.c.id.desc())
                .limit(max(1, min(limit, 200)))).fetchall()]
