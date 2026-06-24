"""Add company research tables.

Revision ID: 0003_company_research
Revises: 0002_add_task_step
Create Date: 2026-06-20
"""
from __future__ import annotations

from alembic import op

revision = "0003_company_research"
down_revision = "0002_add_task_step"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS company_research_batches (
            id               SERIAL PRIMARY KEY,
            batch_id         VARCHAR(96) UNIQUE NOT NULL,
            begin_date       DATE NOT NULL,
            end_date         DATE NOT NULL,
            max_stocks       INT,
            stock_scope      TEXT,
            notice_type      TEXT,
            execution_mode   TEXT,
            total_stocks     INT,
            completed_stocks INT DEFAULT 0,
            failed_stocks    INT DEFAULT 0,
            status           VARCHAR(64),
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            updated_at       TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS company_research_jobs (
            id                   SERIAL PRIMARY KEY,
            batch_id             VARCHAR(96),
            symbol               TEXT NOT NULL,
            stock_name           TEXT,
            begin_date           DATE NOT NULL,
            end_date             DATE NOT NULL,
            notice_type          TEXT DEFAULT '全部',
            execution_mode       TEXT,
            max_stocks           INT,
            auto_delete_notebook BOOLEAN DEFAULT TRUE,
            status               VARCHAR(64),
            current_stage        TEXT,
            progress_percent     REAL DEFAULT 0,
            notice_total         INT DEFAULT 0,
            pdf_downloaded       INT DEFAULT 0,
            pdf_failed           INT DEFAULT 0,
            source_uploaded      INT DEFAULT 0,
            source_ready         INT DEFAULT 0,
            question_answered    INT DEFAULT 0,
            question_saved       INT DEFAULT 0,
            notebook_id          TEXT,
            notebook_deleted     BOOLEAN DEFAULT FALSE,
            notebook_deleted_at  TIMESTAMPTZ,
            retry_count          INT DEFAULT 0,
            last_error           TEXT,
            started_at           TIMESTAMPTZ,
            finished_at          TIMESTAMPTZ,
            created_at           TIMESTAMPTZ DEFAULT NOW(),
            updated_at           TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS company_notice_files (
            id              SERIAL PRIMARY KEY,
            symbol          TEXT NOT NULL,
            stock_name      TEXT,
            notice_id       TEXT NOT NULL,
            notice_title    TEXT,
            notice_date     DATE,
            notice_url      TEXT,
            source_provider TEXT,
            download_url    TEXT,
            file_path       TEXT NOT NULL DEFAULT '',
            file_name       TEXT,
            file_size       BIGINT,
            file_hash       TEXT,
            is_valid_pdf    BOOLEAN DEFAULT FALSE,
            download_status TEXT,
            provider_attempts_json JSONB DEFAULT '{}'::jsonb,
            final_provider  TEXT,
            upload_status   TEXT,
            source_id       TEXT,
            source_title    TEXT,
            local_file_deleted BOOLEAN DEFAULT FALSE,
            local_file_deleted_at TIMESTAMPTZ,
            delete_local_error TEXT,
            error_message   TEXT,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(symbol, notice_id)
        );

        CREATE TABLE IF NOT EXISTS company_notebooks (
            id                 SERIAL PRIMARY KEY,
            symbol             TEXT NOT NULL,
            stock_name         TEXT,
            notebook_id        TEXT UNIQUE,
            notebook_title     TEXT,
            notebook_status    TEXT,
            created_at         TIMESTAMPTZ DEFAULT NOW(),
            deleted_at         TIMESTAMPTZ,
            delete_status      TEXT,
            delete_error       TEXT,
            source_count       INT DEFAULT 0,
            ready_source_count INT DEFAULT 0,
            updated_at         TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS company_research_answers (
            id              SERIAL PRIMARY KEY,
            symbol          TEXT NOT NULL,
            stock_name      TEXT,
            question_index  INT NOT NULL,
            question_key    TEXT NOT NULL,
            question_title  TEXT NOT NULL,
            prompt_text     TEXT NOT NULL,
            answer_markdown TEXT,
            raw_answer      TEXT,
            references_json JSONB DEFAULT '[]'::jsonb,
            conversation_id TEXT,
            source_ids      JSONB DEFAULT '[]'::jsonb,
            notebook_id     TEXT,
            status          TEXT,
            error_message   TEXT,
            generated_at    TIMESTAMPTZ,
            saved_at        TIMESTAMPTZ,
            created_at      TIMESTAMPTZ DEFAULT NOW(),
            updated_at      TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(symbol, question_key)
        );

        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS upload_status TEXT;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS source_id TEXT;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS source_title TEXT;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS provider_attempts_json JSONB DEFAULT '{}'::jsonb;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS final_provider TEXT;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS local_file_deleted BOOLEAN DEFAULT FALSE;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS local_file_deleted_at TIMESTAMPTZ;
        ALTER TABLE company_notice_files ADD COLUMN IF NOT EXISTS delete_local_error TEXT;

        CREATE INDEX IF NOT EXISTS idx_company_research_batches_status ON company_research_batches(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_company_research_jobs_batch ON company_research_jobs(batch_id, id);
        CREATE INDEX IF NOT EXISTS idx_company_research_jobs_symbol ON company_research_jobs(symbol, id DESC);
        CREATE INDEX IF NOT EXISTS idx_company_notice_files_symbol ON company_notice_files(symbol, notice_date DESC);
        CREATE INDEX IF NOT EXISTS idx_company_notice_files_cleanup ON company_notice_files(local_file_deleted, upload_status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_company_notebooks_cleanup ON company_notebooks(delete_status, updated_at);
        CREATE INDEX IF NOT EXISTS idx_company_research_answers_symbol ON company_research_answers(symbol, question_index);
        """
    )


def downgrade() -> None:
    raise RuntimeError("KenRadar company research migration 不支持自动降级；请通过数据库备份恢复")
