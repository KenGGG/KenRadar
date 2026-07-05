from __future__ import annotations

import json
from typing import Any


class TaskRunRepository:
    def __init__(self, database: Any):
        self.database = database

    def enqueue_task_run(
        self,
        task_type: str,
        payload: dict[str, Any],
        message: str,
        requested_by: str = "web",
        *,
        priority: int = 50,
        idempotency_key: str = "",
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO task_run (
                    task_type, payload_json, message, requested_by, priority,
                    idempotency_key, max_attempts, status, available_at, created_at, updated_at
                )
                VALUES (%s, %s::jsonb, %s, %s, %s, NULLIF(%s, ''), %s, 'queued', NOW(), NOW(), NOW())
                ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
                DO UPDATE SET updated_at = task_run.updated_at
                RETURNING id, task_type, message, requested_by, priority, idempotency_key,
                          attempt, max_attempts, status, created_at
                """,
                (
                    task_type,
                    json.dumps(payload or {}, ensure_ascii=False),
                    message,
                    requested_by,
                    int(priority),
                    idempotency_key,
                    max(1, int(max_attempts)),
                ),
            ).fetchone()
            return dict(row) if row else {}

    def claim_next_task_run(self, worker_name: str, lease_seconds: int = 300) -> dict[str, Any] | None:
        lease_seconds = max(30, int(lease_seconds or 300))
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE task_run
                SET status = CASE WHEN attempt < max_attempts THEN 'queued' ELSE 'failed' END,
                    worker_name = '',
                    finished_at = CASE WHEN attempt < max_attempts THEN NULL ELSE NOW() END,
                    last_error = CASE
                        WHEN attempt < max_attempts THEN last_error
                        ELSE COALESCE(last_error, '任务 lease 过期且已达到最大尝试次数')
                    END,
                    updated_at = NOW()
                WHERE status = 'running'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < NOW()
                """
            )
            row = conn.execute(
                """
                WITH candidate AS (
                    SELECT id
                    FROM task_run
                    WHERE status IN ('queued', 'retry_wait')
                      AND available_at <= NOW()
                      AND cancel_requested_at IS NULL
                    ORDER BY priority DESC, available_at, created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE task_run
                SET status = 'running',
                    worker_name = %s,
                    started_at = COALESCE(started_at, NOW()),
                    lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                    heartbeat_at = NOW(),
                    attempt = attempt + 1,
                    updated_at = NOW()
                WHERE id = (SELECT id FROM candidate)
                RETURNING id, task_type, payload_json, message, requested_by, priority,
                          idempotency_key, attempt, max_attempts, status, created_at,
                          started_at, updated_at
                """,
                (worker_name, lease_seconds),
            ).fetchone()
            return dict(row) if row else None

    def heartbeat_task_run(
        self,
        task_run_id: int,
        lease_seconds: int = 300,
        progress: dict[str, Any] | None = None,
    ) -> None:
        lease_seconds = max(30, int(lease_seconds or 300))
        progress_json = json.dumps(progress or {}, ensure_ascii=False)
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE task_run
                SET lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                    heartbeat_at = NOW(),
                    progress_json = CASE WHEN %s::jsonb = '{}'::jsonb THEN progress_json ELSE %s::jsonb END,
                    updated_at = NOW()
                WHERE id = %s AND status = 'running'
                """,
                (lease_seconds, progress_json, progress_json, task_run_id),
            )

    def complete_task_run(self, task_run_id: int, stats: dict[str, Any] | None = None) -> None:
        stats_json = json.dumps(stats or {}, ensure_ascii=False)
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE task_run
                SET status = 'success',
                    stats_json = %s::jsonb,
                    finished_at = NOW(),
                    lease_expires_at = NULL,
                    heartbeat_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s AND status = 'running'
                """,
                (stats_json, task_run_id),
            )
        self.database.insert_state_transition("task_run", str(task_run_id), "running", "success", actor="system")

    def fail_task_run(self, task_run_id: int, error_message: str, retry_delay_seconds: int = 30) -> bool:
        with self.database.connect() as conn:
            old = conn.execute(
                "SELECT status FROM task_run WHERE id = %s", (task_run_id,)
            ).fetchone()
            old_status = str(old["status"]) if old else "unknown"
            row = conn.execute(
                """
                UPDATE task_run
                SET status = CASE
                        WHEN cancel_requested_at IS NOT NULL THEN 'cancelled'
                        WHEN attempt < max_attempts THEN 'retry_wait'
                        ELSE 'failed'
                    END,
                    last_error = %s,
                    available_at = CASE
                        WHEN cancel_requested_at IS NULL AND attempt < max_attempts
                        THEN NOW() + (%s * INTERVAL '1 second')
                        ELSE available_at
                    END,
                    finished_at = CASE
                        WHEN cancel_requested_at IS NOT NULL OR attempt >= max_attempts THEN NOW()
                        ELSE NULL
                    END,
                    lease_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING status
                """,
                (error_message, max(1, int(retry_delay_seconds)), task_run_id),
            ).fetchone()
            new_status = str(row["status"]) if row else "failed"
            self.database.insert_state_transition(
                "task_run",
                str(task_run_id),
                old_status,
                new_status,
                reason=error_message,
                actor="system",
            )
            return new_status == "retry_wait"

    def request_task_cancel(self, task_run_id: int, reason: str = "") -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE task_run
                SET cancel_requested_at = NOW(),
                    last_error = %s,
                    status = CASE WHEN status IN ('queued', 'retry_wait') THEN 'cancelled' ELSE status END,
                    finished_at = CASE WHEN status IN ('queued', 'retry_wait') THEN NOW() ELSE finished_at END,
                    updated_at = NOW()
                WHERE id = %s AND status NOT IN ('success', 'failed', 'cancelled')
                """,
                (reason, task_run_id),
            )

    def mark_task_cancelled(self, task_run_id: int, reason: str = "") -> None:
        with self.database.connect() as conn:
            old = conn.execute(
                "SELECT status FROM task_run WHERE id = %s", (task_run_id,)
            ).fetchone()
            old_status = str(old["status"]) if old else "unknown"
            conn.execute(
                """
                UPDATE task_run
                SET status = 'cancelled',
                    cancel_requested_at = COALESCE(cancel_requested_at, NOW()),
                    last_error = %s,
                    finished_at = NOW(),
                    lease_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (reason, task_run_id),
            )
        self.database.insert_state_transition(
            "task_run",
            str(task_run_id),
            old_status,
            "cancelled",
            reason=reason or None,
            actor="system",
        )

    def cancel_task_run(self, task_run_id: int, reason: str = "") -> None:
        self.request_task_cancel(task_run_id, reason)

    def cancel_active_task_runs(self, reason: str = "") -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE task_run
                SET cancel_requested_at = NOW(),
                    last_error = %s,
                    status = 'cancelled',
                    finished_at = NOW(),
                    lease_expires_at = NULL,
                    updated_at = NOW()
                WHERE status IN ('queued', 'retry_wait', 'running')
                """,
                (reason,),
            )

    def is_task_cancel_requested(self, task_run_id: int) -> bool:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT cancel_requested_at IS NOT NULL AS requested FROM task_run WHERE id = %s",
                (task_run_id,),
            ).fetchone()
            return bool(row and row["requested"])

    def get_task_run(self, task_run_id: int) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM task_run WHERE id = %s", (task_run_id,)).fetchone()
            return dict(row) if row else None

    def start_task_attempt(self, task_run_id: int, worker_name: str) -> int:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO task_attempt (task_run_id, attempt_no, worker_name, status, started_at)
                SELECT id, attempt, %s, 'running', NOW()
                FROM task_run
                WHERE id = %s
                RETURNING id
                """,
                (worker_name, task_run_id),
            ).fetchone()
            return int(row["id"]) if row else 0

    def finish_task_attempt(self, attempt_id: int, status: str, error_message: str = "") -> None:
        if attempt_id <= 0:
            return
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE task_attempt
                SET status = %s,
                    error_message = NULLIF(%s, ''),
                    finished_at = NOW()
                WHERE id = %s
                """,
                (status, error_message, attempt_id),
            )

    def list_queued_task_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, task_type, message, requested_by, status, created_at
                FROM task_run
                WHERE status IN ('queued', 'retry_wait')
                ORDER BY priority DESC, available_at, created_at, id
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_latest_active_task_run(self) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, task_type, message, requested_by, status, progress_json, stats_json,
                       last_error, created_at, started_at, finished_at, updated_at
                FROM task_run
                WHERE status IN ('running', 'queued', 'retry_wait')
                ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END,
                         priority DESC, available_at, created_at, id
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    def get_latest_task_run(self) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, task_type, message, requested_by, status, progress_json, stats_json,
                       last_error, created_at, started_at, finished_at, updated_at
                FROM task_run
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None
