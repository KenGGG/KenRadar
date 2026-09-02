"""Durable task control routes.

Registers POST routes for:
    /api/task-pause, /api/task-resume
"""

from __future__ import annotations

from typing import Any

from kenradar.web.responses import error_response, json_response


def _task_run_id(query_params: dict) -> int | None:
    raw = (query_params.get("id") or [None])[0]
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _control_task(
    handler: Any,
    config_path: str,
    query_params: dict,
    action: str,
) -> None:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    run_id = _task_run_id(query_params)
    if run_id is None:
        error_response(handler, "缺少有效的 task_run_id", status=400)
        return

    database = create_database(load_config(config_path))
    try:
        row = database.get_task_run(run_id)
        if not row:
            error_response(handler, f"未找到任务 #{run_id}", status=404)
            return
        if action == "pause":
            database.request_task_pause(run_id, "Web 请求暂停")
            if str(row.get("status") or "") in {"queued", "retry_wait"}:
                database.pause_task_run(run_id, {}, "Web 请求暂停")
        else:
            database.resume_task_run(run_id)
        updated = database.get_task_run(run_id) or row
    except Exception as exc:  # pragma: no cover - defensive
        error_response(handler, f"任务控制失败: {exc}", status=500)
        return
    finally:
        database.close()

    verb = "暂停" if action == "pause" else "继续"
    json_response(
        handler,
        {
            "ok": True,
            "message": f"已请求{verb}任务 #{run_id}",
            "task": {
                "id": run_id,
                "status": str(updated.get("status") or ""),
                "pause_requested": updated.get("pause_requested_at") is not None,
            },
        },
    )


def _handle_task_pause(self: Any, config_path: str, query_params: dict) -> None:
    _control_task(self, config_path, query_params, "pause")


def _handle_task_resume(self: Any, config_path: str, query_params: dict) -> None:
    _control_task(self, config_path, query_params, "resume")


def register(handler_class: type) -> None:
    """Bind task control handlers and register routes."""
    from kenradar.web.router import register_handler

    handler_class._handle_task_pause = _handle_task_pause
    handler_class._handle_task_resume = _handle_task_resume
    register_handler("/api/task-pause", _handle_task_pause, ["config_path", "query_params"])
    register_handler("/api/task-resume", _handle_task_resume, ["config_path", "query_params"])
