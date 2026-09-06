"""
Dashboard route handlers — bootstrap, status, awemes, library.

Registers GET routes for:
    /api/bootstrap, /api/app-state, /api/status, /api/task-runs, /api/task-run
"""

from __future__ import annotations

from typing import Any

from kenradar.web.queries import (
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


def _handle_archive_files(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config
    from kenradar.web.queries import load_brief_files, load_note_files

    kind = str(query_params.get("kind", [""])[0] or "").strip().lower()
    if kind not in {"notes", "briefs"}:
        json_response(self, {"ok": False, "message": "kind 仅支持 notes 或 briefs"}, status=400)
        return
    config = load_config(config_path)
    items = load_note_files(config) if kind == "notes" else load_brief_files(config)
    json_response(self, {"ok": True, "kind": kind, "items": items})


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


def register(handler_class: type) -> None:
    """Bind dashboard handlers and register routes."""
    from kenradar.web.router import register_handler

    handler_class._handle_bootstrap = _handle_bootstrap
    handler_class._handle_status = _handle_status
    handler_class._handle_archive_files = _handle_archive_files
    handler_class._handle_task_runs = _handle_task_runs
    handler_class._handle_task_run = _handle_task_run

    register_handler("/api/bootstrap", _handle_bootstrap, ["config_path"])
    register_handler("/api/app-state", _handle_bootstrap, ["config_path"])
    register_handler("/api/status", _handle_status, ["config_path"])
    register_handler("/api/archive/files", _handle_archive_files, ["config_path", "query_params"])
    register_handler("/api/task-runs", _handle_task_runs, ["config_path"])
    register_handler("/api/task-run", _handle_task_run, ["config_path", "query_params"])
