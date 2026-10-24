"""V2 content storage and legacy call names backed by the same V2 tables."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select, update, insert, func, and_


class ContentMethods:
    def content_processing_rows(self, *, platform="douyin", external_id=None, successful_transcript=False):
        c, p, cr, t, a, n = (self.table(name) for name in ("content_item", "platform", "creator", "transcript", "ai_analysis", "content_note"))
        stmt = select(c, c.c.content_id.label("aweme_id"), c.c.creator_id.label("db_blogger_id"),
            c.c.content_type.label("aweme_type"), c.c.publish_time.label("create_time"), c.c.media_url.label("video_url"),
            p.c.code.label("platform"), cr.c.platform_uid.label("blogger_id"), cr.c.nickname,
            t.c.text_content, t.c.text_path, t.c.model.label("transcript_model"), t.c.status.label("transcript_status"),
            a.c.status.label("summary_status"), n.c.note_path.label("summary_path")).select_from(c)
        stmt = stmt.join(p, p.c.id == c.c.platform_id).outerjoin(cr, cr.c.id == c.c.creator_id)
        stmt = stmt.outerjoin(t, t.c.content_item_id == c.c.id).outerjoin(a, and_(a.c.content_item_id == c.c.id, a.c.analysis_type == "summary"))
        stmt = stmt.outerjoin(n, and_(n.c.content_item_id == c.c.id, n.c.note_type == "content")).where(p.c.code == platform)
        if external_id:
            stmt = stmt.where(c.c.content_id == str(external_id))
        if successful_transcript:
            stmt = stmt.where(t.c.status == "success", t.c.text_content != "")
        with self.connect() as conn:
            rows = [dict(r) for r in conn.execute(stmt.order_by(c.c.publish_time.desc(), c.c.id.desc())).fetchall()]
        for row in rows:
            row["create_time"] = int(datetime.fromisoformat(row["create_time"].replace("Z", "+00:00")).timestamp()) if row["create_time"] else 0
        return rows

    def load_aweme_for_retry(self, aweme_id):
        rows = self.content_processing_rows(external_id=aweme_id)
        return rows[0] if rows else None

    def set_content_curation(self, aweme_id, *, favorite=None, topic_pool_status=None, research_status=None, user_note=None):
        from .sqlite_database import utc_now
        values = {k: v for k, v in dict(favorite=favorite, topic_pool_status=topic_pool_status,
            research_status=research_status, user_note=user_note).items() if v is not None}
        self._upsert("content_curation", dict(content_item_id=self._content_item_id(aweme_id),
            updated_at=utc_now(), **values), ("content_item_id",))

    def _content_item_id(self, aweme_id, required=True, platform="douyin"):
        row = self.find_content_item(platform, str(aweme_id))
        if not row and required:
            raise ValueError(f"内容不存在: {platform}/{aweme_id}")
        return row["id"] if row else None

    def aweme_exists(self, aweme_id):
        return self.content_exists("douyin", str(aweme_id))

    def should_process_aweme(self, aweme_id):
        row = self.find_content_item("douyin", str(aweme_id))
        return not row or not (row["download_status"] == "done" and self.get_successful_transcript(aweme_id))

    def is_aweme_fully_processed(self, aweme_id):
        row = self.find_content_item("douyin", str(aweme_id))
        if not row:
            return False
        bundle = self.get_current_bundle(row["id"])
        return bool(row["download_status"] == "done" and bundle["transcript"] and
            bundle["transcript"]["status"] == "success" and bundle["analysis"] and
            bundle["analysis"]["status"] == "success" and bundle["note"] and bundle["note"]["note_path"])

    def insert_aweme(self, blogger_id, aweme, status="pending"):
        aid = str(aweme.get("aweme_id") or "")
        if not aid:
            raise ValueError("作品标识不能为空")
        epoch = aweme.get("create_time")
        published = datetime.fromtimestamp(float(epoch), timezone.utc) if epoch else None
        duration = aweme.get("duration")
        self.upsert_content_item("douyin", aid, blogger_id, content_type="video",
            title=aweme.get("desc") or aweme.get("title") or "", description=aweme.get("desc") or "",
            publish_time=published, duration=int(duration) if duration else None,
            source_url=f"https://www.douyin.com/video/{aid}", media_url=aweme.get("video_url"),
            cover_url=aweme.get("cover_url"), local_path=aweme.get("local_path"), download_status=status, extra=aweme)

    def get_creator(self, creator_id):
        t = self.table("creator")
        with self.connect() as conn:
            row = conn.execute(select(t).where(t.c.id == creator_id)).fetchone()
            return dict(row) if row else None

    def get_blogger_checkpoint(self, blogger_id):
        row = self.get_creator(blogger_id) or {}
        return {k: row.get(k) for k in ("last_check_at", "last_content_id")}

    def update_blogger_checkpoint(self, blogger_id, last_aweme_id):
        from .sqlite_database import utc_now
        t = self.table("creator")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == blogger_id).values(last_check_at=utc_now(), updated_at=utc_now(),
                last_content_id=func.coalesce(str(last_aweme_id) if last_aweme_id else None, t.c.last_content_id)))

    def update_aweme_download(self, aweme_id, status, local_path=None, video_url=None, metadata=None):
        from .sqlite_database import utc_now
        t = self.table("content_item")
        cid = self._content_item_id(aweme_id)
        with self.connect(write=True) as conn:
            old = conn.execute(select(t).where(t.c.id == cid)).fetchone()
            conn.execute(update(t).where(t.c.id == cid).values(download_status=status,
                local_path=local_path if local_path is not None else old["local_path"],
                media_url=video_url if video_url is not None else old["media_url"],
                extra=json.dumps({**(old["extra"] or {}), **(metadata or {})}, ensure_ascii=False), updated_at=utc_now()))

    def get_aweme_local_path(self, aweme_id):
        return str((self.find_content_item("douyin", str(aweme_id)) or {}).get("local_path") or "")

    def list_aweme_download_paths(self):
        t, p = self.table("content_item"), self.table("platform")
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(select(t.c.content_id.label("aweme_id"), t.c.local_path)
                .join(p, p.c.id == t.c.platform_id).where(p.c.code == "douyin", t.c.local_path.is_not(None), t.c.local_path != "")).fetchall()]

    def upsert_transcript(self, aweme_id, text, text_path, json_path, model, status, error_message=None,
                          segments_json=None, language=None, duration_seconds=None, platform="douyin"):
        from .sqlite_database import utc_now
        cid = self._content_item_id(aweme_id, platform=platform)
        t, rev = self.table("transcript"), self.table("transcript_revision")
        if status == "success" and not text.strip():
            raise ValueError("成功转录必须包含原始文本")
        with self.connect(write=True) as conn:
            old = conn.execute(select(t).where(t.c.content_item_id == cid)).fetchone()
            if old and old["status"] == "success" and status != "success":
                return
            if old and old["text_content"] and old["text_content"] != text:
                conn.execute(insert(rev).values(content_item_id=cid, text_content=old["text_content"],
                    record_json=json.dumps(dict(old), ensure_ascii=False)))
            self._upsert("transcript", dict(content_item_id=cid, aweme_id=str(aweme_id), text_content=text,
                text_path=text_path, json_path=json_path, model=model, status=status, error_message=error_message,
                segments_json=segments_json, language=language, duration_seconds=duration_seconds,
                completed_at=utc_now() if status == "success" else None, updated_at=utc_now()), ("content_item_id",), conn=conn)

    def get_successful_transcript(self, aweme_id, platform="douyin"):
        row = self.find_content_item(platform, str(aweme_id))
        if not row:
            return None
        t = self.get_current_bundle(row["id"])["transcript"]
        return t if t and t["status"] == "success" else None

    def clear_transcript_paths(self, aweme_id, platform="douyin"):
        from .sqlite_database import utc_now
        cid, t = self._content_item_id(aweme_id, platform=platform), self.table("transcript")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.content_item_id == cid, t.c.status == "success").values(
                text_path="", json_path="", updated_at=utc_now()))

    def upsert_summary(self, aweme_id, summary_text, summary_path, model, status, error_message=None, platform="douyin"):
        cid = self._content_item_id(aweme_id, platform=platform)
        try:
            result = json.loads(summary_text)
        except (ValueError, TypeError):
            result = {}
        if status not in {"success", "degraded"}:
            # A failure never destroys the successful current result.
            self.mark_content_failure(cid, "ORGANIZER_FAILED", error_message or "整理失败")
            a, n = self.table("ai_analysis"), self.table("content_note")
            with self.connect(write=True) as conn:
                previous = conn.execute(select(a.c.status).where(a.c.content_item_id == cid, a.c.analysis_type == "summary")).fetchone()
                if not previous or previous["status"] != "success":
                    self._upsert("ai_analysis", dict(content_item_id=cid, analysis_type="summary", result_json=result,
                        result_text=summary_text, model=model, status="failed", error_message=error_message),
                        ("content_item_id", "analysis_type"), conn=conn)
                    if summary_path:
                        self._upsert("content_note", dict(content_item_id=cid, note_type="content", note_path=summary_path,
                            title=Path(summary_path).stem), ("content_item_id", "note_type"), conn=conn)
            return
        self.replace_analysis_and_note(cid, {"result_json": result, "result_text": summary_text,
            "model": model, "provider": "openai-compatible", "status": status, "error_message": error_message},
            {"note_path": summary_path, "title": Path(summary_path).stem})

    def get_summary(self, aweme_id):
        row = self.find_content_item("douyin", str(aweme_id))
        if not row:
            return None
        bundle = self.get_current_bundle(row["id"])
        analysis = bundle["analysis"]
        return {**analysis, "summary_path": (bundle["note"] or {}).get("note_path")} if analysis else None

    def list_recent_awemes(self, limit=20):
        c, cr, t = self.table("content_item"), self.table("creator"), self.table("transcript")
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(select(c.c.content_id.label("aweme_id"), cr.c.nickname, c.c.title,
                c.c.download_status, func.coalesce(t.c.status, "pending").label("transcript_status"), c.c.created_at)
                .outerjoin(cr, cr.c.id == c.c.creator_id).outerjoin(t, t.c.content_item_id == c.c.id)
                .order_by(c.c.id.desc()).limit(limit)).fetchall()]

    def list_transcripts_missing_summary(self, limit=0):
        c, cr, t, a = (self.table(n) for n in ("content_item", "creator", "transcript", "ai_analysis"))
        stmt = select(c.c.content_id.label("aweme_id"), c.c.title, c.c.publish_time.label("create_time"),
            c.c.duration, c.c.media_url.label("video_url"), c.c.cover_url, cr.c.platform_uid.label("blogger_id"),
            cr.c.nickname, t.c.text_content, t.c.text_path).select_from(t).join(c, c.c.id == t.c.content_item_id)
        stmt = stmt.outerjoin(cr, cr.c.id == c.c.creator_id).outerjoin(a, and_(a.c.content_item_id == c.c.id,
            a.c.analysis_type == "summary", a.c.status == "success")).where(t.c.status == "success", a.c.id.is_(None),
            func.coalesce(func.json_extract(c.c.extra, '$.hermes_private'), 0) != 1)
        stmt = stmt.order_by(c.c.publish_time.desc(), c.c.id.desc())
        if limit > 0:
            stmt = stmt.limit(limit)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(stmt).fetchall()]
