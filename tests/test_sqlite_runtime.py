from __future__ import annotations

import pytest
from sqlalchemy import update

from test_sqlite_v2 import sqlite_db
from kenradar.storage.sqlite_database import LeaseLost, utc_now


def test_step_recovery_fences_result_and_null_version(sqlite_db):
    db, _ = sqlite_db
    creator = db.upsert_creator("douyin", "001", "fixture", "")
    cid = db.upsert_content_item("douyin", "002", creator, title="fixture")
    step_id = db.enqueue_task_step(None, cid, "transcribe")
    assert db.enqueue_task_step(None, cid, "transcribe") == step_id
    old = db.claim_next_task_step(["transcribe"], "old")
    with db.connect(write=True) as conn:
        conn.execute(update(db.table("task_step")).where(db.table("task_step").c.id == step_id).values(lease_expires_at=utc_now(-1)))
    current = db.claim_next_task_step(["transcribe"], "new")
    assert current["attempt"] == 2
    with pytest.raises(LeaseLost), db.step_lease_scope(old):
        db.upsert_creator("douyin", "stale", "不能写入", "")
    with pytest.raises(LeaseLost):
        db.complete_task_step(step_id, lease=old)
    db.complete_task_step(step_id, {"fixture": True}, lease=current)
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM task_step").fetchone()[0] == "success"
        assert conn.execute("SELECT count(*) FROM state_transition WHERE object_type='task_step'").fetchone()[0] == 4


def test_outbox_remote_unknown_is_not_reclaimed(sqlite_db):
    db, _ = sqlite_db
    event_id = db.write_outbox_event("fixture", {}, idempotency_key="one")
    assert db.write_outbox_event("fixture", {}, idempotency_key="one") == event_id
    old = db.claim_outbox_events(owner="old")[0]
    with db.connect(write=True) as conn:
        conn.execute(update(db.table("outbox_event")).values(lease_expires_at=utc_now(-1)))
    assert db.claim_outbox_events(owner="new") == []
    with pytest.raises(LeaseLost):
        db.complete_outbox_event(event_id, lease=old)
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM outbox_event").fetchone()[0] == "unknown"


def test_step_completion_and_audit_are_atomic(sqlite_db, monkeypatch):
    db, _ = sqlite_db
    db.enqueue_task_step(None, None, "fetch", "one")
    step = db.claim_next_task_step(["fetch"], "worker")
    def failure(*args, **kwargs):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(db.runtime, "_transition", failure)
    with pytest.raises(RuntimeError, match="injected"):
        db.complete_task_step(step["id"], lease=step)
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM task_step").fetchone()[0] == "running"
