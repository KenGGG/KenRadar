from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RuntimeRepository:
    def __init__(self, database: Any):
        self.database = database

    def acquire_resource_lease(self, resource_key: str, owner: str, lease_seconds: int = 900) -> bool:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO resource_lease (resource_key, owner, lease_expires_at, updated_at)
                VALUES (%s, %s, NOW() + (%s * INTERVAL '1 second'), NOW())
                ON CONFLICT (resource_key) DO UPDATE SET
                    owner = EXCLUDED.owner,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    updated_at = NOW()
                WHERE resource_lease.lease_expires_at < NOW()
                   OR resource_lease.owner = EXCLUDED.owner
                RETURNING owner
                """,
                (resource_key, owner, max(30, int(lease_seconds))),
            ).fetchone()
            return bool(row and row["owner"] == owner)

    def release_resource_lease(self, resource_key: str, owner: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                "DELETE FROM resource_lease WHERE resource_key = %s AND owner = %s",
                (resource_key, owner),
            )

    def enqueue_task_step(
        self,
        task_run_id: int,
        content_item_id: int | None,
        stage: str,
        input_version: str | None = None,
        priority: int = 50,
        max_attempts: int = 3,
    ) -> int | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """INSERT INTO task_step (
                       task_run_id, content_item_id, stage, input_version,
                       status, priority, max_attempts, available_at, created_at, updated_at
                   )
                   VALUES (%s, %s, %s, %s, 'pending', %s, %s, NOW(), NOW(), NOW())
                   ON CONFLICT (content_item_id, stage, input_version)
                   DO UPDATE SET updated_at = task_step.updated_at
                   RETURNING id""",
                (task_run_id, content_item_id, stage, input_version, int(priority), int(max_attempts)),
            ).fetchone()
            return row["id"] if row else None

    def claim_next_task_step(
        self,
        stages: tuple[str, ...],
        worker_name: str,
        lease_seconds: int = 300,
    ) -> dict[str, Any] | None:
        lease_seconds = max(30, int(lease_seconds or 300))
        with self.database.connect() as conn:
            row = conn.execute(
                """WITH candidate AS (
                     SELECT id
                     FROM task_step
                     WHERE status IN ('pending', 'retry_wait')
                       AND available_at <= NOW()
                       AND stage = ANY(%s)
                     ORDER BY priority DESC, available_at, created_at, id
                     FOR UPDATE SKIP LOCKED
                     LIMIT 1
                   )
                   UPDATE task_step
                   SET status = 'running',
                       locked_by = %s,
                       locked_at = NOW(),
                       lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                       heartbeat_at = NOW(),
                       attempt = attempt + 1,
                       updated_at = NOW()
                   WHERE id = (SELECT id FROM candidate)
                   RETURNING *""",
                (list(stages), worker_name, lease_seconds),
            ).fetchone()
            return dict(row) if row else None

    def complete_task_step(self, step_id: int, output_ref: dict[str, Any] | None = None) -> None:
        output_json = json.dumps(output_ref or {}, ensure_ascii=False)
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE task_step
                   SET status = 'success',
                       output_ref = %s::jsonb,
                       finished_at = NOW(),
                       lease_expires_at = NULL,
                       updated_at = NOW()
                   WHERE id = %s""",
                (output_json, step_id),
            )

    def fail_task_step(self, step_id: int, error_message: str, retry_delay_seconds: int = 30) -> bool:
        with self.database.connect() as conn:
            old = conn.execute(
                "SELECT attempt, max_attempts FROM task_step WHERE id = %s", (step_id,)
            ).fetchone()
            retrying = bool(
                old and int(old["attempt"]) < int(old["max_attempts"])
            ) if old else False
            conn.execute(
                """UPDATE task_step
                   SET status = CASE WHEN %s THEN 'retry_wait' ELSE 'failed' END,
                       error_message = %s,
                       available_at = CASE WHEN %s THEN NOW() + (%s * INTERVAL '1 second') ELSE available_at END,
                       finished_at = CASE WHEN %s THEN NULL ELSE NOW() END,
                       lease_expires_at = NULL,
                       updated_at = NOW()
                   WHERE id = %s""",
                (retrying, error_message, retrying, max(1, int(retry_delay_seconds)), retrying, step_id),
            )
            return retrying

    def heartbeat_task_step(self, step_id: int, lease_seconds: int = 300) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE task_step
                   SET heartbeat_at = NOW(),
                       lease_expires_at = NOW() + (%s * INTERVAL '1 second'),
                       updated_at = NOW()
                   WHERE id = %s AND status = 'running'""",
                (max(30, int(lease_seconds)), step_id),
            )

    def get_task_step(self, step_id: int) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM task_step WHERE id = %s", (step_id,)
            ).fetchone()
            return dict(row) if row else None

    def list_task_steps(self, task_run_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_step WHERE task_run_id = %s ORDER BY priority DESC, created_at",
                (task_run_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def insert_state_transition(
        self,
        object_type: str,
        object_id: str,
        old_status: str | None,
        new_status: str,
        reason: str | None = None,
        actor: str | None = None,
    ) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """INSERT INTO state_transition
                   (object_type, object_id, old_status, new_status, reason, actor, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, NOW())""",
                (object_type, object_id, old_status, new_status, reason, actor),
            )

    def write_outbox_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        aggregate_type: str | None = None,
        aggregate_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> int | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """INSERT INTO outbox_event
                   (event_type, aggregate_type, aggregate_id, idempotency_key,
                    payload_json, status, available_at, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s::jsonb, 'pending', NOW(), NOW(), NOW())
                   RETURNING id""",
                (event_type, aggregate_type, aggregate_id, idempotency_key,
                 json.dumps(payload) if isinstance(payload, dict) else payload),
            ).fetchone()
            return row["id"] if row else None

    def claim_outbox_events(self, batch_size: int = 10, owner: str = "outbox_consumer") -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """UPDATE outbox_event SET status = 'running', locked_by = %s,
                   locked_at = NOW(), lease_expires_at = NOW() + INTERVAL '5 minutes',
                   attempt = attempt + 1, updated_at = NOW()
                   WHERE id IN (
                       SELECT id FROM outbox_event
                       WHERE status = 'pending'
                          OR (status = 'running' AND lease_expires_at < NOW())
                       ORDER BY available_at, id
                       FOR UPDATE SKIP LOCKED
                       LIMIT %s
                   )
                   RETURNING *""",
                (owner, batch_size),
            ).fetchall()
            return [dict(row) for row in rows]

    def complete_outbox_event(self, event_id: int) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE outbox_event SET status = 'success', processed_at = NOW(),
                   updated_at = NOW() WHERE id = %s""",
                (event_id,),
            )

    def fail_outbox_event(self, event_id: int, error: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE outbox_event SET status = 'failed', last_error = %s,
                   updated_at = NOW() WHERE id = %s""",
                (error, event_id),
            )

    def register_artifact(
        self,
        content_item_id: int | None,
        task_run_id: int | None,
        kind: str,
        path: str,
        size_bytes: int | None = None,
        sha256: str | None = None,
    ) -> int | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """INSERT INTO artifact (content_item_id, task_run_id, kind, path,
                       size_bytes, sha256, status, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, 'active', NOW(), NOW())
                   ON CONFLICT (kind, path) DO UPDATE SET
                       content_item_id = COALESCE(EXCLUDED.content_item_id, artifact.content_item_id),
                       size_bytes = EXCLUDED.size_bytes,
                       sha256 = EXCLUDED.sha256,
                       updated_at = NOW()
                   RETURNING id""",
                (content_item_id, task_run_id, kind, path, size_bytes, sha256),
            ).fetchone()
            return row["id"] if row else None

    def list_artifacts(self, kind: str | None = None, status: str = "active") -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            where = ["status = %s"]
            params: list[Any] = [status]
            if kind:
                where.append("kind = %s")
                params.append(kind)
            rows = conn.execute(
                f"SELECT * FROM artifact WHERE {' AND '.join(where)} ORDER BY created_at DESC",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def deactivate_artifact(self, artifact_id: int) -> None:
        with self.database.connect() as conn:
            conn.execute(
                "UPDATE artifact SET status = 'deleted', updated_at = NOW() WHERE id = %s",
                (artifact_id,),
            )

    def cleanup_artifacts(self) -> dict[str, int]:
        cleaned = 0
        errors = 0
        artifacts = self.list_artifacts(status="deleted")
        for art in artifacts:
            path_str = str(art.get("path") or "")
            if not path_str:
                continue
            p = Path(path_str)
            if p.exists():
                try:
                    p.unlink()
                    cleaned += 1
                except OSError:
                    errors += 1
        return {"cleaned": cleaned, "errors": errors, "total": len(artifacts)}
