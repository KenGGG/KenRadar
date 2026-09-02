"""PostgreSQL contract tests for the durable task engine.

These tests lock the behaviour V2 depends on: idempotent enqueue, deterministic
claim order, lease recovery and cooperative pause/resume/cancel.
"""

from __future__ import annotations

from typing import Any

import pytest

from kenradar.storage.pg_database import Database


def test_paused_task_is_not_claimed_until_resumed(task_db: Database) -> None:
    row = task_db.enqueue_task_run("backfill", {}, "batch")
    task_db.request_task_pause(row["id"])
    task_db.pause_task_run(row["id"], {"item_id": 42})

    assert task_db.claim_next_task_run("worker") is None

    task_db.resume_task_run(row["id"])
    claimed = task_db.claim_next_task_run("worker")
    assert claimed["id"] == row["id"]
    assert claimed["checkpoint_json"] == {"item_id": 42}


def test_paused_task_survives_service_restart(task_db: Database) -> None:
    row = task_db.enqueue_task_run("backfill", {}, "batch")
    task_db.request_task_pause(row["id"])
    task_db.pause_task_run(row["id"], {"cursor": "page-3"})

    # A fresh database handle stands in for a restarted process.
    restarted = Database(task_db.database_url)
    try:
        assert restarted.get_task_run(row["id"])["status"] == "paused"
        assert restarted.claim_next_task_run("worker") is None
        assert restarted.control_state(row["id"])["checkpoint"] == {"cursor": "page-3"}
    finally:
        restarted.close()


def test_control_state_reports_pause_and_cancel_requests(task_db: Database) -> None:
    row = task_db.enqueue_task_run("backfill", {}, "batch")
    assert task_db.control_state(row["id"]) == {
        "status": "queued",
        "pause_requested": False,
        "cancel_requested": False,
        "checkpoint": {},
    }

    task_db.request_task_pause(row["id"])
    state = task_db.control_state(row["id"])
    assert state["pause_requested"] is True
    assert state["cancel_requested"] is False


def test_expired_lease_marks_orphan_attempt_abandoned(task_db: Database) -> None:
    row = task_db.enqueue_task_run("backfill", {}, "crash", idempotency_key="crash-1")
    task_db.claim_next_task_run("worker-a")
    attempt_id = task_db.start_task_attempt(row["id"], "worker-a")

    _set_lease_expired(task_db, row["id"])
    task_db.claim_next_task_run("worker-b")

    with task_db.connect() as conn:
        attempt = conn.execute(
            "SELECT status, error_code, finished_at FROM task_attempt WHERE id = %s",
            (attempt_id,),
        ).fetchone()
    assert attempt["status"] == "abandoned"
    assert attempt["error_code"] == "WORKER_LEASE_EXPIRED"
    assert attempt["finished_at"] is not None


def test_permanent_error_fails_without_retry(task_db: Database) -> None:
    row = task_db.enqueue_task_run("process_url", {}, "private", max_attempts=5, idempotency_key="private-1")
    task_db.claim_next_task_run("worker")

    assert task_db.fail_task_run(row["id"], "内容已删除", error_code="CONTENT_DELETED") is False
    stored = task_db.get_task_run(row["id"])
    assert stored["status"] == "failed"
    assert stored["error_code"] == "CONTENT_DELETED"
    assert stored["finished_at"] is not None


def test_classified_transient_error_is_retried_with_backoff(task_db: Database) -> None:
    row = task_db.enqueue_task_run("process_url", {}, "rate", max_attempts=5, idempotency_key="rate-1")
    task_db.claim_next_task_run("worker")

    assert task_db.fail_task_run(row["id"], "限流", error_code="RATE_LIMITED") is True
    stored = task_db.get_task_run(row["id"])
    assert stored["status"] == "retry_wait"
    assert stored["error_code"] == "RATE_LIMITED"
    assert stored["available_at"] > stored["created_at"]


def test_retry_delay_is_bounded() -> None:
    from kenradar.domain.states import (
        MAX_RETRY_DELAY_SECONDS,
        is_permanent_error,
        retry_delay_seconds,
    )

    assert retry_delay_seconds(1) == 30
    assert retry_delay_seconds(2) == 60
    assert retry_delay_seconds(3) == 120
    assert retry_delay_seconds(50) == MAX_RETRY_DELAY_SECONDS
    assert is_permanent_error("AUTH_REQUIRED") is True
    assert is_permanent_error("RATE_LIMITED") is False
    assert is_permanent_error("") is False


def _set_lease_expired(database: Database, task_run_id: int) -> None:
    with database.connect() as conn:
        conn.execute(
            "UPDATE task_run SET lease_expires_at = NOW() - INTERVAL '1 second' WHERE id = %s",
            (task_run_id,),
        )


def _table_columns(database: Database, table_name: str) -> set[str]:
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table_name,),
        ).fetchall()
    return {str(row["column_name"]) for row in rows}


def test_task_run_schema_supports_pause_and_checkpoint(task_db: Database) -> None:
    columns = _table_columns(task_db, "task_run")
    assert {
        "pause_requested_at",
        "paused_at",
        "resumed_at",
        "error_code",
        "checkpoint_json",
        "parent_task_run_id",
    } <= columns


def test_task_attempt_schema_supports_standard_error_codes(task_db: Database) -> None:
    assert "error_code" in _table_columns(task_db, "task_attempt")


def test_task_run_claims_highest_priority_and_reuses_idempotency_key(task_db: Database) -> None:
    low = task_db.enqueue_task_run("backfill", {}, "low", priority=20, idempotency_key="low")
    high = task_db.enqueue_task_run("process_url", {}, "high", priority=100, idempotency_key="high")
    duplicate = task_db.enqueue_task_run("process_url", {}, "duplicate", priority=100, idempotency_key="high")

    assert duplicate["id"] == high["id"]
    assert low["id"] != high["id"]
    assert task_db.claim_next_task_run("test")["id"] == high["id"]


def test_task_run_without_idempotency_key_is_never_deduplicated(task_db: Database) -> None:
    first = task_db.enqueue_task_run("process_url", {}, "first", priority=100)
    second = task_db.enqueue_task_run("process_url", {}, "second", priority=100)

    assert first["id"] != second["id"]


def test_claim_follows_priority_then_creation_order(task_db: Database) -> None:
    older = task_db.enqueue_task_run("backfill", {}, "older", priority=20)
    newer = task_db.enqueue_task_run("backfill", {}, "newer", priority=20)
    urgent = task_db.enqueue_task_run("process_url", {}, "urgent", priority=90)

    assert task_db.claim_next_task_run("worker-a")["id"] == urgent["id"]
    assert task_db.claim_next_task_run("worker-b")["id"] == older["id"]
    assert task_db.claim_next_task_run("worker-c")["id"] == newer["id"]


def test_expired_lease_is_requeued_for_another_worker(task_db: Database) -> None:
    row = task_db.enqueue_task_run("process_url", {}, "leased", priority=80, idempotency_key="lease-1")
    claimed = task_db.claim_next_task_run("worker-a")
    assert claimed["id"] == row["id"]
    assert task_db.claim_next_task_run("worker-b") is None

    _set_lease_expired(task_db, row["id"])
    recovered = task_db.claim_next_task_run("worker-b")
    assert recovered is not None
    assert recovered["id"] == row["id"]
    assert int(recovered["attempt"]) == 2
