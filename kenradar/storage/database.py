from __future__ import annotations

import warnings

warnings.warn(
    "kenradar.storage.database is deprecated. Please use PostgreSQL via database_url in config.yaml.",
    DeprecationWarning,
    stacklevel=2,
)

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS blogger (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    sec_uid         TEXT    NOT NULL UNIQUE,
                    nickname        TEXT,
                    douyin_url      TEXT,
                    avatar_url      TEXT,
                    enabled         INTEGER DEFAULT 1,
                    check_modes     TEXT    DEFAULT 'post',
                    last_check_at   TEXT,
                    last_aweme_id   TEXT,
                    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    updated_at      TEXT    DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS aweme (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    aweme_id        TEXT    NOT NULL UNIQUE,
                    blogger_id      INTEGER NOT NULL,
                    title           TEXT,
                    aweme_type      INTEGER,
                    create_time     INTEGER,
                    duration        INTEGER,
                    video_url       TEXT,
                    cover_url       TEXT,
                    local_path      TEXT,
                    download_status TEXT    DEFAULT 'pending',
                    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (blogger_id) REFERENCES blogger(id)
                );

                CREATE TABLE IF NOT EXISTS transcript (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    aweme_id        TEXT    NOT NULL UNIQUE,
                    text_content    TEXT,
                    text_path       TEXT,
                    json_path       TEXT,
                    model           TEXT    DEFAULT 'large-v3-turbo',
                    status          TEXT    DEFAULT 'pending',
                    error_message   TEXT,
                    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (aweme_id) REFERENCES aweme(aweme_id)
                );

                CREATE TABLE IF NOT EXISTS summary (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    aweme_id        TEXT    NOT NULL UNIQUE,
                    summary_text    TEXT,
                    summary_path    TEXT,
                    model           TEXT,
                    status          TEXT    DEFAULT 'pending',
                    error_message   TEXT,
                    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (aweme_id) REFERENCES aweme(aweme_id)
                );

                CREATE TABLE IF NOT EXISTS push_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    aweme_id        TEXT,
                    batch_id        TEXT,
                    channel         TEXT    DEFAULT 'feishu',
                    status          TEXT,
                    error_message   TEXT,
                    pushed_at       TEXT    DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS alert_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    level           TEXT    NOT NULL,
                    component       TEXT    NOT NULL,
                    aweme_id        TEXT,
                    title           TEXT,
                    message         TEXT    NOT NULL,
                    context         TEXT,
                    notified        INTEGER DEFAULT 0,
                    created_at      TEXT    DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS research_job (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform        TEXT    DEFAULT 'douyin',
                    blogger_id      INTEGER,
                    blogger_name    TEXT,
                    status          TEXT    DEFAULT 'pending',
                    total_count     INTEGER DEFAULT 0,
                    pending_count   INTEGER DEFAULT 0,
                    success_count   INTEGER DEFAULT 0,
                    failed_count    INTEGER DEFAULT 0,
                    skipped_count   INTEGER DEFAULT 0,
                    limit_count     INTEGER DEFAULT 0,
                    since_time      TEXT,
                    until_time      TEXT,
                    push_enabled    INTEGER DEFAULT 0,
                    force_enabled   INTEGER DEFAULT 0,
                    started_at      TEXT,
                    finished_at     TEXT,
                    last_error      TEXT,
                    report_path     TEXT,
                    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (blogger_id) REFERENCES blogger(id)
                );

                CREATE TABLE IF NOT EXISTS research_job_item (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id          INTEGER NOT NULL,
                    aweme_id        TEXT,
                    status          TEXT    DEFAULT 'pending',
                    error_message   TEXT,
                    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
                    FOREIGN KEY (job_id) REFERENCES research_job(id)
                );

                CREATE INDEX IF NOT EXISTS idx_aweme_aweme_id ON aweme(aweme_id);
                CREATE INDEX IF NOT EXISTS idx_aweme_blogger_id ON aweme(blogger_id);
                CREATE INDEX IF NOT EXISTS idx_transcript_aweme_id ON transcript(aweme_id);
                CREATE INDEX IF NOT EXISTS idx_summary_aweme_id ON summary(aweme_id);
                CREATE INDEX IF NOT EXISTS idx_alert_log_created_at ON alert_log(created_at);
                CREATE INDEX IF NOT EXISTS idx_research_job_status ON research_job(status);
                CREATE INDEX IF NOT EXISTS idx_research_job_item_job_id ON research_job_item(job_id);
                CREATE INDEX IF NOT EXISTS idx_research_job_item_aweme_id ON research_job_item(aweme_id);
                """
            )
            self._ensure_column(conn, "research_job", "report_path", "TEXT")

    def upsert_blogger(self, url: str, name: str, sec_uid: str, enabled: bool = True) -> int:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO blogger (sec_uid, nickname, douyin_url, enabled, updated_at)
                VALUES (?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(sec_uid) DO UPDATE SET
                    nickname = excluded.nickname,
                    douyin_url = excluded.douyin_url,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (sec_uid, name, url, 1 if enabled else 0),
            )
            row = conn.execute("SELECT id FROM blogger WHERE sec_uid = ?", (sec_uid,)).fetchone()
            return int(row["id"])

    def aweme_exists(self, aweme_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM aweme WHERE aweme_id = ?", (aweme_id,)).fetchone()
            return row is not None

    def should_process_aweme(self, aweme_id: str) -> bool:
        """pending/failed 允许重试；只有下载完成且转录成功的作品才跳过。"""
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT a.download_status, t.status AS transcript_status
                FROM aweme a
                LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
                WHERE a.aweme_id = ?
                """,
                (aweme_id,),
            ).fetchone()
            if row is None:
                return True
            return not (row["download_status"] == "done" and row["transcript_status"] == "success")

    def get_blogger_checkpoint(self, blogger_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT last_check_at, last_aweme_id AS last_content_id
                FROM blogger
                WHERE id = ?
                """,
                (blogger_id,),
            ).fetchone()
            return dict(row) if row else {"last_check_at": None, "last_content_id": None}

    def is_aweme_fully_processed(self, aweme_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT a.download_status,
                       COALESCE(t.status, 'pending') AS transcript_status,
                       COALESCE(s.status, 'pending') AS summary_status,
                       s.summary_path
                FROM aweme a
                LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
                LEFT JOIN summary s ON s.aweme_id = a.aweme_id
                WHERE a.aweme_id = ?
                """,
                (aweme_id,),
            ).fetchone()
            if row is None:
                return False
            return bool(
                row["download_status"] == "done"
                and row["transcript_status"] == "success"
                and row["summary_status"] == "success"
                and row["summary_path"]
            )

    def insert_aweme(self, blogger_id: int, aweme: dict[str, Any], status: str = "pending") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO aweme (
                    aweme_id, blogger_id, title, aweme_type, create_time,
                    duration, video_url, cover_url, local_path, download_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(aweme_id) DO UPDATE SET
                    blogger_id = excluded.blogger_id,
                    title = excluded.title,
                    aweme_type = excluded.aweme_type,
                    create_time = excluded.create_time,
                    duration = excluded.duration,
                    video_url = COALESCE(excluded.video_url, aweme.video_url),
                    cover_url = COALESCE(excluded.cover_url, aweme.cover_url),
                    download_status = CASE
                        WHEN aweme.download_status = 'done' THEN aweme.download_status
                        ELSE excluded.download_status
                    END
                """,
                (
                    str(aweme.get("aweme_id")),
                    blogger_id,
                    aweme.get("desc") or aweme.get("title") or "",
                    aweme.get("aweme_type"),
                    aweme.get("create_time"),
                    aweme.get("duration"),
                    aweme.get("video_url"),
                    aweme.get("cover_url"),
                    aweme.get("local_path"),
                    status,
                ),
            )

    def list_recent_awemes(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT a.aweme_id, b.nickname, a.title, a.download_status,
                       COALESCE(t.status, 'pending') AS transcript_status,
                       a.created_at
                FROM aweme a
                LEFT JOIN blogger b ON b.id = a.blogger_id
                LEFT JOIN transcript t ON t.aweme_id = a.aweme_id
                ORDER BY a.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_aweme_download(
        self,
        aweme_id: str,
        status: str,
        local_path: str | None = None,
        video_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE aweme
                SET download_status = ?, local_path = COALESCE(?, local_path), video_url = COALESCE(?, video_url)
                WHERE aweme_id = ?
                """,
                (status, local_path, video_url, aweme_id),
            )

    def update_blogger_checkpoint(self, blogger_id: int, last_aweme_id: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE blogger
                SET last_check_at = datetime('now', 'localtime'),
                    last_aweme_id = COALESCE(?, last_aweme_id),
                    updated_at = datetime('now', 'localtime')
                WHERE id = ?
                """,
                (last_aweme_id, blogger_id),
            )

    def upsert_transcript(
        self,
        aweme_id: str,
        text: str,
        text_path: str,
        json_path: str,
        model: str,
        status: str,
        error_message: str | None = None,
        segments_json: dict[str, Any] | list[Any] | None = None,
        language: str | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO transcript (aweme_id, text_content, text_path, json_path, model, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(aweme_id) DO UPDATE SET
                    text_content = excluded.text_content,
                    text_path = excluded.text_path,
                    json_path = excluded.json_path,
                    model = excluded.model,
                    status = excluded.status,
                    error_message = excluded.error_message
                """,
                (aweme_id, text, text_path, json_path, model, status, error_message),
            )

    def get_successful_transcript(self, aweme_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT aweme_id, text_content, text_path, json_path, model, status
                FROM transcript
                WHERE aweme_id = ? AND status = 'success'
                """,
                (aweme_id,),
            ).fetchone()
            return dict(row) if row else None

    def clear_transcript_paths(self, aweme_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE transcript
                SET text_path = '', json_path = ''
                WHERE aweme_id = ? AND status = 'success'
                """,
                (aweme_id,),
            )

    def upsert_summary(
        self,
        aweme_id: str,
        summary_text: str,
        summary_path: str,
        model: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO summary (aweme_id, summary_text, summary_path, model, status, error_message, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                ON CONFLICT(aweme_id) DO UPDATE SET
                    summary_text = excluded.summary_text,
                    summary_path = excluded.summary_path,
                    model = excluded.model,
                    status = excluded.status,
                    error_message = excluded.error_message,
                    updated_at = excluded.updated_at
                """,
                (aweme_id, summary_text, summary_path, model, status, error_message),
            )

    def get_summary(self, aweme_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT aweme_id, summary_text, summary_path, model, status, error_message, created_at, updated_at
                FROM summary
                WHERE aweme_id = ?
                """,
                (aweme_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_transcripts_missing_summary(self, limit: int = 0) -> list[dict[str, Any]]:
        sql = """
            SELECT a.aweme_id, a.title, a.create_time, a.duration, a.video_url, a.cover_url,
                   COALESCE(b.sec_uid, b.id) AS blogger_id, b.nickname,
                   t.text_content, t.text_path
            FROM transcript t
            LEFT JOIN aweme a ON a.aweme_id = t.aweme_id
            LEFT JOIN blogger b ON b.id = a.blogger_id
            LEFT JOIN summary s ON s.aweme_id = t.aweme_id AND s.status = 'success'
            WHERE t.status = 'success' AND s.aweme_id IS NULL
            ORDER BY a.create_time DESC, a.id DESC
        """
        params: tuple[Any, ...] = ()
        if limit > 0:
            sql += " LIMIT ?"
            params = (limit,)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def insert_push_log(self, aweme_id: str | None, batch_id: str, status: str, error_message: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO push_log (aweme_id, batch_id, channel, status, error_message)
                VALUES (?, ?, 'feishu', ?, ?)
                """,
                (aweme_id, batch_id, status, error_message),
            )

    def insert_alert_log(
        self,
        level: str,
        component: str,
        message: str,
        aweme_id: str | None = None,
        title: str | None = None,
        context: str | None = None,
        notified: bool = False,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_log (level, component, aweme_id, title, message, context, notified)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (level, component, aweme_id, title, message, context, 1 if notified else 0),
            )

    def list_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT level, component, aweme_id, title, message, notified, created_at
                FROM alert_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_research_job(
        self,
        platform: str,
        blogger_id: int | None,
        blogger_name: str,
        limit_count: int,
        since_time: str | None,
        until_time: str | None,
        push_enabled: bool,
        force_enabled: bool,
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO research_job (
                    platform, blogger_id, blogger_name, status, limit_count, since_time, until_time,
                    push_enabled, force_enabled
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (platform, blogger_id, blogger_name, limit_count, since_time, until_time, 1 if push_enabled else 0, 1 if force_enabled else 0),
            )
            return int(cursor.lastrowid)

    def update_research_job(self, job_id: int, **fields: Any) -> None:
        allowed = {
            "status",
            "blogger_name",
            "total_count",
            "pending_count",
            "success_count",
            "failed_count",
            "skipped_count",
            "started_at",
            "finished_at",
            "last_error",
            "report_path",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        updates["updated_at"] = "datetime('now', 'localtime')"
        assignments = []
        params: list[Any] = []
        for key, value in updates.items():
            if key == "updated_at":
                assignments.append(f"{key} = {value}")
            else:
                assignments.append(f"{key} = ?")
                params.append(value)
        params.append(job_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE research_job SET {', '.join(assignments)} WHERE id = ?", params)

    def upsert_research_job_item(self, job_id: int, aweme_id: str, status: str, error_message: str | None = None) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM research_job_item WHERE job_id = ? AND aweme_id = ?",
                (job_id, aweme_id),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE research_job_item
                    SET status = ?, error_message = ?, updated_at = datetime('now', 'localtime')
                    WHERE id = ?
                    """,
                    (status, error_message, row["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO research_job_item (job_id, aweme_id, status, error_message)
                    VALUES (?, ?, ?, ?)
                    """,
                    (job_id, aweme_id, status, error_message),
                )

    def list_research_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT j.*,
                       i.aweme_id AS current_aweme_id,
                       i.status AS current_item_status,
                       a.title AS current_title,
                       i.updated_at AS current_updated_at
                FROM research_job j
                LEFT JOIN research_job_item i ON i.id = (
                    SELECT id
                    FROM research_job_item
                    WHERE job_id = j.id
                    ORDER BY CASE status
                        WHEN 'downloading' THEN 0
                        WHEN 'transcribing' THEN 0
                        WHEN 'summarizing' THEN 0
                        WHEN 'noting' THEN 0
                        WHEN 'running' THEN 0
                        ELSE 1
                    END, id DESC
                    LIMIT 1
                )
                LEFT JOIN aweme a ON a.aweme_id = i.aweme_id
                ORDER BY j.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if any(str(row["name"]) == column for row in rows):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def get_research_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT j.*,
                       i.aweme_id AS current_aweme_id,
                       i.status AS current_item_status,
                       a.title AS current_title,
                       i.updated_at AS current_updated_at
                FROM research_job j
                LEFT JOIN research_job_item i ON i.id = (
                    SELECT id
                    FROM research_job_item
                    WHERE job_id = j.id
                    ORDER BY CASE status
                        WHEN 'downloading' THEN 0
                        WHEN 'transcribing' THEN 0
                        WHEN 'summarizing' THEN 0
                        WHEN 'noting' THEN 0
                        WHEN 'running' THEN 0
                        ELSE 1
                    END, id DESC
                    LIMIT 1
                )
                LEFT JOIN aweme a ON a.aweme_id = i.aweme_id
                WHERE j.id = ?
                """,
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def list_research_job_items(self, job_id: int, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT i.*, a.title, b.nickname, s.summary_path,
                       COALESCE(t.status, 'pending') AS transcript_status,
                       COALESCE(s.status, 'pending') AS summary_status
                FROM research_job_item i
                LEFT JOIN aweme a ON a.aweme_id = i.aweme_id
                LEFT JOIN blogger b ON b.id = a.blogger_id
                LEFT JOIN transcript t ON t.aweme_id = i.aweme_id
                LEFT JOIN summary s ON s.aweme_id = i.aweme_id
                WHERE i.job_id = ?
                ORDER BY i.id DESC
                LIMIT ?
                """,
                (job_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
