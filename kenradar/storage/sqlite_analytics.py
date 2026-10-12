"""Deterministic SQLite source metrics; no model or publication calls."""
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import and_, case, delete, func, or_, select
from .sqlite_score import score_expression
from .sqlite_database import utc_now


def aggregate(db, config, days=7, dry_run=False):
    from kenradar.core.curation import CurationPolicy
    policy = CurationPolicy.from_config(config)
    tz = ZoneInfo(str(config.get("app.timezone", "Asia/Shanghai")))
    today = datetime.now(tz).date()
    summary = dict(total_days=0, sources_processed=0, rows_upserted=0, rows_skipped_no_mapping=0, errors=0)
    s, cr, ci, ai, metrics, topics = [db.table(name) for name in ("source_subscription", "creator", "content_item", "ai_analysis", "source_daily_metrics", "source_topic_metrics")]
    with db.connect() as conn:
        sources = conn.execute(select(s).where(s.c.enabled == 1)).fetchall()
    for source in sources:
        with db.connect() as conn:
            mappings = [cr.c.platform_uid == source["source_key"]]
            for url in (source["source_url"], source["feed_url"]):
                if url:
                    mappings.append(cr.c.profile_url == url)
            creators = [row[0] for row in conn.execute(select(cr.c.id).where(cr.c.platform_id == source["platform_id"], or_(*mappings))).fetchall()]
        if not creators:
            summary["rows_skipped_no_mapping"] += days
            continue
        for offset in range(max(1, min(365, int(days)))):
            day = today - timedelta(days=offset)
            begin = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
            end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
            score = score_expression(ai.c.result_json)
            action = func.json_extract(ai.c.result_json, "$.recommended_action")
            joined = ci.outerjoin(ai, and_(ai.c.content_item_id == ci.c.id, ai.c.analysis_type == "summary"))
            filters = (ci.c.creator_id.in_(creators), ci.c.publish_time >= begin, ci.c.publish_time < end)
            query = select(func.count().label("total_content"), func.count(score).label("rated_count"), func.avg(score).label("avg_rating"),
                func.count().filter(score >= policy.high_value_threshold).label("high_value_count"), func.count().filter(action == "push").label("push_count"),
                func.count().filter(action == "confirm").label("review_count"), func.count().filter(or_(ci.c.download_status == "failed", ai.c.status == "failed")).label("failed_count")).select_from(joined).where(*filters)
            with db.connect(write=not dry_run) as conn:
                values = dict(conn.execute(query).fetchone())
                analyses = conn.execute(select(ai.c.result_json).select_from(joined).where(*filters)).fetchall()
                labels = Counter()
                for row in analyses:
                    value = row[0] or {}
                    if not isinstance(value, dict):
                        continue
                    items = value.get("topics") or value.get("tags") or []
                    if isinstance(items, str):
                        items = [items]
                    if isinstance(items, list):
                        labels.update({str(item).strip()[:128] for item in items if str(item).strip()})
                if not dry_run:
                    db._upsert("source_daily_metrics", {**values, "source_id": source["id"], "metric_date": day.isoformat(), "calculation_version": "sqlite-v1", "updated_at": utc_now()}, ("source_id", "metric_date"), conn=conn)
                    conn.execute(delete(topics).where(topics.c.source_id == source["id"], topics.c.metric_date == day.isoformat(), topics.c.taxonomy_version == "v1"))
                    for topic, count in labels.items():
                        db._upsert("source_topic_metrics", dict(source_id=source["id"], metric_date=day.isoformat(), topic=topic, content_count=count, content_ratio=count / max(1, len(analyses)), taxonomy_version="v1", model_name="existing-ai-labels", updated_at=utc_now()), ("source_id", "metric_date", "topic", "taxonomy_version"), conn=conn)
            summary["total_days"] += 1
            summary["sources_processed"] += 1
            summary["rows_upserted"] += 1
    return summary
