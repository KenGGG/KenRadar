"""Research job repository: scan-confirm-execute workflow (V2 M6).

Extends the legacy research_job table with:
- scope-based historical scanning (recent vs full)
- discovered-but-unexecuted items reviewable before execution
- confirm/execute status tracking
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class ResearchJobRepository:
    def __init__(self, database: Any):
        self.database = database

    # ── job lifecycle ──────────────────────────────────────────────────

    def create_scan_job(
        self,
        *,
        platform: str,
        source_subscription_id: int | None,
        scan_scope: str,
        history_capability: str,
        external_content_id: str | None = None,
        creator_name: str = "",
        requested_by: str = "",
    ) -> dict[str, Any]:
        """Create a scan job (no execution yet) for review."""
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO research_job (
                    platform, creator_name, status, scan_scope, history_capability,
                    source_subscription_id, external_content_id,
                    confirm_status, total_count, pending_count,
                    created_at, updated_at
                )
                VALUES (
                    %s, %s, 'pending', %s, %s, %s, %s, 'pending', 0, 0, NOW(), NOW()
                )
                RETURNING id
                """,
                (
                    str(platform),
                    str(creator_name or ""),
                    str(scan_scope or "recent"),
                    str(history_capability or "unknown"),
                    int(source_subscription_id) if source_subscription_id else None,
                    str(external_content_id) if external_content_id else None,
                ),
            ).fetchone()
            job_id = row["id"]
        return self.get_job(job_id)

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT id, platform, creator_name, status, scan_scope, history_capability,
                       source_subscription_id, external_content_id, discovered_count,
                       confirmed_count, confirm_status, confirmed_by, confirmed_at,
                       total_count, pending_count, success_count, failed_count,
                       skipped_count, created_at, updated_at
                FROM research_job WHERE id = %s
                """,
                (job_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_jobs(self, *, confirm_status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            SELECT id, platform, creator_name, status, scan_scope, history_capability,
                   external_content_id, discovered_count, confirmed_count,
                   confirm_status, created_at
            FROM research_job
        """
        params: list[Any] = []
        if confirm_status:
            query += " WHERE confirm_status = %s"
            params.append(str(confirm_status))
        query += " ORDER BY id DESC LIMIT %s"
        params.append(int(limit))
        with self.database.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # ── discovered items ───────────────────────────────────────────────

    def add_discovered_item(
        self,
        *,
        job_id: int,
        external_content_id: str,
        title: str,
        url: str,
        published_at: datetime | None,
    ) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_job_item (
                    job_id, aweme_id, external_content_id, title, url, published_at,
                    status, review_status, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', 'pending', NOW(), NOW())
                ON CONFLICT(job_id, aweme_id) DO UPDATE SET
                    external_content_id = EXCLUDED.external_content_id,
                    title = EXCLUDED.title,
                    url = EXCLUDED.url,
                    published_at = EXCLUDED.published_at
                """,
                (
                    int(job_id),
                    str(external_content_id),
                    str(external_content_id),
                    str(title or ""),
                    str(url or ""),
                    published_at,
                ),
            )
            conn.execute(
                """
                UPDATE research_job
                SET discovered_count = (
                        SELECT COUNT(*) FROM research_job_item
                        WHERE job_id = %s
                    ),
                    total_count = (SELECT COUNT(*) FROM research_job_item WHERE job_id = %s),
                    pending_count = (SELECT COUNT(*) FROM research_job_item WHERE job_id = %s),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (int(job_id), int(job_id), int(job_id), int(job_id)),
            )

    def list_discovered_items(self, job_id: int) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, job_id, external_content_id, title, url, published_at,
                       review_status, status
                FROM research_job_item
                WHERE job_id = %s
                ORDER BY published_at DESC NULLS LAST, id DESC
                """,
                (int(job_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_item_review(self, job_id: int, external_content_id: str, review_status: str) -> None:
        if review_status not in ("approved", "rejected"):
            raise ValueError(f"无效的 review_status: {review_status}")
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE research_job_item
                SET review_status = %s, updated_at = NOW()
                WHERE job_id = %s AND external_content_id = %s
                """,
                (str(review_status), int(job_id), str(external_content_id)),
            )

    # ── confirm / execute ──────────────────────────────────────────────

    def confirm_job(self, job_id: int, *, confirmed_by: str, approve: bool) -> None:
        with self.database.connect() as conn:
            if approve:
                conn.execute(
                    """
                    UPDATE research_job
                    SET confirm_status = 'confirmed',
                        confirmed_by = %s,
                        confirmed_at = NOW(),
                        confirmed_count = (
                            SELECT COUNT(*) FROM research_job_item
                            WHERE job_id = %s AND review_status = 'approved'
                        ),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (str(confirmed_by), int(job_id), int(job_id)),
                )
            else:
                conn.execute(
                    """
                    UPDATE research_job
                    SET confirm_status = 'rejected',
                        confirmed_by = %s,
                        confirmed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (str(confirmed_by), int(job_id)),
                )

    def mark_executed(self, job_id: int) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE research_job
                SET confirm_status = 'executed', status = 'running', updated_at = NOW()
                WHERE id = %s
                """,
                (int(job_id),),
            )

    def approved_items(self, job_id: int) -> list[dict[str, Any]]:
        """Return approved items ready for execution."""
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT external_content_id, title, url
                FROM research_job_item
                WHERE job_id = %s AND review_status = 'approved'
                ORDER BY published_at DESC NULLS LAST, id DESC
                """,
                (int(job_id),),
            ).fetchall()
        return [dict(r) for r in rows]

    def claim_next_approved_item(self, job_id: int) -> dict[str, Any] | None:
        """Claim one approved item so historical processing yields after each item."""
        with self.database.connect() as conn:
            row = conn.execute(
                """
                WITH candidate AS (
                    SELECT id FROM research_job_item
                    WHERE job_id = %s AND review_status = 'approved' AND status = 'pending'
                    ORDER BY published_at DESC NULLS LAST, id DESC
                    FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE research_job_item
                SET status = 'running', updated_at = NOW()
                WHERE id = (SELECT id FROM candidate)
                RETURNING id, external_content_id, title, url
                """,
                (int(job_id),),
            ).fetchone()
        return dict(row) if row else None

    def finish_backfill_item(self, job_id: int, item_id: int, *, success: bool, error: str = "") -> dict[str, int]:
        status = "success" if success else "failed"
        with self.database.connect() as conn:
            conn.execute(
                """UPDATE research_job_item SET status = %s, error_message = %s, updated_at = NOW()
                   WHERE id = %s AND job_id = %s""",
                (status, str(error or "") or None, int(item_id), int(job_id)),
            )
            counts = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE review_status = 'approved' AND status IN ('pending', 'queued', 'running')) AS pending,
                       COUNT(*) FILTER (WHERE status = 'success') AS success,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COUNT(*) FILTER (WHERE review_status = 'rejected' OR status = 'skipped') AS skipped
                FROM research_job_item WHERE job_id = %s
                """,
                (int(job_id),),
            ).fetchone()
            result = {key: int(counts[key] or 0) for key in ("total", "pending", "success", "failed", "skipped")}
            job_status = "running" if result["pending"] else ("partial_failed" if result["failed"] else "completed")
            conn.execute(
                """UPDATE research_job SET total_count=%s, pending_count=%s, success_count=%s,
                   failed_count=%s, skipped_count=%s, status=%s, updated_at=NOW(),
                   finished_at=CASE WHEN %s THEN NOW() ELSE finished_at END WHERE id=%s""",
                (result["total"], result["pending"], result["success"], result["failed"], result["skipped"], job_status, not result["pending"], int(job_id)),
            )
        return result

    def finish_backfill_if_idle(self, job_id: int) -> dict[str, int]:
        """Close a confirmed batch that has no approved item left to claim."""
        with self.database.connect() as conn:
            counts = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE review_status = 'approved' AND status IN ('pending', 'queued', 'running')) AS pending,
                       COUNT(*) FILTER (WHERE status = 'success') AS success,
                       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                       COUNT(*) FILTER (WHERE review_status = 'rejected' OR status = 'skipped') AS skipped
                FROM research_job_item WHERE job_id = %s
                """,
                (int(job_id),),
            ).fetchone()
            result = {key: int(counts[key] or 0) for key in ("total", "pending", "success", "failed", "skipped")}
            status = "partial_failed" if result["failed"] else "completed"
            conn.execute(
                """UPDATE research_job SET total_count=%s, pending_count=%s, success_count=%s,
                   failed_count=%s, skipped_count=%s, status=%s, finished_at=NOW(), updated_at=NOW()
                   WHERE id=%s""",
                (result["total"], result["pending"], result["success"], result["failed"], result["skipped"], status, int(job_id)),
            )
        return result
