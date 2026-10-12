"""Step/outbox leases with the same short-transaction fencing discipline."""
from __future__ import annotations

import json
import uuid
from sqlalchemy import insert, select, update, and_, or_, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from kenradar.storage.sqlite_database import LeaseLost, utc_now


class Runtime:
    def __init__(self, db):
        self.db = db

    def _transition(self, conn, record, old, new, reason=""):
        conn.execute(insert(self.db.table("state_transition")).values(
            object_type="task_step", object_id=str(record["id"]), old_status=old,
            new_status=new, reason=reason, actor=record.get("locked_by") or "system"))

    def enqueue_task_step(self, task_run_id, content_item_id, stage, input_version=None, priority=50, max_attempts=3):
        t = self.db.table("task_step")
        stmt = sqlite_insert(t).values(task_run_id=task_run_id, content_item_id=content_item_id, stage=stage,
            input_version=input_version, priority=priority, max_attempts=max(1, max_attempts)).on_conflict_do_nothing().returning(t.c.id)
        with self.db.connect(write=True) as conn:
            row = conn.execute(stmt).fetchone()
            if not row:
                row = conn.execute(select(t.c.id).where(t.c.content_item_id == content_item_id,
                    t.c.stage == stage, t.c.input_version == input_version)).fetchone()
            return row["id"]

    def claim_next_task_step(self, stages, worker_name, lease_seconds=300):
        t = self.db.table("task_step")
        with self.db.connect(write=True) as conn:
            now = utc_now()
            expired = conn.execute(select(t).where(t.c.status == "running", t.c.lease_expires_at <= now)).fetchall()
            for old in expired:
                state = "retry_wait" if old["attempt"] < old["max_attempts"] else "failed"
                conn.execute(update(t).where(t.c.id == old["id"]).values(status=state,
                    lease_token=None, locked_by=None, error_code="WORKER_LEASE_EXPIRED",
                    lease_expires_at=None, available_at=now, finished_at=now if state == "failed" else None))
                self._transition(conn, old, "running", state, "WORKER_LEASE_EXPIRED")
            conn.execute(update(t).where(t.c.status == "retry_wait", t.c.attempt >= t.c.max_attempts).values(status="failed", finished_at=now))
            row = conn.execute(select(t).where(t.c.stage.in_(stages), t.c.status.in_(("pending", "retry_wait")),
                t.c.available_at <= now).order_by(t.c.priority.desc(), t.c.available_at, t.c.created_at, t.c.id).limit(1)).fetchone()
            if not row:
                return None
            result = conn.execute(update(t).where(t.c.id == row["id"]).values(status="running", locked_by=worker_name,
                lease_token=uuid.uuid4().hex, attempt=t.c.attempt + 1, locked_at=now, heartbeat_at=now,
                started_at=func.coalesce(t.c.started_at, now), lease_expires_at=utc_now(lease_seconds), updated_at=now).returning(t)).fetchone()
            self._transition(conn, dict(result), row["status"], "running")
            return dict(result)

    def _assert(self, conn, record, table, owner_column):
        t = self.db.table(table)
        if not record or not record.get("lease_token"):
            raise LeaseLost("必须提供本次领取的步骤/事件租约")
        row = conn.execute(select(t.c.id).where(t.c.id == record["id"], t.c.status == "running",
            t.c.lease_token == record["lease_token"], t.c[owner_column] == record[owner_column],
            t.c.lease_expires_at > utc_now(), t.c.attempt == record["attempt"])).fetchone()
        if not row:
            raise LeaseLost("步骤/事件租约已失效")

    def complete_task_step(self, step_id, output_ref=None, *, lease):
        t = self.db.table("task_step")
        with self.db.connect(write=True) as conn:
            self._assert(conn, lease, "task_step", "locked_by")
            if lease["id"] != step_id:
                raise LeaseLost("步骤身份不一致")
            conn.execute(update(t).where(t.c.id == step_id).values(status="success", output_ref=json.dumps(output_ref or {}),
                finished_at=utc_now(), lease_token=None, lease_expires_at=None, updated_at=utc_now()))
            self._transition(conn, lease, "running", "success")

    def heartbeat_task_step(self, step_id, lease_seconds=300, *, lease):
        t = self.db.table("task_step")
        with self.db.connect(write=True) as conn:
            self._assert(conn, lease, "task_step", "locked_by")
            if lease["id"] != step_id:
                raise LeaseLost("步骤身份不一致")
            conn.execute(update(t).where(t.c.id == step_id).values(heartbeat_at=utc_now(), lease_expires_at=utc_now(lease_seconds)))

    def fail_task_step(self, step_id, error_message, retry_delay_seconds=30, *, lease):
        t = self.db.table("task_step")
        retry = lease["attempt"] < lease["max_attempts"]
        with self.db.connect(write=True) as conn:
            self._assert(conn, lease, "task_step", "locked_by")
            if lease["id"] != step_id:
                raise LeaseLost("步骤身份不一致")
            conn.execute(update(t).where(t.c.id == step_id).values(status="retry_wait" if retry else "failed",
                error_message=error_message, lease_token=None, lease_expires_at=None, available_at=utc_now(retry_delay_seconds),
                finished_at=None if retry else utc_now()))
            self._transition(conn, lease, "running", "retry_wait" if retry else "failed", error_message)
        return retry

    def write_outbox_event(self, event_type, payload, aggregate_type=None, aggregate_id=None, idempotency_key=None):
        t = self.db.table("outbox_event")
        stmt = sqlite_insert(t).values(event_type=event_type, payload_json=json.dumps(payload, ensure_ascii=False),
            aggregate_type=aggregate_type, aggregate_id=aggregate_id, idempotency_key=idempotency_key).on_conflict_do_nothing().returning(t.c.id)
        with self.db.connect(write=True) as conn:
            row = conn.execute(stmt).fetchone()
            if not row and idempotency_key:
                row = conn.execute(select(t.c.id).where(t.c.idempotency_key == idempotency_key)).fetchone()
            return row["id"] if row else None

    def claim_outbox_events(self, batch_size=10, owner="outbox_consumer"):
        t = self.db.table("outbox_event")
        with self.db.connect(write=True) as conn:
            # Remote effect may already have happened. Expired delivery is unknown,
            # not retried automatically. A user must reconcile its remote state.
            conn.execute(update(t).where(t.c.status == "running", t.c.lease_expires_at < utc_now()).values(
                status="unknown", last_error="LEASE_EXPIRED_REMOTE_RESULT_UNKNOWN", lease_token=None))
            rows = conn.execute(select(t).where(t.c.status == "pending", t.c.available_at <= utc_now()).order_by(t.c.available_at, t.c.id).limit(batch_size)).fetchall()
            result = []
            for row in rows:
                claimed = conn.execute(update(t).where(t.c.id == row["id"]).values(status="running", locked_by=owner,
                    lease_token=uuid.uuid4().hex, locked_at=utc_now(), lease_expires_at=utc_now(300), attempt=t.c.attempt + 1).returning(t)).fetchone()
                result.append(dict(claimed))
            return result

    def complete_outbox_event(self, event_id, *, lease):
        t = self.db.table("outbox_event")
        with self.db.connect(write=True) as conn:
            self._assert(conn, lease, "outbox_event", "locked_by")
            if lease["id"] != event_id:
                raise LeaseLost("事件身份不一致")
            conn.execute(update(t).where(t.c.id == event_id).values(status="success", processed_at=utc_now(), lease_token=None))

    def fail_outbox_event(self, event_id, error, *, lease, uncertain=False):
        t = self.db.table("outbox_event")
        with self.db.connect(write=True) as conn:
            self._assert(conn, lease, "outbox_event", "locked_by")
            if lease["id"] != event_id:
                raise LeaseLost("事件身份不一致")
            conn.execute(update(t).where(t.c.id == event_id).values(status="unknown" if uncertain else "failed",
                last_error=error, lease_token=None, lease_expires_at=None))
