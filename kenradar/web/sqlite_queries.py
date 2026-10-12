"""Core queries for the SQLite content contract (no long transcript in lists)."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import Float, case, cast, func, literal, or_, and_, select

from kenradar.core.curation import CurationPolicy
from kenradar.storage import create_database


def runtime_timeline(db):
    j, i, c, cr, t, a = [db.table(n) for n in ("research_job", "research_job_item", "content_item", "creator", "transcript", "ai_analysis")]
    pending = ('pending', 'running', 'downloading', 'downloaded', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting')
    priority = case((i.c.status.in_(("transcribing", "summarizing")), 0), (i.c.status == "noting", 1),
        (i.c.status == "downloading", 2), (i.c.status == "downloaded", 3), else_=4)
    current = select(i.c.id).where(i.c.job_id == j.c.id, i.c.status.in_(pending)).order_by(priority, i.c.updated_at.desc(), i.c.id.desc()).limit(1).correlate(j).scalar_subquery()
    stmt = select(j, i.c.aweme_id, i.c.status.label("item_status"), i.c.error_message.label("item_error"),
        i.c.updated_at.label("item_updated_at"), func.coalesce(c.c.title, i.c.aweme_id, "").label("item_title"),
        func.coalesce(cr.c.nickname, j.c.blogger_name, "").label("current_creator_name")).select_from(j)
    stmt = stmt.outerjoin(i, i.c.id == current).outerjoin(c, c.c.id == i.c.content_item_id).outerjoin(cr, cr.c.id == c.c.creator_id)
    stmt = stmt.where(j.c.status.in_(("running", "paused"))).order_by((j.c.status == "running").desc(), j.c.updated_at.desc(), j.c.id.desc()).limit(1)
    with db.connect() as conn:
        row = conn.execute(stmt).fetchone()
        if not row:
            return None, {}
        ts = func.coalesce(t.c.status == "success", False)
        summarized = func.coalesce(a.c.status == "success", False)
        conditions = dict(download_waiting=and_(i.c.status.in_(("pending", "running", "downloading")), ~ts),
            download_active=i.c.status == "downloading", transcribe_waiting=and_(i.c.status == "downloaded", ~ts),
            transcribe_active=and_(i.c.status == "transcribing", ~ts),
            ai_waiting=and_(ts, ~summarized, ~i.c.status.in_(("summarizing", "noting", "success", "skipped", "failed", "cancelled"))),
            ai_active=i.c.status.in_(("summarizing", "noting")), done=or_(i.c.status.in_(("success", "skipped")), summarized),
            failed=i.c.status.in_(("failed", "cancelled")))
        counts = select(*(func.count().filter(condition).label(name) for name, condition in conditions.items())).select_from(i)
        counts = counts.outerjoin(t, t.c.content_item_id == i.c.content_item_id).outerjoin(a,
            and_(a.c.content_item_id == i.c.content_item_id, a.c.analysis_type == "summary")).where(i.c.job_id == row["id"])
        return dict(row), dict(conn.execute(counts).fetchone())


def failures(config, limit=200):
    from kenradar.web.queries import _stage_still_failed
    db = create_database(config)
    c, tr, a = [db.table(n) for n in ("content_item", "transcript", "ai_analysis")]
    stmt = select(c.c.content_id.label("aweme_id"), c.c.title, c.c.download_status,
        tr.c.status.label("transcript_status"), a.c.status.label("summary_status"),
        c.c.current_error_message, c.c.updated_at, tr.c.error_message.label("transcript_error"),
        a.c.error_message.label("summary_error"), tr.c.updated_at.label("transcript_updated_at"),
        a.c.updated_at.label("summary_updated_at")).select_from(c)
    stmt = stmt.outerjoin(tr, tr.c.content_item_id == c.c.id).outerjoin(a,
        and_(a.c.content_item_id == c.c.id, a.c.analysis_type == "summary"))
    stmt = stmt.where(or_(c.c.download_status == "failed", tr.c.status == "failed", a.c.status == "failed"))
    result = []
    with db.connect() as conn:
        for row in conn.execute(stmt.order_by(c.c.updated_at.desc()).limit(limit)).fetchall():
            item = dict(row)
            for stage, state, error, timestamp in (("download", "download_status", "current_error_message", "updated_at"),
                ("whisper", "transcript_status", "transcript_error", "transcript_updated_at"),
                ("ai", "summary_status", "summary_error", "summary_updated_at")):
                if item[state] == "failed" and _stage_still_failed(stage, item):
                    result.append({**item, "stage": stage, "source": "task", "notified": False,
                        "error_message": item[error] or f"{stage} failed", "failed_at": item[timestamp]})
    return sorted(result, key=lambda r: r["failed_at"] or "", reverse=True)[:limit]


def content_items(config, *, keyword=None, creator_id=None, platform=None, status=None,
                  high_value=None, reviewed=None, date_from=None, date_to=None,
                  sort="priority_desc", cursor=None, limit=30, _raw=False, offset=0):
    from kenradar.web.helpers import _frontend_content
    from kenradar.web.queries import _enrich_aweme_row
    db = create_database(config)
    ci, p, cr, tr, a, n, c, pl = [db.table(name) for name in (
        "content_item", "platform", "creator", "transcript", "ai_analysis", "content_note", "content_curation", "publication_log")]
    policy = CurationPolicy.from_config(config)
    from kenradar.storage.sqlite_score import score_expression
    score = func.coalesce(score_expression(a.c.result_json), 0.0)
    published = func.coalesce(ci.c.publish_time, "")
    filters = dict(keyword=keyword, creator_id=creator_id, platform=platform, status=status,
                   high_value=high_value, reviewed=reviewed, date_from=date_from, date_to=date_to)
    fingerprint = hashlib.sha256(json.dumps({**filters, "sort": sort}, sort_keys=True).encode()).hexdigest()[:16]
    latest_publication = select(pl.c.status).where(pl.c.content_item_id == ci.c.id).order_by(pl.c.id.desc()).limit(1).scalar_subquery()
    stmt = select(ci.c.id.label("content_item_id"), ci.c.content_id, p.c.code.label("platform"), cr.c.nickname,
        ci.c.title, ci.c.publish_time, ci.c.created_at.label("aweme_created_at"), ci.c.duration,
        ci.c.media_url.label("video_url"), ci.c.source_url, ci.c.cover_url, ci.c.download_status, ci.c.local_path,
        func.coalesce(tr.c.status, "pending").label("transcript_status"), tr.c.error_message.label("transcript_error"),
        tr.c.created_at.label("transcript_created_at"), tr.c.updated_at.label("transcript_updated_at"),
        func.coalesce(a.c.status, "pending").label("summary_status"), a.c.error_message.label("summary_error"),
        a.c.updated_at.label("summary_updated_at"), func.coalesce(latest_publication, "pending").label("push_status"),
        a.c.result_text.label("summary_text"), a.c.result_json.label("summary_json"), n.c.note_path.label("summary_path"),
        tr.c.text_path, func.length(tr.c.text_content).label("text_len"), func.coalesce(c.c.favorite, False).label("favorite"),
        func.coalesce(c.c.topic_pool_status, "").label("topic_pool_status"), func.coalesce(c.c.research_status, "").label("research_status"),
        func.coalesce(c.c.user_note, "").label("user_note"), score.label("_score"), published.label("_published")
    ).select_from(ci.join(p, p.c.id == ci.c.platform_id).join(cr, cr.c.id == ci.c.creator_id)
        .outerjoin(tr, tr.c.content_item_id == ci.c.id)
        .outerjoin(a, and_(a.c.content_item_id == ci.c.id, a.c.analysis_type == "summary"))
        .outerjoin(n, and_(n.c.content_item_id == ci.c.id, n.c.note_type == "content"))
        .outerjoin(c, c.c.content_item_id == ci.c.id))
    if keyword:
        from kenradar.storage.sqlite_search import candidate_ids
        candidates = candidate_ids(db, keyword)
        if candidates is not None:
            stmt = stmt.where(ci.c.id.in_(candidates))
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%" + escaped + "%"
        stmt = stmt.where(or_(ci.c.title.like(pattern, escape="\\"), cr.c.nickname.like(pattern, escape="\\"),
            a.c.result_text.like(pattern, escape="\\"), tr.c.text_content.like(pattern, escape="\\")))
    if creator_id is not None:
        stmt = stmt.where(ci.c.creator_id == creator_id)
    if platform:
        stmt = stmt.where(p.c.code == platform)
    if status:
        stmt = stmt.where(ci.c.status == status)
    if high_value is not None:
        stmt = stmt.where((score >= policy.high_value_threshold) if high_value else (score < policy.high_value_threshold))
    if reviewed is not None:
        stmt = stmt.where((ci.c.review_status != "none") if reviewed else (ci.c.review_status == "none"))
    if date_from:
        stmt = stmt.where(published >= date_from)
    if date_to:
        stmt = stmt.where(func.substr(published, 1, 10) <= date_to)
    matched = stmt.subquery()
    with db.connect() as conn:
        total = conn.execute(select(func.count()).select_from(matched)).fetchone()[0]
        source_counts = [dict(row) for row in conn.execute(select(
            matched.c.nickname.label('name'), func.count().label('total_items'),
            func.count().filter(matched.c.summary_path.is_not(None)).label('note_files'),
            func.count().filter(matched.c.summary_status == 'success').label('successful_notes'),
            func.count().filter(matched.c.summary_status == 'failed').label('failed_notes'),
        ).group_by(matched.c.nickname)).fetchall()]
    if sort not in {"priority_desc", "score_desc", "newest"}:
        raise ValueError("无效排序")
    # Existing priority order has a constant first expression; keep score/date/id.
    columns = [published, ci.c.id] if sort == "newest" else [score, published, ci.c.id]
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            values = decoded["values"]
            if decoded["filter"] != fingerprint or len(values) != len(columns):
                raise ValueError("分页条件已变化")
            clauses = [and_(*(col == val for col, val in zip(columns[:i], values[:i])), columns[i] < values[i])
                       for i in range(len(columns))]
            stmt = stmt.where(or_(*clauses))
        except Exception as exc:
            raise ValueError("无效或过期的 cursor") from exc
    limit = min(5000 if _raw else 100, max(1, int(limit)))
    with db.connect() as conn:
        rows = conn.execute(stmt.order_by(*(col.desc() for col in columns)).offset(max(0, offset)).limit(limit + 1)).fetchall()
    more, rows = len(rows) > limit, rows[:limit]
    next_cursor = None
    if more and rows:
        last = rows[-1]
        values = [last["_published"], last["content_item_id"]]
        if sort != "newest":
            values.insert(0, last["_score"])
        next_cursor = base64.urlsafe_b64encode(json.dumps({"filter": fingerprint, "values": values}).encode()).decode().rstrip("=")
    items = []
    for row in rows:
        item = dict(row)
        if isinstance(item["summary_json"], str):
            item["summary_json"] = json.loads(item["summary_json"])
        item["create_time"] = int(datetime.fromisoformat(item["publish_time"].replace("Z", "+00:00")).timestamp()) if item["publish_time"] else 0
        enriched = _enrich_aweme_row(item)
        items.append(enriched if _raw else _frontend_content(config, enriched))
    return {"items": items, "next_cursor": next_cursor, "has_more": more, "total_estimate": total,
            "source_counts": source_counts,
            **policy.frontend_thresholds(), "applied_filters": {k: v for k, v in filters.items() if v is not None}}
