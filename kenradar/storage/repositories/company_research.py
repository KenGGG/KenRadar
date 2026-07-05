from __future__ import annotations

import json
from typing import Any


class CompanyResearchRepository:
    def __init__(self, database: Any):
        self.database = database

    def create_company_research_batch(
        self,
        *,
        batch_id: str,
        begin_date: str,
        end_date: str,
        max_stocks: int,
        stock_scope: str,
        notice_type: str,
        execution_mode: str,
        total_stocks: int,
        status: str = "queued",
    ) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO company_research_batches (
                    batch_id, begin_date, end_date, max_stocks, stock_scope,
                    notice_type, execution_mode, total_stocks, status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                RETURNING *
                """,
                (batch_id, begin_date, end_date, max_stocks, stock_scope, notice_type, execution_mode, total_stocks, status),
            ).fetchone()
            return dict(row)

    def update_company_research_batch(self, batch_id: str, **fields: Any) -> None:
        allowed = {"status", "completed_stocks", "failed_stocks"}
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            assignments.append(f"{key} = %s")
            params.append(value)
        if not assignments:
            return
        assignments.append("updated_at = NOW()")
        params.append(batch_id)
        with self.database.connect() as conn:
            conn.execute(f"UPDATE company_research_batches SET {', '.join(assignments)} WHERE batch_id = %s", params)

    def get_company_research_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM company_research_batches WHERE batch_id = %s", (batch_id,)).fetchone()
            return dict(row) if row else None

    def list_company_research_batches(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM company_research_batches ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_company_research_job(
        self,
        *,
        batch_id: str,
        symbol: str,
        stock_name: str,
        begin_date: str,
        end_date: str,
        notice_type: str,
        execution_mode: str,
        max_stocks: int,
        auto_delete_notebook: bool = True,
    ) -> dict[str, Any]:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO company_research_jobs (
                    batch_id, symbol, stock_name, begin_date, end_date, notice_type,
                    execution_mode, max_stocks, auto_delete_notebook, status,
                    current_stage, progress_percent, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', 'created', 0, NOW(), NOW())
                RETURNING *
                """,
                (batch_id, symbol, stock_name, begin_date, end_date, notice_type, execution_mode, max_stocks, auto_delete_notebook),
            ).fetchone()
            return dict(row)

    def update_company_research_job(self, job_id: int, **fields: Any) -> None:
        allowed = {
            "stock_name",
            "status",
            "current_stage",
            "progress_percent",
            "notice_total",
            "pdf_downloaded",
            "pdf_failed",
            "source_uploaded",
            "source_ready",
            "question_answered",
            "question_saved",
            "notebook_id",
            "notebook_deleted",
            "notebook_deleted_at",
            "retry_count",
            "last_error",
            "started_at",
            "finished_at",
        }
        assignments: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "started_at":
                assignments.append("started_at = COALESCE(started_at, %s)")
            else:
                assignments.append(f"{key} = %s")
            params.append(value)
        if not assignments:
            return
        assignments.append("updated_at = NOW()")
        params.append(job_id)
        with self.database.connect() as conn:
            conn.execute(f"UPDATE company_research_jobs SET {', '.join(assignments)} WHERE id = %s", params)

    def get_company_research_job(self, job_id: int) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM company_research_jobs WHERE id = %s", (job_id,)).fetchone()
            return dict(row) if row else None

    def list_company_research_jobs(
        self,
        *,
        batch_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if batch_id:
            clauses.append("batch_id = %s")
            params.append(batch_id)
        if symbol:
            clauses.append("symbol = %s")
            params.append(symbol)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM company_research_jobs
                {where}
                ORDER BY id DESC
                LIMIT %s
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def resolve_company_research_symbol(self, query: str) -> str | None:
        needle = str(query or "").strip()
        if not needle:
            return None
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT symbol
                FROM company_research_jobs
                WHERE symbol ILIKE %s OR stock_name ILIKE %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (needle, f"%{needle}%"),
            ).fetchone()
            return str(row["symbol"]) if row else None

    def upsert_company_notice_file(self, **fields: Any) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO company_notice_files (
                    symbol, stock_name, notice_id, notice_title, notice_date, notice_url,
                    source_provider, download_url, file_path, file_name, file_size,
                    file_hash, is_valid_pdf, download_status, provider_attempts_json, final_provider, upload_status, source_id,
                    source_title, local_file_deleted, local_file_deleted_at, delete_local_error,
                    error_message, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, NULLIF(%s, '')::date, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s::jsonb, %s, %s, %s,
                    %s, %s, NULLIF(%s, '')::timestamptz, %s,
                    %s, NOW(), NOW()
                )
                ON CONFLICT(symbol, notice_id) DO UPDATE SET
                    stock_name = EXCLUDED.stock_name,
                    notice_title = EXCLUDED.notice_title,
                    notice_date = EXCLUDED.notice_date,
                    notice_url = EXCLUDED.notice_url,
                    source_provider = EXCLUDED.source_provider,
                    download_url = EXCLUDED.download_url,
                    file_path = EXCLUDED.file_path,
                    file_name = EXCLUDED.file_name,
                    file_size = EXCLUDED.file_size,
                    file_hash = EXCLUDED.file_hash,
                    is_valid_pdf = EXCLUDED.is_valid_pdf,
                    download_status = EXCLUDED.download_status,
                    provider_attempts_json = EXCLUDED.provider_attempts_json,
                    final_provider = EXCLUDED.final_provider,
                    upload_status = COALESCE(EXCLUDED.upload_status, company_notice_files.upload_status),
                    source_id = COALESCE(EXCLUDED.source_id, company_notice_files.source_id),
                    source_title = COALESCE(EXCLUDED.source_title, company_notice_files.source_title),
                    local_file_deleted = EXCLUDED.local_file_deleted,
                    local_file_deleted_at = COALESCE(EXCLUDED.local_file_deleted_at, company_notice_files.local_file_deleted_at),
                    delete_local_error = EXCLUDED.delete_local_error,
                    error_message = EXCLUDED.error_message,
                    updated_at = NOW()
                """,
                (
                    fields.get("symbol"),
                    fields.get("stock_name"),
                    fields.get("notice_id"),
                    fields.get("notice_title"),
                    str(fields.get("notice_date") or "")[:10],
                    fields.get("notice_url"),
                    fields.get("source_provider"),
                    fields.get("download_url"),
                    fields.get("file_path"),
                    fields.get("file_name"),
                    int(fields.get("file_size") or 0),
                    fields.get("file_hash"),
                    bool(fields.get("is_valid_pdf")),
                    fields.get("download_status"),
                    json.dumps(fields.get("provider_attempts_json") or {}, ensure_ascii=False),
                    fields.get("final_provider"),
                    fields.get("upload_status"),
                    fields.get("source_id"),
                    fields.get("source_title"),
                    bool(fields.get("local_file_deleted", False)),
                    fields.get("local_file_deleted_at") or "",
                    fields.get("delete_local_error"),
                    fields.get("error_message"),
                ),
            )

    def list_company_notice_files(self, symbol: str, limit: int = 500) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM company_notice_files
                WHERE symbol = %s
                ORDER BY notice_date DESC NULLS LAST, id DESC
                LIMIT %s
                """,
                (symbol, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_company_notice_file_upload(
        self,
        symbol: str,
        notice_id: str,
        *,
        upload_status: str,
        source_id: str = "",
        source_title: str = "",
        error_message: str | None = None,
    ) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE company_notice_files
                SET upload_status = %s,
                    source_id = NULLIF(%s, ''),
                    source_title = NULLIF(%s, ''),
                    error_message = COALESCE(%s, error_message),
                    updated_at = NOW()
                WHERE symbol = %s AND notice_id = %s
                """,
                (upload_status, source_id, source_title, error_message, symbol, notice_id),
            )

    def mark_company_notice_file_local_deleted(
        self,
        symbol: str,
        notice_id: str,
        *,
        deleted: bool,
        delete_error: str | None = None,
    ) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE company_notice_files
                SET local_file_deleted = %s,
                    local_file_deleted_at = CASE WHEN %s THEN NOW() ELSE local_file_deleted_at END,
                    delete_local_error = %s,
                    updated_at = NOW()
                WHERE symbol = %s AND notice_id = %s
                """,
                (deleted, deleted, delete_error, symbol, notice_id),
            )

    def list_company_notice_files_pending_cleanup(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM company_notice_files
                WHERE upload_status IN ('uploaded', 'ready')
                  AND COALESCE(local_file_deleted, FALSE) = FALSE
                  AND COALESCE(file_path, '') <> ''
                ORDER BY updated_at
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def upsert_company_notebook(self, symbol: str, stock_name: str, notebook_id: str, notebook_title: str, notebook_status: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO company_notebooks (
                    symbol, stock_name, notebook_id, notebook_title, notebook_status,
                    delete_status, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, 'active', NOW(), NOW())
                ON CONFLICT(notebook_id) DO UPDATE SET
                    stock_name = EXCLUDED.stock_name,
                    notebook_title = EXCLUDED.notebook_title,
                    notebook_status = EXCLUDED.notebook_status,
                    updated_at = NOW()
                """,
                (symbol, stock_name, notebook_id, notebook_title, notebook_status),
            )

    def update_company_notebook_counts(self, notebook_id: str, *, source_count: int, ready_source_count: int) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE company_notebooks
                SET source_count = %s, ready_source_count = %s, updated_at = NOW()
                WHERE notebook_id = %s
                """,
                (source_count, ready_source_count, notebook_id),
            )

    def mark_company_notebook_deleted(self, notebook_id: str, delete_status: str = "deleted") -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE company_notebooks
                SET notebook_status = 'deleted',
                    delete_status = %s,
                    deleted_at = NOW(),
                    delete_error = NULL,
                    updated_at = NOW()
                WHERE notebook_id = %s
                """,
                (delete_status, notebook_id),
            )

    def mark_company_notebook_delete_failed(self, notebook_id: str, error: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE company_notebooks
                SET delete_status = 'delete_failed',
                    delete_error = %s,
                    updated_at = NOW()
                WHERE notebook_id = %s
                """,
                (error, notebook_id),
            )

    def list_company_notebooks_pending_cleanup(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM company_notebooks
                WHERE delete_status IN ('delete_failed', 'active')
                  AND notebook_id IN (
                      SELECT notebook_id
                      FROM company_research_answers
                      WHERE status = 'saved'
                      GROUP BY notebook_id
                      HAVING COUNT(DISTINCT question_key) >= 10
                  )
                ORDER BY updated_at
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_company_jobs_notebook_deleted(self, notebook_id: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                UPDATE company_research_jobs
                SET notebook_deleted = TRUE,
                    notebook_deleted_at = NOW(),
                    status = CASE WHEN status = 'completed_with_delete_pending' THEN 'completed' ELSE status END,
                    updated_at = NOW()
                WHERE notebook_id = %s
                """,
                (notebook_id,),
            )

    def upsert_company_research_answer(self, **fields: Any) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO company_research_answers (
                    symbol, stock_name, question_index, question_key, question_title,
                    prompt_text, answer_markdown, raw_answer, references_json,
                    conversation_id, source_ids, notebook_id, status, error_message,
                    generated_at, saved_at, created_at, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s::jsonb,
                    %s, %s::jsonb, %s, %s, %s,
                    NULLIF(%s, '')::timestamptz, NULLIF(%s, '')::timestamptz, NOW(), NOW()
                )
                ON CONFLICT(symbol, question_key) DO UPDATE SET
                    stock_name = EXCLUDED.stock_name,
                    question_index = EXCLUDED.question_index,
                    question_title = EXCLUDED.question_title,
                    prompt_text = EXCLUDED.prompt_text,
                    answer_markdown = COALESCE(EXCLUDED.answer_markdown, company_research_answers.answer_markdown),
                    raw_answer = COALESCE(EXCLUDED.raw_answer, company_research_answers.raw_answer),
                    references_json = COALESCE(EXCLUDED.references_json, company_research_answers.references_json),
                    conversation_id = COALESCE(EXCLUDED.conversation_id, company_research_answers.conversation_id),
                    source_ids = COALESCE(EXCLUDED.source_ids, company_research_answers.source_ids),
                    notebook_id = COALESCE(EXCLUDED.notebook_id, company_research_answers.notebook_id),
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message,
                    generated_at = COALESCE(EXCLUDED.generated_at, company_research_answers.generated_at),
                    saved_at = COALESCE(EXCLUDED.saved_at, company_research_answers.saved_at),
                    updated_at = NOW()
                """,
                (
                    fields.get("symbol"),
                    fields.get("stock_name"),
                    int(fields.get("question_index") or 0),
                    fields.get("question_key"),
                    fields.get("question_title"),
                    fields.get("prompt_text"),
                    fields.get("answer_markdown"),
                    fields.get("raw_answer"),
                    fields.get("references_json") or "[]",
                    fields.get("conversation_id"),
                    json.dumps(fields.get("source_ids") or [], ensure_ascii=False),
                    fields.get("notebook_id"),
                    fields.get("status"),
                    fields.get("error_message"),
                    fields.get("generated_at") or "",
                    fields.get("saved_at") or "",
                ),
            )

    def get_company_research_answer(self, symbol: str, question_key: str) -> dict[str, Any] | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT * FROM company_research_answers WHERE symbol = %s AND question_key = %s",
                (symbol, question_key),
            ).fetchone()
            return dict(row) if row else None

    def list_company_research_answers(self, symbol: str) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM company_research_answers
                WHERE symbol = %s
                ORDER BY question_index
                """,
                (symbol,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_company_notebooks(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT n.*,
                       j.question_answered, j.question_saved,
                       j.status AS job_status
                FROM company_notebooks n
                LEFT JOIN LATERAL (
                    SELECT question_answered, question_saved, status
                    FROM company_research_jobs
                    WHERE notebook_id = n.notebook_id
                    ORDER BY updated_at DESC
                    LIMIT 1
                ) j ON TRUE
                ORDER BY n.updated_at DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            ).fetchall()
            return [dict(row) for row in rows]

    def can_delete_company_notebook(self, symbol: str) -> bool:
        rows = self.list_company_research_answers(symbol)
        if len(rows) != 10:
            return False
        for row in rows:
            if row.get("status") != "saved":
                return False
            if not row.get("answer_markdown") and not row.get("raw_answer"):
                return False
        return True


