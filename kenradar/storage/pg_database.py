from __future__ import annotations

import json
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from kenradar.core.ai_json import fallback_analysis, parse_ai_json


class PgRow(dict):
    def __init__(self, names: list[str], values: tuple[Any, ...]):
        super().__init__(zip(names, values))
        self._values = values

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class PgCursor:
    def __init__(self, cursor: Any):
        self._cursor = cursor

    def execute(self, sql: str, params: Any = None) -> "PgCursor":
        self._cursor.execute(sql, params)
        return self

    def fetchone(self) -> PgRow | None:
        row = self._cursor.fetchone()
        if row is None:
            return None
        return PgRow(self._names(), tuple(row))

    def fetchall(self) -> list[PgRow]:
        return [PgRow(self._names(), tuple(row)) for row in self._cursor.fetchall()]

    @property
    def lastrowid(self) -> int | None:
        return None

    def _names(self) -> list[str]:
        return [column.name for column in (self._cursor.description or [])]


class PgConnection:
    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, sql: str, params: Any = None) -> PgCursor:
        cursor = PgCursor(self._conn.cursor())
        return cursor.execute(sql, params)

    def executescript(self, sql: str) -> None:
        self._conn.execute(sql)


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: Any = None

    def _ensure_pool(self) -> Any:
        if self._pool is None:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(self.database_url, min_size=1, max_size=5, open=True)
        return self._pool

    @contextmanager
    def connect(self) -> Iterator[PgConnection]:
        pool = self._ensure_pool()
        with pool.connection() as conn:
            try:
                yield PgConnection(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)

    def _platform_id(self, code: str = "douyin") -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM platform WHERE code = %s", (code,)).fetchone()
            if row is None:
                raise RuntimeError(f"平台未初始化: {code}")
            return int(row["id"])

    def upsert_blogger(self, url: str, name: str, sec_uid: str, enabled: bool = True) -> int:
        platform_id = self._platform_id("douyin")
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO creator (platform_id, platform_uid, nickname, profile_url, enabled, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT(platform_id, platform_uid) DO UPDATE SET
                    nickname = EXCLUDED.nickname,
                    profile_url = EXCLUDED.profile_url,
                    enabled = EXCLUDED.enabled,
                    updated_at = NOW()
                RETURNING id
                """,
                (platform_id, sec_uid, name, url, enabled),
            ).fetchone()
            return int(row["id"])

    def aweme_exists(self, aweme_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM content_item WHERE platform_id = %s AND content_id = %s",
                (self._platform_id("douyin"), aweme_id),
            ).fetchone() is not None

    def should_process_aweme(self, aweme_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.download_status, t.status AS transcript_status
                FROM content_item c
                LEFT JOIN transcript t ON t.content_item_id = c.id
                WHERE c.platform_id = %s AND c.content_id = %s
                """,
                (self._platform_id("douyin"), aweme_id),
            ).fetchone()
            if row is None:
                return True
            return not (row["download_status"] == "done" and row["transcript_status"] == "success")

    def get_blogger_checkpoint(self, blogger_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT last_check_at, last_content_id
                FROM creator
                WHERE id = %s
                """,
                (blogger_id,),
            ).fetchone()
            return dict(row) if row else {"last_check_at": None, "last_content_id": None}

    def is_aweme_fully_processed(self, aweme_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.download_status,
                       COALESCE(t.status, 'pending') AS transcript_status,
                       COALESCE(a.status, 'pending') AS summary_status,
                       n.note_path AS summary_path
                FROM content_item c
                LEFT JOIN transcript t ON t.content_item_id = c.id
                LEFT JOIN ai_analysis a ON a.content_item_id = c.id AND a.analysis_type = 'summary'
                LEFT JOIN content_note n ON n.content_item_id = c.id AND n.note_type = 'content'
                WHERE c.platform_id = %s AND c.content_id = %s
                """,
                (self._platform_id("douyin"), aweme_id),
            ).fetchone()
            if row is None:
                return False
            return bool(row["download_status"] == "done" and row["transcript_status"] == "success" and row["summary_status"] == "success" and row["summary_path"])

    def insert_aweme(self, blogger_id: int, aweme: dict[str, Any], status: str = "pending") -> None:
        aweme_id = str(aweme.get("aweme_id") or "")
        platform_id = self._platform_id("douyin")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO content_item (
                    platform_id, content_id, creator_id, content_type, title, description, publish_time,
                    duration, source_url, media_url, cover_url, local_path, download_status, extra
                ) VALUES (%s, %s, %s, 'video', %s, %s, to_timestamp(%s), %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT(platform_id, content_id) DO UPDATE SET
                    creator_id = EXCLUDED.creator_id,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    publish_time = EXCLUDED.publish_time,
                    duration = EXCLUDED.duration,
                    media_url = COALESCE(EXCLUDED.media_url, content_item.media_url),
                    cover_url = COALESCE(EXCLUDED.cover_url, content_item.cover_url),
                    local_path = COALESCE(EXCLUDED.local_path, content_item.local_path),
                    extra = content_item.extra || EXCLUDED.extra,
                    download_status = CASE
                        WHEN content_item.download_status = 'done' THEN content_item.download_status
                        ELSE EXCLUDED.download_status
                    END
                """,
                (
                    platform_id,
                    aweme_id,
                    blogger_id,
                    aweme.get("desc") or aweme.get("title") or "",
                    aweme.get("desc") or aweme.get("title") or "",
                    _epoch(aweme.get("create_time")),
                    _duration(aweme.get("duration")),
                    f"https://www.douyin.com/video/{aweme_id}" if aweme_id else None,
                    aweme.get("video_url"),
                    aweme.get("cover_url"),
                    aweme.get("local_path"),
                    status,
                    json.dumps(aweme, ensure_ascii=False),
                ),
            )

    def list_recent_awemes(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.content_id AS aweme_id, cr.nickname, c.title, c.download_status,
                       COALESCE(t.status, 'pending') AS transcript_status,
                       c.created_at
                FROM content_item c
                LEFT JOIN creator cr ON cr.id = c.creator_id
                LEFT JOIN transcript t ON t.content_item_id = c.id
                ORDER BY c.id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_aweme_download(self, aweme_id: str, status: str, local_path: str | None = None, video_url: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE content_item
                SET download_status = %s,
                    local_path = COALESCE(%s, local_path),
                    media_url = COALESCE(%s, media_url),
                    extra = extra || %s::jsonb
                WHERE platform_id = %s AND content_id = %s
                """,
                (status, local_path, video_url, json.dumps(metadata or {}, ensure_ascii=False), self._platform_id("douyin"), aweme_id),
            )

    def update_blogger_checkpoint(self, blogger_id: int, last_aweme_id: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE creator
                SET last_check_at = NOW(),
                    last_content_id = COALESCE(%s, last_content_id),
                    updated_at = NOW()
                WHERE id = %s
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
        content_item_id = self._content_item_id(aweme_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO transcript (
                    content_item_id, aweme_id, text_content, segments_json, text_path, json_path,
                    model, language, status, error_message, duration_seconds, updated_at
                ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT(content_item_id) DO UPDATE SET
                    aweme_id = EXCLUDED.aweme_id,
                    text_content = EXCLUDED.text_content,
                    segments_json = EXCLUDED.segments_json,
                    text_path = EXCLUDED.text_path,
                    json_path = EXCLUDED.json_path,
                    model = EXCLUDED.model,
                    language = EXCLUDED.language,
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message,
                    duration_seconds = EXCLUDED.duration_seconds,
                    updated_at = NOW()
                WHERE NOT (transcript.status = 'success' AND EXCLUDED.status <> 'success')
                """,
                (
                    content_item_id,
                    aweme_id,
                    text,
                    json.dumps(segments_json or {}, ensure_ascii=False),
                    text_path,
                    json_path,
                    model,
                    language,
                    status,
                    error_message,
                    duration_seconds,
                ),
            )

    def get_successful_transcript(self, aweme_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT aweme_id, text_content, text_path, json_path, model, status
                FROM transcript
                WHERE aweme_id = %s AND status = 'success'
                """,
                (aweme_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_aweme_local_path(self, aweme_id: str) -> str:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT local_path
                FROM content_item
                WHERE platform_id = %s AND content_id = %s
                """,
                (self._platform_id("douyin"), aweme_id),
            ).fetchone()
            return str(row["local_path"] or "") if row else ""

    def list_aweme_download_paths(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT content_id AS aweme_id, local_path
                FROM content_item
                WHERE platform_id = %s
                  AND local_path IS NOT NULL
                  AND local_path != ''
                """,
                (self._platform_id("douyin"),),
            ).fetchall()
            return [dict(row) for row in rows]

    def clear_transcript_paths(self, aweme_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE transcript
                SET text_path = '', json_path = '', updated_at = NOW()
                WHERE aweme_id = %s AND status = 'success'
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
        content_item_id = self._content_item_id(aweme_id)
        result_json = _parse_json(summary_text)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_analysis (
                    content_item_id, analysis_type, result_json, result_text, model, provider, status, error_message, updated_at
                ) VALUES (%s, 'summary', %s::jsonb, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT(content_item_id, analysis_type) DO UPDATE SET
                    result_json = EXCLUDED.result_json,
                    result_text = EXCLUDED.result_text,
                    model = EXCLUDED.model,
                    provider = EXCLUDED.provider,
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message,
                    updated_at = NOW()
                """,
                (content_item_id, json.dumps(result_json, ensure_ascii=False), summary_text, model, "openai-compatible", status, error_message),
            )
            conn.execute(
                """
                INSERT INTO content_note (content_item_id, note_type, note_path, title, updated_at)
                VALUES (%s, 'content', %s, %s, NOW())
                ON CONFLICT(content_item_id, note_type) DO UPDATE SET
                    note_path = EXCLUDED.note_path,
                    title = EXCLUDED.title,
                    updated_at = NOW()
                """,
                (content_item_id, summary_path, _note_title(summary_path)),
            )

    def get_summary(self, aweme_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM summary WHERE aweme_id = %s", (aweme_id,)).fetchone()
            return dict(row) if row else None

    def list_transcripts_missing_summary(self, limit: int = 0) -> list[dict[str, Any]]:
        sql = """
            SELECT a.aweme_id, a.title, a.create_time, a.duration, a.video_url, a.cover_url,
                   COALESCE(b.sec_uid, b.id::text) AS blogger_id, b.nickname,
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
            sql += " LIMIT %s"
            params = (limit,)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]

    def insert_push_log(self, aweme_id: str | None, batch_id: str, status: str, error_message: str | None = None, message_type: str | None = None) -> None:
        content_item_id = self._content_item_id(aweme_id, required=False) if aweme_id else None
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO push_log (content_item_id, aweme_id, batch_id, channel, message_type, status, error_message)
                VALUES (%s, %s, %s, 'feishu', %s, %s, %s)
                """,
                (content_item_id, aweme_id, batch_id, message_type or "card", status, error_message),
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
        content_item_id = self._content_item_id(aweme_id, required=False) if aweme_id else None
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_log (level, component, content_item_id, aweme_id, title, message, context, notified)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (level, component, content_item_id, aweme_id, title, message, _json_or_empty(context), notified),
            )

    def list_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT level, component, aweme_id, title, message, notified, created_at
                FROM alert_log
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def set_content_curation(
        self,
        aweme_id: str,
        *,
        favorite: bool | None = None,
        topic_pool_status: str | None = None,
        research_status: str | None = None,
        user_note: str | None = None,
    ) -> None:
        content_item_id = self._content_item_id(aweme_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO content_curation (
                    content_item_id, favorite, topic_pool_status, research_status, user_note, updated_at
                ) VALUES (%s, COALESCE(%s, FALSE), COALESCE(%s, ''), COALESCE(%s, ''), COALESCE(%s, ''), NOW())
                ON CONFLICT(content_item_id) DO UPDATE SET
                    favorite = CASE WHEN %s IS NULL THEN content_curation.favorite ELSE EXCLUDED.favorite END,
                    topic_pool_status = CASE WHEN %s IS NULL THEN content_curation.topic_pool_status ELSE EXCLUDED.topic_pool_status END,
                    research_status = CASE WHEN %s IS NULL THEN content_curation.research_status ELSE EXCLUDED.research_status END,
                    user_note = CASE WHEN %s IS NULL THEN content_curation.user_note ELSE EXCLUDED.user_note END,
                    updated_at = NOW()
                """,
                (
                    content_item_id,
                    favorite,
                    topic_pool_status,
                    research_status,
                    user_note,
                    favorite,
                    topic_pool_status,
                    research_status,
                    user_note,
                ),
            )

    def toggle_favorite(self, aweme_id: str) -> bool:
        content_item_id = self._content_item_id(aweme_id)
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO content_curation (content_item_id, favorite, updated_at)
                VALUES (%s, TRUE, NOW())
                ON CONFLICT(content_item_id) DO UPDATE SET
                    favorite = NOT content_curation.favorite,
                    updated_at = NOW()
                RETURNING favorite
                """,
                (content_item_id,),
            ).fetchone()
            return bool(row["favorite"]) if row else False

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
        platform_id = self._platform_id(platform or "douyin")
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO research_job (
                    platform_id, creator_id, creator_name, platform, blogger_id, blogger_name,
                    status, limit_count, since_time, until_time, push_enabled, force_enabled
                ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (platform_id, blogger_id, blogger_name, platform, blogger_id, blogger_name, limit_count, since_time or None, until_time or None, push_enabled, force_enabled),
            ).fetchone()
            return int(row["id"])

    def update_research_job(self, job_id: int, **fields: Any) -> None:
        allowed = {
            "status",
            "blogger_name",
            "creator_name",
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
        if "blogger_name" in updates and "creator_name" not in updates:
            updates["creator_name"] = updates["blogger_name"]
        if not updates:
            return
        assignments = [f"{key} = %s" for key in updates]
        assignments.append("updated_at = NOW()")
        params = list(updates.values()) + [job_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE research_job SET {', '.join(assignments)} WHERE id = %s", params)

    def upsert_research_job_item(self, job_id: int, aweme_id: str, status: str, error_message: str | None = None) -> None:
        content_item_id = self._content_item_id(aweme_id, required=False)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO research_job_item (job_id, content_item_id, aweme_id, status, error_message, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT(job_id, aweme_id) DO UPDATE SET
                    content_item_id = COALESCE(EXCLUDED.content_item_id, research_job_item.content_item_id),
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message,
                    updated_at = NOW()
                """,
                (job_id, content_item_id, aweme_id, status, error_message),
            )

    def list_research_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(RESEARCH_JOBS_SQL + " ORDER BY j.id DESC LIMIT %s", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get_research_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(RESEARCH_JOBS_SQL + " WHERE j.id = %s", (job_id,)).fetchone()
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
                WHERE i.job_id = %s
                ORDER BY i.id DESC
                LIMIT %s
                """,
                (job_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def _content_item_id(self, aweme_id: str | None, required: bool = True) -> int | None:
        if not aweme_id:
            if required:
                raise ValueError("缺少 aweme_id")
            return None
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM content_item WHERE platform_id = %s AND content_id = %s",
                (self._platform_id("douyin"), aweme_id),
            ).fetchone()
            if row is None:
                if required:
                    raise ValueError(f"未找到内容条目: {aweme_id}")
                return None
            return int(row["id"])


def _epoch(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _duration(value: Any) -> int:
    try:
        duration = int(float(value or 0))
    except (TypeError, ValueError):
        return 0
    if duration > 10000:
        return max(1, round(duration / 1000))
    return max(0, duration)


def _parse_json(value: str) -> Any:
    parsed = parse_ai_json(value)
    if not isinstance(parsed, dict):
        return fallback_analysis(value)
    _complete_analysis_scores(parsed)
    return parsed


def _complete_analysis_scores(parsed: dict[str, Any]) -> None:
    importance = _score(parsed.get("importance_score"), parsed.get("importance_level"))
    novelty = _score(parsed.get("novelty_score"))
    density = _score(parsed.get("information_density"))
    relevance = _score(parsed.get("business_relevance"))
    parsed["importance_score"] = importance
    parsed["novelty_score"] = novelty
    parsed["information_density"] = density
    parsed["business_relevance"] = relevance
    parsed["value_score"] = _score(parsed.get("value_score")) or _average_score(importance, novelty, density, relevance)
    if not str(parsed.get("recommended_action") or "").strip():
        parsed["recommended_action"] = "review" if float(parsed.get("value_score") or 0) >= 3 else "archive"


def _fallback_analysis_json(value: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:\w+)?\s*", "", str(value or "").strip())
    text = re.sub(r"\s*```$", "", text)
    if not text:
        return {}
    lines = []
    for line in text.splitlines():
        clean = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip(" -•\t`")
        if clean:
            lines.append(clean)
    if not lines:
        return {}
    summary = _limit_plain_text(lines[0], 180)
    body = _limit_plain_text(" ".join(lines[1:]) or summary, 250)
    scores = _fallback_scores_from_text(text)
    topics = _infer_topics(text)
    return {
        "brief_title": "",
        "brief_summary": summary,
        "content_sections": [{"title": "核心要点1", "content": body}],
        "content_category": topics[0] if topics else "",
        "keywords": topics[:8],
        "tags": topics[:5] or ["投资策略"],
        "importance_score": scores["importance_score"],
        "novelty_score": scores["novelty_score"],
        "information_density": scores["information_density"],
        "business_relevance": scores["business_relevance"],
        "value_score": scores["value_score"],
        "recommended_action": scores["recommended_action"],
        "recommendation_reason": "AI 返回非 JSON，系统按可读摘要保守评估",
        "deep_research_suggested": scores["value_score"] >= 4.2,
    }


def _score(value: Any, level: Any = None) -> float:
    try:
        score = float(value)
        if score > 0:
            return max(1.0, min(5.0, score))
    except (TypeError, ValueError):
        pass
    level_text = str(level or "")
    if level_text == "高":
        return 4.5
    if level_text == "中":
        return 3.0
    if level_text == "低":
        return 2.0
    return 0.0


def _average_score(*values: float) -> float:
    scores = [float(value) for value in values if value]
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 1)


def _fallback_scores_from_text(text: str) -> dict[str, Any]:
    value = str(text or "")
    information_density = 3.0
    business_relevance = 3.0
    novelty_score = 3.0
    importance_score = 3.0
    if len(value) > 1200 or len(re.findall(r"\d+(?:\.\d+)?%?", value)) >= 5:
        information_density = 3.5
    if any(word in value for word in ["投资", "配置", "估值", "业绩", "需求", "供给", "ROE", "公司", "板块", "行业"]):
        business_relevance = 3.5
    if any(word in value for word in ["AI", "算力", "半导体", "芯片", "新能源", "电力", "券商", "有色", "创新药", "港股", "A股"]):
        importance_score = 3.5
    if any(word in value for word in ["拐点", "超预期", "周期", "催化", "新高", "反转", "爆发", "国产化"]):
        novelty_score = 3.5
    value_score = round((importance_score + novelty_score + information_density + business_relevance) / 4, 1)
    return {
        "importance_score": importance_score,
        "novelty_score": novelty_score,
        "information_density": information_density,
        "business_relevance": business_relevance,
        "value_score": value_score,
        "recommended_action": "research" if value_score >= 4.2 else ("review" if value_score >= 3.0 else "archive"),
    }


def _infer_topics(text: str) -> list[str]:
    rules = [
        ("AI", "AI产业"),
        ("人工智能", "AI产业"),
        ("算力", "算力中心"),
        ("半导体", "半导体"),
        ("芯片", "半导体"),
        ("港股", "港股市场"),
        ("A股", "股票市场"),
        ("股票", "股票市场"),
        ("券商", "证券行业"),
        ("有色", "有色金属"),
        ("电力", "电力行业"),
        ("新能源", "新能源"),
        ("电池", "新能源"),
        ("储能", "新能源"),
        ("策略", "投资策略"),
        ("配置", "资产配置"),
    ]
    topics: list[str] = []
    for keyword, topic in rules:
        if keyword in text and topic not in topics:
            topics.append(topic)
    return topics


def _limit_plain_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" ，。,.；;") + "。"


def _json_or_empty(value: str | None) -> str:
    if not value:
        return "{}"
    try:
        json.loads(value)
        return value
    except json.JSONDecodeError:
        return json.dumps({"raw": value}, ensure_ascii=False)


def _note_title(path: str) -> str:
    return path.rsplit("/", 1)[-1].removesuffix(".md") if path else ""


RESEARCH_JOBS_SQL = """
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
"""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS platform (
    id           SERIAL PRIMARY KEY,
    code         VARCHAR(32) UNIQUE NOT NULL,
    display_name VARCHAR(64),
    enabled      BOOLEAN DEFAULT TRUE,
    config_json  JSONB DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO platform (code, display_name)
VALUES ('douyin', '抖音'), ('bilibili', 'B站'), ('xiaohongshu', '小红书'), ('youtube', 'YouTube')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS creator (
    id              SERIAL PRIMARY KEY,
    platform_id     INT NOT NULL REFERENCES platform(id),
    platform_uid    VARCHAR(256) NOT NULL,
    nickname        VARCHAR(256),
    profile_url     TEXT,
    avatar_url      TEXT,
    enabled         BOOLEAN DEFAULT TRUE,
    check_modes     VARCHAR(64) DEFAULT 'post',
    last_check_at   TIMESTAMPTZ,
    last_content_id VARCHAR(128),
    extra           JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(platform_id, platform_uid)
);

CREATE TABLE IF NOT EXISTS content_item (
    id              SERIAL PRIMARY KEY,
    platform_id     INT NOT NULL REFERENCES platform(id),
    content_id      VARCHAR(128) NOT NULL,
    creator_id      INT NOT NULL REFERENCES creator(id),
    content_type    VARCHAR(32) DEFAULT 'video',
    title           TEXT,
    description     TEXT,
    publish_time    TIMESTAMPTZ,
    duration        INT,
    source_url      TEXT,
    media_url       TEXT,
    cover_url       TEXT,
    local_path      TEXT,
    download_status VARCHAR(32) DEFAULT 'pending',
    extra           JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(platform_id, content_id)
);

CREATE TABLE IF NOT EXISTS transcript (
    id               SERIAL PRIMARY KEY,
    content_item_id  INT NOT NULL REFERENCES content_item(id),
    aweme_id         VARCHAR(128) UNIQUE,
    text_content     TEXT,
    segments_json    JSONB,
    text_path        TEXT,
    json_path        TEXT,
    model            VARCHAR(64) DEFAULT 'large-v3-turbo',
    language         VARCHAR(16),
    status           VARCHAR(32) DEFAULT 'pending',
    error_message    TEXT,
    duration_seconds REAL,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(content_item_id)
);

CREATE TABLE IF NOT EXISTS ai_analysis (
    id              SERIAL PRIMARY KEY,
    content_item_id INT NOT NULL REFERENCES content_item(id),
    analysis_type   VARCHAR(32) DEFAULT 'summary',
    result_json     JSONB,
    result_text     TEXT,
    model           VARCHAR(128),
    provider        VARCHAR(64),
    prompt_hash     VARCHAR(64),
    status          VARCHAR(32) DEFAULT 'pending',
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(content_item_id, analysis_type)
);

CREATE TABLE IF NOT EXISTS content_note (
    id              SERIAL PRIMARY KEY,
    content_item_id INT NOT NULL REFERENCES content_item(id),
    note_type       VARCHAR(32) DEFAULT 'content',
    note_path       TEXT NOT NULL,
    title           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(content_item_id, note_type)
);

CREATE TABLE IF NOT EXISTS content_curation (
    content_item_id    INT PRIMARY KEY REFERENCES content_item(id),
    favorite           BOOLEAN DEFAULT FALSE,
    topic_pool_status  VARCHAR(32) DEFAULT '',
    research_status    VARCHAR(32) DEFAULT '',
    user_note          TEXT,
    created_at         TIMESTAMPTZ DEFAULT NOW(),
    updated_at         TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS push_log (
    id              SERIAL PRIMARY KEY,
    content_item_id INT REFERENCES content_item(id),
    aweme_id        VARCHAR(128),
    batch_id        VARCHAR(64),
    channel         VARCHAR(32) DEFAULT 'feishu',
    message_type    VARCHAR(32),
    status          VARCHAR(32),
    error_message   TEXT,
    pushed_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_log (
    id              SERIAL PRIMARY KEY,
    level           VARCHAR(16) NOT NULL,
    component       VARCHAR(64) NOT NULL,
    content_item_id INT REFERENCES content_item(id),
    aweme_id        VARCHAR(128),
    title           TEXT,
    message         TEXT NOT NULL,
    context         JSONB,
    notified        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_job (
    id              SERIAL PRIMARY KEY,
    platform_id     INT REFERENCES platform(id),
    creator_id      INT REFERENCES creator(id),
    creator_name    VARCHAR(256),
    platform        TEXT DEFAULT 'douyin',
    blogger_id      INT,
    blogger_name    VARCHAR(256),
    status          VARCHAR(32) DEFAULT 'pending',
    total_count     INT DEFAULT 0,
    pending_count   INT DEFAULT 0,
    success_count   INT DEFAULT 0,
    failed_count    INT DEFAULT 0,
    skipped_count   INT DEFAULT 0,
    limit_count     INT DEFAULT 0,
    since_time      TIMESTAMPTZ,
    until_time      TIMESTAMPTZ,
    push_enabled    BOOLEAN DEFAULT FALSE,
    force_enabled   BOOLEAN DEFAULT FALSE,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    last_error      TEXT,
    report_path     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research_job_item (
    id              SERIAL PRIMARY KEY,
    job_id          INT NOT NULL REFERENCES research_job(id),
    content_item_id INT REFERENCES content_item(id),
    aweme_id        VARCHAR(128),
    status          VARCHAR(32) DEFAULT 'pending',
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(job_id, aweme_id)
);

CREATE INDEX IF NOT EXISTS idx_creator_platform_uid ON creator(platform_id, platform_uid);
CREATE INDEX IF NOT EXISTS idx_content_item_content_id ON content_item(platform_id, content_id);
CREATE INDEX IF NOT EXISTS idx_content_item_creator ON content_item(creator_id);
CREATE INDEX IF NOT EXISTS idx_content_item_publish ON content_item(publish_time DESC);
CREATE INDEX IF NOT EXISTS idx_transcript_content ON transcript(content_item_id);
CREATE INDEX IF NOT EXISTS idx_ai_analysis_content ON ai_analysis(content_item_id, analysis_type);
CREATE INDEX IF NOT EXISTS idx_content_curation_topic ON content_curation(topic_pool_status);
CREATE INDEX IF NOT EXISTS idx_content_curation_research ON content_curation(research_status);
CREATE INDEX IF NOT EXISTS idx_push_log_pushed ON push_log(pushed_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_log_created ON alert_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_research_job_status ON research_job(status);
CREATE INDEX IF NOT EXISTS idx_research_job_item_job ON research_job_item(job_id);

DROP VIEW IF EXISTS summary;
DROP VIEW IF EXISTS aweme;
DROP VIEW IF EXISTS blogger;

CREATE OR REPLACE VIEW blogger AS
SELECT
    c.id,
    c.platform_uid AS sec_uid,
    c.nickname,
    c.profile_url AS douyin_url,
    c.avatar_url,
    CASE WHEN c.enabled THEN 1 ELSE 0 END AS enabled,
    c.check_modes,
    c.last_check_at,
    c.last_content_id AS last_aweme_id,
    c.created_at,
    c.updated_at
FROM creator c;

CREATE OR REPLACE VIEW aweme AS
SELECT
    ci.id,
    ci.content_id AS aweme_id,
    ci.creator_id AS blogger_id,
    ci.title,
    0 AS aweme_type,
    COALESCE(EXTRACT(EPOCH FROM ci.publish_time)::bigint, 0) AS create_time,
    ci.duration,
    ci.media_url AS video_url,
    ci.cover_url,
    ci.local_path,
    ci.download_status,
    ci.extra,
    ci.created_at
FROM content_item ci;

CREATE OR REPLACE VIEW summary AS
SELECT
    a.id,
    ci.content_id AS aweme_id,
    a.result_text AS summary_text,
    n.note_path AS summary_path,
    a.model,
    a.status,
    a.error_message,
    a.created_at,
    a.updated_at
FROM ai_analysis a
JOIN content_item ci ON ci.id = a.content_item_id
LEFT JOIN content_note n ON n.content_item_id = ci.id AND n.note_type = 'content'
WHERE a.analysis_type = 'summary';
"""
