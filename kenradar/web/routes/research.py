"""
Research route handlers — jobs (GET only).

Complex POST handlers (retries, restart, cancel, pause, resume, etc.)
remain inline in app.py do_POST for Phase 0 (behavior-preserving).
"""

from __future__ import annotations

from typing import Any

from kenradar.web.responses import json_response


def _handle_research_jobs_get(self: Any, config_path: str) -> None:
    from kenradar.web.helpers import _frontend_task, _safe_query
    from kenradar.core.config import load_config
    from kenradar.web.queries import load_research_jobs
    config = load_config(config_path)
    json_response(
        self,
        {
            "items": [
                _frontend_task(row)
                for row in _safe_query(lambda: load_research_jobs(config, limit=100), [])
            ]
        },
    )


def _handle_research_job_get(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config
    from kenradar.web.queries import load_research_job, load_research_job_items, load_research_pipeline_stats
    job_id = int(query_params.get("id", ["0"])[0] or 0)
    config = load_config(config_path)
    json_response(
        self,
        {
            "job": load_research_job(config, job_id),
            "items": load_research_job_items(config, job_id, limit=120),
            "pipeline": load_research_pipeline_stats(config, job_id),
        },
    )


def register(handler_class: type) -> None:
    """Register GET-only research routes via dispatcher."""
    from kenradar.web.router import register_handler
    # Bind as methods so they have access to self (the handler instance)
    handler_class._handle_research_jobs_get = _handle_research_jobs_get
    handler_class._handle_research_job_get = _handle_research_job_get
    register_handler("/api/research/jobs", _handle_research_jobs_get, ["config_path"])
    register_handler("/api/research/job", _handle_research_job_get, ["config_path", "query_params"])
