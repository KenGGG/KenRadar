"""
Dashboard route handlers — bootstrap, status, awemes, library.

Registers GET routes for:
    /api/bootstrap, /api/app-state, /api/status, /api/awemes,
    /api/task-runs, /api/task-run, /api/aweme/detail, /api/aweme/progress
"""

from __future__ import annotations

from typing import Any

from kenradar.web.queries import (
    load_aweme_detail,
    load_aweme_progress,
    load_aweme_rows,
    load_library_counts,
    load_task_run_detail,
    load_task_runs,
)
from kenradar.web.responses import json_response


def _handle_bootstrap(self: Any, config_path: str) -> None:
    from kenradar.core.config import load_config
    from kenradar.web.helpers import _build_frontend_bootstrap
    json_response(self, _build_frontend_bootstrap(load_config(config_path)))


def _handle_status(self: Any, config_path: str) -> None:
    from kenradar.web.helpers import _frontend_runtime_timeline, _safe_query
    from kenradar.core.config import load_config
    from kenradar.web import task_state
    config = load_config(config_path)
    task_state.sync(config_path)
    json_response(
        self,
        {
            **task_state.current(),
            "runtime_timeline": _safe_query(lambda: _frontend_runtime_timeline(config), {}),
        },
    )


def _handle_awemes(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.web.helpers import _frontend_video, _safe_query, FRONTEND_LIBRARY_LIMIT
    from kenradar.core.config import load_config
    config = load_config(config_path)
    counts = _safe_query(lambda: load_library_counts(config), {})
    page = max(1, int(query_params.get("page", ["1"])[0] or 1))
    page_size = min(200, max(20, int(query_params.get("page_size", ["100"])[0] or 100)))
    rows = load_aweme_rows(config, limit=page_size, offset=(page - 1) * page_size)
    json_response(
        self,
        {
            "items": [_frontend_video(config, row) for row in rows],
            "libraryStats": {**counts, "loaded_items": len(rows), "display_limit": page_size},
            "page": page,
            "page_size": page_size,
        },
    )


def _handle_task_runs(self: Any, config_path: str) -> None:
    from kenradar.core.config import load_config
    json_response(self, {"items": load_task_runs(load_config(config_path), limit=200)})


def _handle_task_run(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config
    run_id = int(query_params.get("id", ["0"])[0] or 0)
    row = load_task_run_detail(load_config(config_path), run_id)
    if not row:
        json_response(self, {"ok": False, "message": "未找到任务"}, status=404)
        return
    json_response(self, {"ok": True, "item": row})


def _handle_aweme_detail(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.web.helpers import _frontend_video, _safe_query
    from kenradar.core.config import load_config
    from kenradar.web.queries import load_failures
    aweme_id = query_params.get("id", [""])[0]
    config = load_config(config_path)
    row = load_aweme_detail(config, aweme_id)
    if not row:
        json_response(self, {"ok": False, "message": "未找到内容"}, status=404)
        return
    failures = {
        str(item.get("aweme_id") or ""): item
        for item in _safe_query(lambda: load_failures(config, limit=500), [])
    }
    json_response(
        self,
        {
            "ok": True,
            "item": _frontend_video(
                config,
                row,
                failures.get(str(row.get("aweme_id") or "")),
                include_content=True,
            ),
        },
    )


def _handle_aweme_progress(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.web.helpers import _merge_manual_task_progress
    from kenradar.core.config import load_config
    from kenradar.web import task_state
    aweme_id = query_params.get("id", [""])[0]
    config = load_config(config_path)
    progress = load_aweme_progress(config, aweme_id)
    if not progress:
        json_response(self, {"ok": False, "message": "未找到内容"}, status=404)
        return
    _merge_manual_task_progress(progress, task_state.current())
    json_response(self, {"ok": True, "progress": progress})


def register(handler_class: type) -> None:
    """Bind dashboard handlers and register routes."""
    from kenradar.web.router import register_handler

    handler_class._handle_bootstrap = _handle_bootstrap
    handler_class._handle_status = _handle_status
    handler_class._handle_awemes = _handle_awemes
    handler_class._handle_task_runs = _handle_task_runs
    handler_class._handle_task_run = _handle_task_run
    handler_class._handle_aweme_detail = _handle_aweme_detail
    handler_class._handle_aweme_progress = _handle_aweme_progress

    register_handler("/api/bootstrap", _handle_bootstrap, ["config_path"])
    register_handler("/api/app-state", _handle_bootstrap, ["config_path"])
    register_handler("/api/status", _handle_status, ["config_path"])
    register_handler("/api/awemes", _handle_awemes, ["config_path", "query_params"])
    register_handler("/api/task-runs", _handle_task_runs, ["config_path"])
    register_handler("/api/task-run", _handle_task_run, ["config_path", "query_params"])
    register_handler("/api/aweme/detail", _handle_aweme_detail, ["config_path", "query_params"])
    register_handler("/api/aweme/progress", _handle_aweme_progress, ["config_path", "query_params"])
