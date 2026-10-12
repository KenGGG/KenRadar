"""V2 scan/confirm/execute research records in Core short transactions."""
from datetime import datetime, timezone
from sqlalchemy import select, insert, update, func, and_, or_

def utc_now(seconds=0):
    from .sqlite_database import utc_now as clock
    return clock(seconds)

PENDING = ('pending', 'queued', 'running', 'downloading', 'downloaded', 'transcribing',
           'transcribed_waiting_summary', 'summarizing', 'noting')


class ResearchRepository:
    def __init__(self, db):
        self.db = db

    def get_job(self, job_id):
        t = self.db.table("research_job")
        with self.db.connect() as conn:
            row = conn.execute(select(t).where(t.c.id == job_id)).fetchone()
            return dict(row) if row else None

    def list_jobs(self, *, confirm_status=None, limit=50):
        t = self.db.table("research_job")
        stmt = select(t).order_by(t.c.id.desc()).limit(limit)
        if confirm_status:
            stmt = stmt.where(t.c.confirm_status == confirm_status)
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(stmt).fetchall()]

    def create_scan_job(self, *, platform, source_subscription_id, scan_scope, history_capability,
                        external_content_id=None, creator_name="", requested_by=""):
        t = self.db.table("research_job")
        pid = self.db.ensure_platform(platform)
        with self.db.connect(write=True) as conn:
            row = conn.execute(insert(t).values(platform=platform, platform_id=pid, creator_name=creator_name,
                source_subscription_id=source_subscription_id, scan_scope=scan_scope,
                history_capability=history_capability, external_content_id=external_content_id).returning(t)).fetchone()
            return dict(row)

    def _counts(self, conn, job_id, approved=False, finish=False):
        item, job = self.db.table("research_job_item"), self.db.table("research_job")
        pending = item.c.status.in_(PENDING)
        if approved:
            pending = and_(pending, item.c.review_status == "approved")
        row = conn.execute(select(func.count().label("total"), func.count().filter(pending).label("pending"),
            func.count().filter(item.c.status == "success").label("success"),
            func.count().filter(item.c.status == "failed").label("failed"),
            func.count().filter(or_(item.c.status == "skipped", item.c.review_status == "rejected")).label("skipped"))
            .where(item.c.job_id == job_id)).fetchone()
        counts = dict(row)
        values = {k + "_count": v for k, v in counts.items()}
        values["updated_at"] = utc_now()
        if finish:
            values["status"] = "running" if counts["pending"] else ("partial_failed" if counts["failed"] else "completed")
            if not counts["pending"]:
                values["finished_at"] = utc_now()
        conn.execute(update(job).where(job.c.id == job_id).values(**values))
        return counts

    def add_discovered_item(self, *, job_id, external_content_id, title, url, published_at):
        if published_at is not None:
            if published_at.tzinfo is None:
                raise ValueError("发布时间必须包含时区")
            published_at = published_at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        with self.db.connect(write=True) as conn:
            self.db._upsert("research_job_item", dict(job_id=job_id, aweme_id=str(external_content_id),
                external_content_id=str(external_content_id), title=title, url=url, published_at=published_at,
                updated_at=utc_now()), ("job_id", "aweme_id"), conn=conn)
            counts = self._counts(conn, job_id)
            job = self.db.table("research_job")
            conn.execute(update(job).where(job.c.id == job_id).values(discovered_count=counts["total"]))

    def list_discovered_items(self, job_id):
        t = self.db.table("research_job_item")
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(select(t).where(t.c.job_id == job_id)
                .order_by(t.c.published_at.desc(), t.c.id.desc())).fetchall()]

    def set_item_review(self, job_id, external_content_id, review_status):
        if review_status not in {"approved", "rejected"}:
            raise ValueError("无效 review_status")
        t = self.db.table("research_job_item")
        with self.db.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.job_id == job_id, t.c.external_content_id == str(external_content_id))
                .values(review_status=review_status, updated_at=utc_now()))

    def confirm_job(self, job_id, *, confirmed_by, approve):
        t, item = self.db.table("research_job"), self.db.table("research_job_item")
        with self.db.connect(write=True) as conn:
            count = conn.execute(select(func.count()).where(item.c.job_id == job_id, item.c.review_status == "approved")).fetchone()[0]
            conn.execute(update(t).where(t.c.id == job_id).values(confirm_status="confirmed" if approve else "rejected",
                confirmed_by=confirmed_by, confirmed_at=utc_now(), confirmed_count=count if approve else 0, updated_at=utc_now()))

    def mark_executed(self, job_id):
        t = self.db.table("research_job")
        with self.db.connect(write=True) as conn:
            result = conn.execute(update(t).where(t.c.id == job_id, t.c.confirm_status == "confirmed").values(
                confirm_status="executed", status="running", updated_at=utc_now()))
            if result.rowcount != 1:
                raise ValueError("研究任务尚未确认或已执行")

    def approved_items(self, job_id):
        return [r for r in self.list_discovered_items(job_id) if r["review_status"] == "approved"]

    def claim_next_approved_item(self, job_id):
        t = self.db.table("research_job_item")
        with self.db.connect(write=True) as conn:
            row = conn.execute(select(t).where(t.c.job_id == job_id, t.c.review_status == "approved", t.c.status == "pending")
                .order_by(t.c.published_at.desc(), t.c.id.desc()).limit(1)).fetchone()
            if not row:
                return None
            result = conn.execute(update(t).where(t.c.id == row["id"]).values(status="running", updated_at=utc_now()).returning(t)).fetchone()
            return dict(result)

    def finish_backfill_item(self, job_id, item_id, *, success, error=""):
        t = self.db.table("research_job_item")
        with self.db.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.job_id == job_id, t.c.id == item_id).values(
                status="success" if success else "failed", error_message=error or None, updated_at=utc_now()))
            return self._counts(conn, job_id, approved=True, finish=True)

    def finish_backfill_if_idle(self, job_id):
        with self.db.connect(write=True) as conn:
            return self._counts(conn, job_id, approved=True, finish=True)


class ResearchMethods:
    def control_research_job(self, job_id, action, reason=""):
        job, item, audit = [self.table(name) for name in ("research_job", "research_job_item", "state_transition")]
        allowed = {"cancel": ("pending", "running", "paused"), "pause": ("running",), "resume": ("paused",)}
        states = {"cancel": "cancelled", "pause": "paused", "resume": "running"}
        if action not in allowed:
            raise ValueError("unknown research action")
        with self.connect(write=True) as conn:
            old = conn.execute(select(job.c.status).where(job.c.id == job_id)).fetchone()
            if not old or old[0] not in allowed[action]:
                raise ValueError("研究任务状态已变化")
            values = dict(status=states[action], last_error=reason, updated_at=utc_now())
            if action == "cancel":
                values.update(finished_at=utc_now(), pending_count=0)
                conn.execute(update(item).where(item.c.job_id == job_id, item.c.status.in_(PENDING)).values(status="cancelled", error_message=reason, updated_at=utc_now()))
            conn.execute(update(job).where(job.c.id == job_id, job.c.status == old[0]).values(**values))
            conn.execute(insert(audit).values(object_type="research_job", object_id=str(job_id), old_status=old[0], new_status=states[action], reason=reason, actor="web", created_at=utc_now()))

    def reset_stale_research_items(self, job_id, minutes):
        t = self.table("research_job_item")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.job_id == job_id, t.c.status.in_(PENDING), t.c.updated_at < utc_now(-minutes * 60))
                .values(status="pending", error_message=f"stale_reset: 超过 {minutes} 分钟未更新", updated_at=utc_now()))

    def reset_stale_transcripts(self, minutes):
        t = self.table("transcript")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.status == "running", t.c.updated_at < utc_now(-minutes * 60))
                .values(status="failed", error_message=f"stale_reset: 超过 {minutes} 分钟未更新", updated_at=utc_now()))

    def cancel_other_running_research_jobs(self, keep_job_id, reason):
        job, item = self.table("research_job"), self.table("research_job_item")
        with self.connect(write=True) as conn:
            ids = [r[0] for r in conn.execute(select(job.c.id).where(job.c.id != keep_job_id, job.c.status == "running")).fetchall()]
            conn.execute(update(job).where(job.c.id.in_(ids)).values(status="cancelled", pending_count=0,
                finished_at=utc_now(), updated_at=utc_now(), last_error=reason))
            conn.execute(update(item).where(item.c.job_id.in_(ids), item.c.status.in_(PENDING)).values(
                status="cancelled", error_message=reason, updated_at=utc_now()))
            return ids

    def get_research_report_data(self, job_id):
        item, c, n = self.table("research_job_item"), self.table("content_item"), self.table("content_note")
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(select(item.c.aweme_id, item.c.status, item.c.error_message,
                func.coalesce(c.c.title, item.c.aweme_id).label("title"), c.c.publish_time.label("create_time"),
                n.c.note_path.label("summary_path")).select_from(item).outerjoin(c, c.c.id == item.c.content_item_id)
                .outerjoin(n, and_(n.c.content_item_id == c.c.id, n.c.note_type == "content"))
                .where(item.c.job_id == job_id).order_by(c.c.publish_time.desc(), item.c.id.desc())).fetchall()]

    def create_research_job(self, platform, blogger_id, blogger_name, limit_count, since_time, until_time, push_enabled, force_enabled):
        t, pid = self.table("research_job"), self.ensure_platform(platform)
        with self.connect(write=True) as conn:
            return conn.execute(insert(t).values(platform_id=pid, creator_id=blogger_id, creator_name=blogger_name,
                platform=platform, blogger_id=blogger_id, blogger_name=blogger_name, limit_count=limit_count,
                since_time=since_time or None, until_time=until_time or None,
                push_enabled=push_enabled, force_enabled=force_enabled).returning(t.c.id)).fetchone()[0]

    def update_research_job(self, job_id, **fields):
        t = self.table("research_job")
        allowed = {"status", "blogger_name", "creator_name", "total_count", "pending_count", "success_count",
                   "failed_count", "skipped_count", "started_at", "finished_at", "last_error", "report_path"}
        if set(fields) - allowed:
            raise ValueError("未知研究任务字段")
        if "blogger_name" in fields:
            fields.setdefault("creator_name", fields["blogger_name"])
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == job_id).values(updated_at=utc_now(), **fields))

    def get_research_job(self, job_id):
        return self.research_jobs.get_job(job_id)

    def list_research_jobs(self, limit=100):
        return self.research_jobs.list_jobs(limit=limit)

    def get_research_job_status(self, job_id):
        return (self.get_research_job(job_id) or {}).get("status")

    def upsert_research_job_item(self, job_id, aweme_id, status, error_message=None):
        job = self.get_research_job(job_id)
        cid = self._content_item_id(aweme_id, required=False, platform=job["platform"])
        self._upsert("research_job_item", dict(job_id=job_id, aweme_id=str(aweme_id), content_item_id=cid,
            status=status, error_message=error_message, updated_at=utc_now()), ("job_id", "aweme_id"))

    def list_research_job_items(self, job_id, limit=500):
        i, c, cr, t, a, n = [self.table(name) for name in ("research_job_item", "content_item", "creator", "transcript", "ai_analysis", "content_note")]
        stmt = select(i, c.c.title, cr.c.nickname, n.c.note_path.label("summary_path"), func.coalesce(t.c.status, "pending").label("transcript_status"), func.coalesce(a.c.status, "pending").label("summary_status"))
        stmt = stmt.select_from(i.outerjoin(c, c.c.id == i.c.content_item_id).outerjoin(cr, cr.c.id == c.c.creator_id).outerjoin(t, t.c.content_item_id == c.c.id).outerjoin(a, and_(a.c.content_item_id == c.c.id, a.c.analysis_type == "summary")).outerjoin(n, and_(n.c.content_item_id == c.c.id, n.c.note_type == "content")))
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(stmt.where(i.c.job_id == job_id).order_by(i.c.id.desc()).limit(max(1, min(10000, limit)))).fetchall()]

    def get_research_job_failed_items(self, job_id):
        return [r["aweme_id"] for r in self.list_research_job_items(job_id) if r["status"] == "failed"]

    def set_research_job_error(self, job_id, error_message):
        self.update_research_job(job_id, status="failed", last_error=error_message)

    def get_research_job_content_ids(self, job_id):
        item, c, n = self.table("research_job_item"), self.table("content_item"), self.table("content_note")
        with self.connect() as conn:
            return [r[0] for r in conn.execute(select(c.c.id).distinct().join(item, item.c.content_item_id == c.c.id)
                .join(n, n.c.content_item_id == c.c.id).where(item.c.job_id == job_id, item.c.status.in_(("success", "skipped")),
                    n.c.note_type == "content", n.c.note_path != "").order_by(c.c.id)).fetchall()]

    def get_research_job_publish_data(self, job_id):
        n = self.table("content_note")
        ids = self.get_research_job_content_ids(job_id)
        with self.connect() as conn:
            paths = [r[0] for r in conn.execute(select(n.c.note_path).where(n.c.content_item_id.in_(ids), n.c.note_type == "content")).fetchall()]
        return {"job": self.get_research_job(job_id), "note_paths": paths}

    def cancel_research_job_items(self, job_id):
        t = self.table("research_job_item")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.job_id == job_id, t.c.status.in_(PENDING)).values(
                status="cancelled", error_message="cancelled_by_restart", updated_at=utc_now()))
