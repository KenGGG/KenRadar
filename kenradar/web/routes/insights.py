"""
Insights route handlers for source metrics API.

Registers GET routes for:
    GET /api/insights/sources
    GET /api/insights/sources/:id/metrics
    GET /api/insights/overview
"""

from __future__ import annotations

from typing import Any

from kenradar.web.responses import json_response


def _handle_insights_sources(self: Any, config_path: str) -> None:
    """List all sources with summary metrics."""
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    config = load_config(config_path)
    db = create_database(config)

    if getattr(config, "database_type", "") == "sqlite":
        from sqlalchemy import func, select
        s, p, m = [db.table(name) for name in ("source_subscription", "platform", "source_daily_metrics")]
        latest = select(m.c.id).where(m.c.source_id == s.c.id).order_by(m.c.metric_date.desc(), m.c.id.desc()).limit(1).correlate(s).scalar_subquery()
        fields = ("total_content", "rated_count", "high_value_count", "push_count", "failed_count")
        stmt = select(s.c.id, s.c.display_name, s.c.source_url, s.c.category, s.c.enabled, s.c.platform_id,
            p.c.code.label("platform"), *(func.coalesce(m.c[key], 0).label(key) for key in fields), m.c.avg_rating, m.c.metric_date)
        with db.connect() as conn:
            rows = conn.execute(stmt.select_from(s.join(p, p.c.id == s.c.platform_id).outerjoin(m, m.c.id == latest)).order_by(s.c.enabled.desc(), s.c.display_name)).fetchall()
        json_response(self, {"items": [dict(row) for row in rows]})
        return

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT
                s.id, s.display_name, s.source_url, s.category, s.enabled,
                s.platform_id, p.code AS platform,
                COALESCE(m.total_content, 0) AS total_content,
                COALESCE(m.rated_count, 0) AS rated_count,
                m.avg_rating,
                COALESCE(m.high_value_count, 0) AS high_value_count,
                COALESCE(m.push_count, 0) AS push_count,
                COALESCE(m.failed_count, 0) AS failed_count,
                m.metric_date
            FROM source_subscription s
            JOIN platform p ON p.id = s.platform_id
            LEFT JOIN LATERAL (
                SELECT * FROM source_daily_metrics
                WHERE source_id = s.id
                ORDER BY metric_date DESC
                LIMIT 1
            ) m ON true
            ORDER BY s.enabled DESC, s.display_name
            """
        ).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        # Format avg_rating
        ar = d.get("avg_rating")
        if ar is not None:
            d["avg_rating"] = round(float(ar), 2)
        result.append(d)

    json_response(self, {"items": result})


def _handle_insights_source_metrics(self: Any, config_path: str, query_params: dict) -> None:
    """Get time-series metrics for a specific source."""
    from datetime import date, timedelta

    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    source_id = int(query_params.get("id", ["0"])[0] or 0)
    try:
        days = int(query_params.get("days", ["30"])[0])
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(365, days))

    config = load_config(config_path)
    db = create_database(config)

    if getattr(config, "database_type", "") == "sqlite":
        from sqlalchemy import select
        s, p, m = [db.table(name) for name in ("source_subscription", "platform", "source_daily_metrics")]
        with db.connect() as conn:
            source = conn.execute(select(s, p.c.code.label("platform")).join(p, p.c.id == s.c.platform_id).where(s.c.id == source_id)).fetchone()
            rows = conn.execute(select(m).where(m.c.source_id == source_id, m.c.metric_date >= (date.today() - timedelta(days=days - 1)).isoformat()).order_by(m.c.metric_date)).fetchall()
        if not source:
            json_response(self, {"error": "source not found"}, status=404)
            return
        metrics = [dict(row) for row in rows]
        summary = {key: sum(row[key] for row in metrics) for key in ("total_content", "rated_count", "high_value_count", "push_count", "failed_count")}
        ratings = [row for row in metrics if row["avg_rating"] is not None and row["rated_count"]]
        weight = sum(row["rated_count"] for row in ratings)
        summary["avg_rating"] = round(sum(row["avg_rating"] * row["rated_count"] for row in ratings) / weight, 2) if weight else None
        json_response(self, {"source": {"id": source["id"], "name": source["display_name"], "platform": source["platform"], "category": source["category"], "enabled": source["enabled"]}, "summary": summary, "metrics": metrics})
        return

    # Get source info
    with db.connect() as conn:
        source = conn.execute(
            """
            SELECT s.*, p.code AS platform
            FROM source_subscription s
            JOIN platform p ON p.id = s.platform_id
            WHERE s.id = %s
            """,
            (source_id,),
        ).fetchone()

    if not source:
        json_response(self, {"error": "source not found"}, status=404)
        return

    # Get metrics time series
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT metric_date, total_content, rated_count, avg_rating,
                   high_value_count, push_count, review_count, failed_count
            FROM source_daily_metrics
            WHERE source_id = %s
              AND metric_date >= %s
            ORDER BY metric_date ASC
            """,
            (source_id, (date.today() - timedelta(days=days - 1)).isoformat()),
        ).fetchall()

    metrics = []
    for row in rows:
        d = dict(row)
        ar = d.get("avg_rating")
        if ar is not None:
            d["avg_rating"] = round(float(ar), 2)
        metrics.append(d)

    # Compute summary over the period
    summary = {
        "total_content": sum(m["total_content"] for m in metrics),
        "rated_count": sum(m["rated_count"] for m in metrics),
        "high_value_count": sum(m["high_value_count"] for m in metrics),
        "push_count": sum(m["push_count"] for m in metrics),
        "failed_count": sum(m["failed_count"] for m in metrics),
        "avg_rating": None,
    }
    rated_ratings = [m["avg_rating"] for m in metrics if m.get("avg_rating") is not None]
    if rated_ratings:
        summary["avg_rating"] = round(sum(rated_ratings) / len(rated_ratings), 2)

    json_response(self, {
        "source": {
            "id": source["id"],
            "name": source["display_name"],
            "platform": source["platform"],
            "category": source.get("category"),
            "enabled": source["enabled"],
        },
        "summary": summary,
        "metrics": metrics,
    })


def _handle_insights_overview(self: Any, config_path: str, query_params: dict) -> None:
    """Global overview of all sources."""
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    try:
        days = int(query_params.get("days", ["30"])[0])
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(365, days))

    from datetime import date, timedelta

    config = load_config(config_path)
    db = create_database(config)

    if getattr(config, "database_type", "") == "sqlite":
        from sqlalchemy import func, select
        m = db.table("source_daily_metrics")
        fields = ("total_content", "rated_count", "high_value_count", "push_count", "failed_count")
        with db.connect() as conn:
            row = conn.execute(select(func.count(func.distinct(m.c.source_id)).label("active_sources"), *(func.coalesce(func.sum(m.c[key]), 0).label(key) for key in fields)).where(m.c.metric_date >= (date.today() - timedelta(days=days - 1)).isoformat())).fetchone()
        json_response(self, {"period_days": days, **dict(row)})
        return

    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT sdm.source_id) AS active_sources,
                SUM(sdm.total_content) AS total_content,
                SUM(sdm.rated_count) AS rated_count,
                SUM(sdm.high_value_count) AS high_value_count,
                SUM(sdm.push_count) AS push_count,
                SUM(sdm.failed_count) AS failed_count
            FROM source_daily_metrics sdm
            WHERE sdm.metric_date >= %s
            """,
            ((date.today() - timedelta(days=days - 1)).isoformat(),),
        ).fetchone()

    json_response(self, {
        "period_days": days,
        "active_sources": int(row["active_sources"] or 0),
        "total_content": int(row["total_content"] or 0),
        "rated_count": int(row["rated_count"] or 0),
        "high_value_count": int(row["high_value_count"] or 0),
        "push_count": int(row["push_count"] or 0),
        "failed_count": int(row["failed_count"] or 0),
    })


def _handle_insights_source_topics(self: Any, config_path: str, query_params: dict) -> None:
    """Return normalized topic distribution for a source and period."""
    from datetime import date, timedelta
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    try:
        source_id = int(query_params.get("id", ["0"])[0] or 0)
        days = max(1, min(365, int(query_params.get("days", ["30"])[0] or 30)))
    except (TypeError, ValueError):
        json_response(self, {"ok": False, "error": "invalid source or days"}, status=400)
        return
    config = load_config(config_path)
    db = create_database(config)
    if config.database_type == "sqlite":
        from sqlalchemy import func, select
        m = db.table("source_topic_metrics")
        with db.connect() as conn:
            rows = conn.execute(select(m.c.topic, func.sum(m.c.content_count).label("content_count")).where(m.c.source_id == source_id, m.c.metric_date >= (date.today() - timedelta(days=days - 1)).isoformat()).group_by(m.c.topic).order_by(func.sum(m.c.content_count).desc(), m.c.topic).limit(50)).fetchall()
        total = sum(row["content_count"] for row in rows)
        json_response(self, {"source_id": source_id, "period_days": days, "topics": [{"topic": row["topic"], "content_count": row["content_count"], "content_ratio": round(row["content_count"] / total, 6) if total else 0} for row in rows]})
        return
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT topic, SUM(content_count) AS content_count
            FROM source_topic_metrics
            WHERE source_id = %s AND metric_date >= %s
            GROUP BY topic ORDER BY content_count DESC, topic LIMIT 50
            """,
            (source_id, date.today() - timedelta(days=days - 1)),
        ).fetchall()
    total = sum(int(row["content_count"] or 0) for row in rows)
    json_response(self, {"source_id": source_id, "period_days": days, "topics": [
        {"topic": row["topic"], "content_count": int(row["content_count"] or 0),
         "content_ratio": round((int(row["content_count"] or 0) / total), 6) if total else 0}
        for row in rows
    ]})


def register(handler_class: type) -> None:
    """Register insights routes via dispatcher."""
    from kenradar.web.router import register_handler

    handler_class._handle_insights_sources = _handle_insights_sources
    handler_class._handle_insights_source_metrics = _handle_insights_source_metrics
    handler_class._handle_insights_overview = _handle_insights_overview
    handler_class._handle_insights_source_topics = _handle_insights_source_topics

    register_handler("/api/insights/sources", _handle_insights_sources, ["config_path"])
    register_handler("/api/insights/sources/metrics", _handle_insights_source_metrics, ["config_path", "query_params"])
    register_handler("/api/insights/overview", _handle_insights_overview, ["config_path", "query_params"])
    register_handler("/api/insights/sources/topics", _handle_insights_source_topics, ["config_path", "query_params"])
