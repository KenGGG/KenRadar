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
    from kenradar.web.helpers import (
        _frontend_content_status,
        _frontend_video,
        _safe_query,
    )
    from kenradar.web.queries import (
        HIGH_VALUE_THRESHOLD,
        load_aweme_rows,
        load_health,
        load_library_counts,
        load_recent_alerts,
    )

    config = load_config(config_path)

    # days parameter for trend window (default 30)
    try:
        days = int(query_params.get("days", ["30"])[0])
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(365, days))

    # --- Summary ---
    library_stats = _safe_query(lambda: load_library_counts(config), {})
    rows = _safe_query(lambda: load_aweme_rows(config, limit=5000), [])
    failures_map = {
        str(item.get("aweme_id") or ""): item
        for item in _safe_query(lambda: load_failures(config, limit=2000), [])
    }

    today_count = 0
    high_value_count = 0
    failed_count = 0
    processing_count = 0
    pushed_count = 0
    confirmed_count = 0

    for row in rows:
        fid = str(row.get("aweme_id") or "")
        failure = failures_map.get(fid)
        status = _frontend_content_status(row, failure)

        if status == "failed":
            failed_count += 1
        elif status == "processing":
            processing_count += 1

        # Check if published today (using created_at date)
        ca = row.get("created_at") or row.get("aweme_created_at") or ""
        if ca:
            try:
                dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
                if dt.date() == datetime.now().date():
                    today_count += 1
            except (ValueError, TypeError):
                pass

        # High value check (value_score >= 3.5 → rating >= 7)
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
                if score >= HIGH_VALUE_THRESHOLD and status == "completed":
                    high_value_count += 1
            except (TypeError, ValueError):
                pass

        # Pushed / confirmed from recommended_action
        ra = sj.get("recommended_action", "")
        if ra == "push":
            pushed_count += 1
        elif ra == "confirm":
            confirmed_count += 1

    summary = {
        "today_new": today_count,
        "high_value_pending": high_value_count,
        "failed": failed_count,
        "processing": processing_count,
    }

    # --- Pipeline status ---
    pipeline = {
        "downloading": 0,
        "transcribing": 0,
        "ai_waiting": 0,
        "push_waiting": 0,
        "success": 0,
        "failed": 0,
    }
    for row in rows:
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

    # --- Daily trend (last N days) ---

    daily_trend = []
    today = datetime.now().date()
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        d_str = d.isoformat()
        d_count = 0
        d_hv = 0
        d_pushed = 0
        d_confirmed = 0

        for row in rows:
            ca = row.get("created_at") or row.get("aweme_created_at") or ""
            if ca:
                try:
                    dt = datetime.fromisoformat(str(ca).replace("Z", "+00:00"))
                    if dt.date() == d:
                        d_count += 1
                        fid = str(row.get("aweme_id") or "")
                        failure = failures_map.get(fid)
                        if _frontend_content_status(row, failure) == "completed":
                            sj = row.get("summary_json") or {}
                            if isinstance(sj, str):
                                try:
                                    sj = json.loads(sj)
                                except Exception:
                                    pass
                            vs = sj.get("value_score")
                            if vs is not None:
                                try:
                                    if float(vs) >= HIGH_VALUE_THRESHOLD:
                                        d_hv += 1
                                except (TypeError, ValueError):
                                    pass
                            ra = sj.get("recommended_action", "")
                            if ra == "push":
                                d_pushed += 1
                            elif ra == "confirm":
                                d_confirmed += 1
                except (ValueError, TypeError):
                    pass

        daily_trend.append({
            "date": d_str,
            "total": d_count,
            "highValue": d_hv,
            "pushed": d_pushed,
            "confirmed": d_confirmed,
        })

    # --- Failure reasons ---
    failure_reasons: dict[str, int] = {}
    for row in rows:
        fid = str(row.get("aweme_id") or "")
        failure = failures_map.get(fid)
        if failure:
            step = str(failure.get("stage") or "unknown")
            failure_reasons[step] = failure_reasons.get(step, 0) + 1

    # --- Score distribution ---
    score_buckets = {"0-1": 0, "1-2": 0, "2-3": 0, "3-4": 0, "4-5": 0, "5+": 0}
    for row in rows:
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

    score_distribution = [
        {"bucket": k, "count": v} for k, v in score_buckets.items()
    ]

    result = {
        "summary": summary,
        "dailyTrend": daily_trend,
        "pipeline": pipeline,
        "failureReasons": [
            {"stage": k, "count": v} for k, v in sorted(failure_reasons.items(), key=lambda x: -x[1])
        ],
        "scoreDistribution": score_distribution,
        "highValueThreshold": round(HIGH_VALUE_THRESHOLD * 2, 1),
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
