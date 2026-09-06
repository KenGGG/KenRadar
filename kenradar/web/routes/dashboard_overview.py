"""
Dashboard overview route handler.

Registers GET route for:
    /api/dashboard/overview
"""

from __future__ import annotations

from typing import Any

from kenradar.web.queries import load_failures, load_task_runs
from kenradar.web.responses import json_response


def _handle_dashboard_overview(self: Any, config_path: str, query_params: dict) -> None:
    from datetime import date, datetime, timedelta
    import json

    from kenradar.core.config import load_config
    from kenradar.core.curation import CurationPolicy
    from kenradar.web.helpers import (
        _frontend_content_status,
        _frontend_content,
        _safe_query,
    )
    from kenradar.web.queries import (
        load_content_rows,
        load_health,
        load_library_counts,
        load_recent_alerts,
    )

    config = load_config(config_path)
    policy = CurationPolicy.from_config(config)

    # days parameter for trend window (default 30)
    try:
        days = int(query_params.get("days", ["30"])[0])
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(365, days))

    # --- Summary ---
    library_stats = _safe_query(lambda: load_library_counts(config), {})
    rows = _safe_query(lambda: load_content_rows(config, limit=5000), [])
    failures_map = {
        str(item.get("aweme_id") or ""): item
        for item in _safe_query(lambda: load_failures(config, limit=2000), [])
    }

    today = datetime.now().date()
    window_start = today - timedelta(days=days - 1)
    # Single-pass trend buckets keyed by date, oldest -> newest insertion order.
    trend_by_date: dict = {}
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        trend_by_date[d] = {
            "date": d.isoformat(),
            "total": 0,
            "highValue": 0,
            "pushed": 0,
            "confirmed": 0,
        }

    today_count = 0
    high_value_count = 0
    failed_count = 0
    processing_count = 0

    pipeline = {
        "downloading": 0,
        "transcribing": 0,
        "ai_waiting": 0,
        "push_waiting": 0,
        "success": 0,
        "failed": 0,
    }
    failure_reasons: dict[str, int] = {}
    score_buckets = {"0-1": 0, "1-2": 0, "2-3": 0, "3-4": 0, "4-5": 0, "5+": 0}

    for row in rows:
        fid = str(row.get("aweme_id") or "")
        failure = failures_map.get(fid)
        status = _frontend_content_status(row, failure)

        if status == "failed":
            failed_count += 1
        elif status == "processing":
            processing_count += 1

        # Per-row date parsing (once), reused for summary + trend.
        ca = row.get("created_at") or row.get("aweme_created_at") or ""
        dt = None
        if ca:
            try:
                dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                dt = None

        if dt is not None:
            if dt.date() == today:
                today_count += 1
            if window_start <= dt.date() <= today:
                bucket = trend_by_date.get(dt.date())
                if bucket is not None:
                    bucket["total"] += 1
                    if status == "completed":
                        sj = row.get("summary_json") or {}
                        if isinstance(sj, str):
                            try:
                                sj = json.loads(sj)
                            except Exception:
                                sj = {}
                        vs = sj.get("value_score")
                        if vs is not None:
                            try:
                                if policy.is_high_value(vs):
                                    bucket["highValue"] += 1
                            except (TypeError, ValueError):
                                pass
                        ra = sj.get("recommended_action", "")
                        if ra == "push":
                            bucket["pushed"] += 1
                        elif ra == "confirm":
                            bucket["confirmed"] += 1

        # High value (global, completed only) — mirrors the trend highValue logic.
        sj = row.get("summary_json") or {}
        if isinstance(sj, str):
            try:
                sj = json.loads(sj)
            except Exception:
                sj = {}
        vs = sj.get("value_score")
        if vs is not None:
            try:
                score = float(vs)
                if policy.is_high_value(score) and status == "completed":
                    high_value_count += 1
                if score < 1:
                    score_buckets["0-1"] += 1
                elif score < 2:
                    score_buckets["1-2"] += 1
                elif score < 3:
                    score_buckets["2-3"] += 1
                elif score < 4:
                    score_buckets["3-4"] += 1
                elif score <= 5:
                    score_buckets["4-5"] += 1
                else:
                    score_buckets["5+"] += 1
            except (TypeError, ValueError):
                pass

        # Pipeline status
        ds = str(row.get("download_status") or "").lower()
        ts = str(row.get("transcript_status") or "").lower()
        ss = str(row.get("summary_status") or "").lower()

        if ss == "success":
            pipeline["success"] += 1
        elif ss == "failed" or ts == "failed" or ds == "failed":
            pipeline["failed"] += 1
        elif ts in ("running", "processing") or ds in ("downloading", "done"):
            if ts in ("running", "processing"):
                pipeline["transcribing"] += 1
            else:
                pipeline["downloading"] += 1
        elif ss in ("running", "processing"):
            pipeline["ai_waiting"] += 1
        elif ds in ("pending", "queued"):
            pipeline["downloading"] += 1
        elif ts in ("pending", "queued"):
            pipeline["transcribing"] += 1
        elif ss in ("pending", "queued"):
            pipeline["ai_waiting"] += 1

        # Failure reasons
        if failure:
            step = str(failure.get("stage") or "unknown")
            failure_reasons[step] = failure_reasons.get(step, 0) + 1

    summary = {
        "today_new": today_count,
        "high_value_pending": high_value_count,
        "failed": failed_count,
        "processing": processing_count,
    }

    daily_trend = list(trend_by_date.values())
    score_distribution = [{"bucket": k, "count": v} for k, v in score_buckets.items()]

    result = {
        "summary": summary,
        "dailyTrend": daily_trend,
        "pipeline": pipeline,
        "failureReasons": [
            {"stage": k, "count": v} for k, v in sorted(failure_reasons.items(), key=lambda x: -x[1])
        ],
        "scoreDistribution": score_distribution,
        "curationThresholds": policy.frontend_thresholds(),
        "highValueThreshold": policy.frontend_thresholds()["high_value_threshold"],
    }

    json_response(self, result)


def register(handler_class: type) -> None:
    """Bind dashboard overview handler and register route."""
    from kenradar.web.router import register_handler

    handler_class._handle_dashboard_overview = _handle_dashboard_overview
    register_handler(
        "/api/dashboard/overview",
        _handle_dashboard_overview,
        ["config_path", "query_params"],
    )
