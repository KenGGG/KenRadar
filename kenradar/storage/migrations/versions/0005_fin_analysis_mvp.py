"""Add financial analysis MVP tables.

Revision ID: 0005_fin_analysis_mvp
Revises: 0004_company_notice_attempts
Create Date: 2026-06-22
"""
from __future__ import annotations

import logging

from alembic import op

revision = "0005_fin_analysis_mvp"
down_revision = "0004_company_notice_attempts"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    conn = op.get_bind()

    # ── Table 1: company_financial_analysis_jobs ──
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS company_financial_analysis_jobs (
            id                  SERIAL PRIMARY KEY,
            symbol              TEXT NOT NULL,
            stock_name          TEXT,
            analysis_base_year  INTEGER NOT NULL DEFAULT 2026,
            status              TEXT DEFAULT 'created',
            current_stage       TEXT DEFAULT 'created',
            selected_pdf_count     INTEGER DEFAULT 0,
            uploaded_source_count  INTEGER DEFAULT 0,
            ready_source_count     INTEGER DEFAULT 0,
            question_answered      INTEGER DEFAULT 0,
            question_saved         INTEGER DEFAULT 0,
            financial_risk_score   INTEGER,
            financial_risk_tier    TEXT,
            score_source           TEXT,
            missing_report_files   TEXT,
            notebook_id     TEXT,
            notebook_deleted BOOLEAN DEFAULT FALSE,
            auto_delete_notebook BOOLEAN DEFAULT TRUE,
            delete_local_pdfs_after_ready BOOLEAN DEFAULT FALSE,
            retry_count     INTEGER DEFAULT 0,
            last_error      TEXT,
            started_at      TIMESTAMP,
            finished_at     TIMESTAMP,
            created_at      TIMESTAMP DEFAULT NOW(),
            updated_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_jobs_symbol ON company_financial_analysis_jobs(symbol)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_jobs_status ON company_financial_analysis_jobs(status)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_jobs_created ON company_financial_analysis_jobs(created_at DESC)")

    # ── Table 2: company_financial_report_files ──
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS company_financial_report_files (
            id              SERIAL PRIMARY KEY,
            job_id          INTEGER REFERENCES company_financial_analysis_jobs(id),
            symbol          TEXT NOT NULL,
            report_year     INTEGER,
            report_period   TEXT,
            report_period_end DATE,
            report_type     TEXT,
            notice_title    TEXT,
            notice_date     DATE,
            pdf_status      TEXT,
            file_path       TEXT,
            file_size       INTEGER,
            file_hash       TEXT,
            final_provider  TEXT,
            download_error  TEXT,
            upload_status   TEXT,
            upload_error    TEXT,
            source_id       TEXT,
            source_title    TEXT,
            local_file_deleted BOOLEAN DEFAULT FALSE,
            local_file_deleted_at TIMESTAMP,
            created_at      TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_files_job ON company_financial_report_files(job_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_files_symbol ON company_financial_report_files(symbol)")
    conn.exec_driver_sql("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_files_job_notice
        ON company_financial_report_files(job_id, notice_title)
    """)

    # ── Table 3: company_financial_question_answers ──
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS company_financial_question_answers (
            id              SERIAL PRIMARY KEY,
            job_id          INTEGER REFERENCES company_financial_analysis_jobs(id),
            symbol          TEXT NOT NULL,
            question_index  INTEGER NOT NULL,
            question_key    TEXT NOT NULL,
            question_title  TEXT NOT NULL,
            prompt_text     TEXT NOT NULL,
            answer_markdown TEXT,
            raw_answer      TEXT,
            status          TEXT DEFAULT 'pending',
            error_message   TEXT,
            conversation_id TEXT,
            created_at      TIMESTAMP DEFAULT NOW(),
            saved_at        TIMESTAMP
        )
    """)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_qa_job ON company_financial_question_answers(job_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_qa_symbol ON company_financial_question_answers(symbol)")
    conn.exec_driver_sql("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_qa_job_question
        ON company_financial_question_answers(job_id, question_key)
    """)

    # ── Table 4: company_financial_analysis_reports ──
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS company_financial_analysis_reports (
            id                      SERIAL PRIMARY KEY,
            job_id                  INTEGER REFERENCES company_financial_analysis_jobs(id),
            symbol                  TEXT NOT NULL,
            report_markdown         TEXT,
            parsed_json             JSONB,
            raw_answer              TEXT,
            parse_success           BOOLEAN,
            financial_risk_score    INTEGER,
            financial_risk_tier     TEXT,
            score_source            TEXT,
            first_repayment_source  TEXT,
            leasing_advice          TEXT,
            status                  TEXT DEFAULT 'pending',
            created_at              TIMESTAMP DEFAULT NOW(),
            saved_at                TIMESTAMP
        )
    """)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_report_job ON company_financial_analysis_reports(job_id)")
    conn.exec_driver_sql("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fin_report_symbol
        ON company_financial_analysis_reports(symbol)
    """)

    # ── Table 5: company_financial_red_flags ──
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS company_financial_red_flags (
            id                      SERIAL PRIMARY KEY,
            job_id                  INTEGER REFERENCES company_financial_analysis_jobs(id),
            symbol                  TEXT NOT NULL,
            flag_type               TEXT,
            flag_name               TEXT,
            risk_level              TEXT,
            evidence                TEXT,
            annual_report_explanation TEXT,
            explanation_sufficient  BOOLEAN,
            leasing_due_diligence_impact TEXT,
            required_follow_up_materials TEXT,
            created_at              TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_flags_job ON company_financial_red_flags(job_id)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_flags_symbol ON company_financial_red_flags(symbol)")
    conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS idx_fin_flags_level ON company_financial_red_flags(risk_level)")

    logger.info("Migration 0005 complete: 5 financial analysis tables created")


def downgrade() -> None:
    conn = op.get_bind()
    conn.exec_driver_sql("DROP TABLE IF EXISTS company_financial_red_flags CASCADE")
    conn.exec_driver_sql("DROP TABLE IF EXISTS company_financial_analysis_reports CASCADE")
    conn.exec_driver_sql("DROP TABLE IF EXISTS company_financial_question_answers CASCADE")
    conn.exec_driver_sql("DROP TABLE IF EXISTS company_financial_report_files CASCADE")
    conn.exec_driver_sql("DROP TABLE IF EXISTS company_financial_analysis_jobs CASCADE")
    logger.info("Migration 0005 downgrade: 5 tables dropped")
