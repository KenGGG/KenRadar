from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import mimetypes
import re
import subprocess
import threading
from copy import deepcopy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from kenradar.core.config import AppConfig, load_config, save_config
from kenradar.notification.alert import AlertManager
from kenradar.storage import create_database
from kenradar.web.queries import (
    find_aweme_id_from_note_path,
    generate_weekly_brief,
    load_aweme_detail,
    load_aweme_progress,
    load_aweme_rows,
    load_bloggers,
    load_failures,
    load_health,
    load_library_counts,
    load_log_lines,
    load_brief_files,
    load_note_files,
    load_push_logs,
    load_recent_alerts,
    load_research_job,
    load_research_job_items,
    load_research_jobs,
    load_research_pipeline_stats,
    load_source_quality,
    read_text,
    safe_data_path,
)
from kenradar.web.templates import (
    render_archive_briefs_page,
    render_archive_notes_page,
    render_archive_page,
    render_archive_research_page,
    render_aweme,
    render_config_page,
    render_dashboard,
    render_error,
    render_file,
    render_monitor_alerts_page,
    render_monitor_pushes_page,
    render_monitor_runtime_page,
    render_monitor_status_page,
    render_operations_page,
    render_operations_retry_page,
    render_research_job_page,
    render_sources_page,
)

logger = logging.getLogger(__name__)

FRONTEND_LIBRARY_LIMIT = 5000

_TASK_LOCK = threading.Lock()
_TASK_QUEUE_LOCK = threading.Lock()
_TASK_QUEUE: list[dict[str, Any]] = []
_TASK_QUEUE_WORKER_RUNNING = False
_TASK_STATE: dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "status": "idle",
    "message": "空闲",
    "stats": None,
    "progress": None,
    "queue": [],
}
_TASK_LOCK_TOKEN = 0
_SCHEDULER_STARTED = False


def _public_task_queue() -> list[dict[str, Any]]:
    with _TASK_QUEUE_LOCK:
        return [
            {
                "position": index,
                "task_id": str(entry.get("task_id") or ""),
                "message": str(entry.get("message") or ""),
                "queued_at": str(entry.get("queued_at") or ""),
            }
            for index, entry in enumerate(_TASK_QUEUE, start=1)
        ]


def _sync_task_queue_state() -> None:
    _TASK_STATE["queue"] = _public_task_queue()


def _enqueue_background_task(config_path: str, task_id: str, task_factory: Any, message: str) -> int:
    global _TASK_QUEUE_WORKER_RUNNING

    entry = {
        "config_path": config_path,
        "task_id": task_id,
        "task_factory": task_factory,
        "message": message,
        "queued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with _TASK_QUEUE_LOCK:
        _TASK_QUEUE.append(entry)
        position = len(_TASK_QUEUE)
        should_start_worker = not _TASK_QUEUE_WORKER_RUNNING
        if should_start_worker:
            _TASK_QUEUE_WORKER_RUNNING = True
    _sync_task_queue_state()
    if should_start_worker:
        threading.Thread(target=_task_queue_loop, daemon=True).start()
    return position


def _task_queue_loop() -> None:
    global _TASK_QUEUE_WORKER_RUNNING

    while True:
        with _TASK_QUEUE_LOCK:
            if not _TASK_QUEUE:
                _TASK_QUEUE_WORKER_RUNNING = False
                break
        _TASK_LOCK.acquire()
        with _TASK_QUEUE_LOCK:
            if not _TASK_QUEUE:
                _TASK_LOCK.release()
                _TASK_QUEUE_WORKER_RUNNING = False
                break
            entry = _TASK_QUEUE.pop(0)
        _sync_task_queue_state()
        _start_locked_task_thread(entry, release_lock=True)


def _start_locked_task_thread(entry: dict[str, Any], *, release_lock: bool) -> None:
    global _TASK_LOCK_TOKEN

    _TASK_LOCK_TOKEN += 1
    lock_token = _TASK_LOCK_TOKEN

    def task_is_current() -> bool:
        return lock_token == _TASK_LOCK_TOKEN

    def worker() -> None:
        from kenradar.core.workflow import Workflow

        try:
            config = load_config(str(entry["config_path"]))
            if task_is_current():
                _sync_task_queue_state()
                _TASK_STATE.update(
                    {
                        "running": True,
                        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "finished_at": None,
                        "status": str(entry["task_id"]),
                        "message": str(entry["message"]),
                        "stats": None,
                    }
                )
            logger.info("Manual %s task started from web", entry["task_id"])
            stats = asyncio.run(entry["task_factory"](Workflow(config)))
            if task_is_current():
                _sync_task_queue_state()
                _TASK_STATE.update(
                    {
                        "running": False,
                        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "success",
                        "message": "任务完成",
                        "stats": stats,
                    }
                )
            logger.info("Manual %s task finished: %s", entry["task_id"], stats)
        except Exception as exc:
            try:
                config = load_config(str(entry["config_path"]))
                AlertManager(config, create_database(config)).error(
                    "web_task",
                    str(exc),
                    title=str(entry.get("message") or entry.get("task_id") or "后台任务"),
                    context={"task_id": entry.get("task_id")},
                )
            except Exception:
                logger.exception("Manual %s task failed and alert logging also failed", entry.get("task_id"))
            if task_is_current():
                _sync_task_queue_state()
                _TASK_STATE.update(
                    {
                        "running": False,
                        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "failed",
                        "message": str(exc),
                    }
                )
            logger.exception("Manual %s task failed", entry.get("task_id"))
        finally:
            if release_lock and task_is_current():
                try:
                    _TASK_LOCK.release()
                except RuntimeError:
                    logger.warning("Task lock was already released for %s", entry.get("task_id"))
            elif not task_is_current():
                logger.info("Manual %s task was superseded; leaving current task lock untouched", entry.get("task_id"))

    threading.Thread(target=worker, daemon=True).start()


def run_web(config_path: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    from kenradar.storage import create_database

    create_database(load_config(config_path)).initialize()
    _start_embedded_scheduler(config_path)

    class KenRadarHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if not self._authorized(config_path):
                    return
                if parsed.path.startswith("/assets/"):
                    self._send_frontend_asset(parsed.path)
                    return
                if parsed.path in {"/api/bootstrap", "/api/app-state"}:
                    self._send_json(_build_frontend_bootstrap(load_config(config_path)))
                    return
                if parsed.path == "/":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_dashboard(load_config(config_path), _TASK_STATE))
                    return
                if parsed.path == "/config":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_config_page(load_config(config_path)))
                    return
                if parsed.path == "/sources":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_sources_page(load_config(config_path)))
                    return
                if parsed.path == "/run":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_monitor_status_page(load_config(config_path)))
                    return
                if parsed.path == "/operations":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_operations_page(load_config(config_path)))
                    return
                if parsed.path == "/operations/retry":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_operations_retry_page(load_config(config_path)))
                    return
                if parsed.path == "/operations/pushes":
                    self.send_response(302)
                    self.send_header("Location", "/logs/pushes")
                    self.end_headers()
                    return
                if parsed.path == "/archive":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_archive_page(load_config(config_path)))
                    return
                if parsed.path == "/archive/research":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_archive_research_page(load_config(config_path)))
                    return
                if parsed.path == "/archive/notes":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_archive_notes_page(load_config(config_path)))
                    return
                if parsed.path == "/archive/briefs":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_archive_briefs_page(load_config(config_path)))
                    return
                if parsed.path == "/items":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_operations_page(load_config(config_path)))
                    return
                if parsed.path == "/notes":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_archive_notes_page(load_config(config_path)))
                    return
                if parsed.path == "/briefs":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_archive_briefs_page(load_config(config_path)))
                    return
                if parsed.path == "/pushes":
                    self.send_response(302)
                    self.send_header("Location", "/logs/pushes")
                    self.end_headers()
                    return
                if parsed.path == "/research":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_archive_research_page(load_config(config_path)))
                    return
                if parsed.path == "/research/jobs":
                    if self._send_frontend_app():
                        return
                    query = parse_qs(parsed.query)
                    self._send_html(render_research_job_page(load_config(config_path), int(query.get("id", ["0"])[0] or 0)))
                    return
                if parsed.path == "/failures":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_operations_retry_page(load_config(config_path)))
                    return
                if parsed.path in {"/logs", "/logs/status"}:
                    if self._send_frontend_app():
                        return
                    self._send_html(render_monitor_status_page(load_config(config_path)))
                    return
                if parsed.path == "/logs/pushes":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_monitor_pushes_page(load_config(config_path)))
                    return
                if parsed.path == "/logs/alerts":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_monitor_alerts_page(load_config(config_path)))
                    return
                if parsed.path == "/logs/runtime":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_monitor_runtime_page(load_config(config_path)))
                    return
                if parsed.path == "/aweme":
                    if self._send_frontend_app():
                        return
                    query = parse_qs(parsed.query)
                    self._send_html(render_aweme(load_config(config_path), query.get("id", [""])[0]))
                    return
                if parsed.path == "/file":
                    query = parse_qs(parsed.query)
                    rel_path = query.get("path", [""])[0]
                    config = load_config(config_path)
                    try:
                        path = safe_data_path(config, rel_path)
                        aweme_id = find_aweme_id_from_note_path(config, path)
                        if aweme_id:
                            self.send_response(302)
                            self.send_header("Location", f"/aweme?id={aweme_id}")
                            self.end_headers()
                            return
                    except (FileNotFoundError, ValueError):
                        pass
                    self._send_html(render_file(config, rel_path))
                    return
                if parsed.path == "/api/status":
                    self._send_json(_TASK_STATE)
                    return
                if parsed.path == "/api/awemes":
                    config = load_config(config_path)
                    counts = _safe_query(lambda: load_library_counts(config), {})
                    limit = min(FRONTEND_LIBRARY_LIMIT, max(100, int(counts.get("total_items") or 0)))
                    self._send_json({"items": load_aweme_rows(config, limit=limit), "libraryStats": counts})
                    return
                if parsed.path == "/api/aweme/detail":
                    query = parse_qs(parsed.query)
                    aweme_id = query.get("id", [""])[0]
                    config = load_config(config_path)
                    row = load_aweme_detail(config, aweme_id)
                    if not row:
                        self._send_json({"ok": False, "message": "未找到内容"}, status=404)
                        return
                    failures = {
                        str(item.get("aweme_id") or ""): item
                        for item in _safe_query(lambda: load_failures(config, limit=500), [])
                    }
                    self._send_json(
                        {
                            "ok": True,
                            "item": _frontend_video(config, row, failures.get(str(row.get("aweme_id") or ""))),
                        }
                    )
                    return
                if parsed.path == "/api/aweme/progress":
                    query = parse_qs(parsed.query)
                    aweme_id = query.get("id", [""])[0]
                    config = load_config(config_path)
                    progress = load_aweme_progress(config, aweme_id)
                    if not progress:
                        self._send_json({"ok": False, "message": "未找到内容"}, status=404)
                        return
                    _merge_manual_task_progress(progress, deepcopy(_TASK_STATE))
                    self._send_json({"ok": True, "progress": progress})
                    return
                if parsed.path == "/api/research/job":
                    query = parse_qs(parsed.query)
                    job_id = int(query.get("id", ["0"])[0] or 0)
                    config = load_config(config_path)
                    self._send_json(
                        {
                            "job": load_research_job(config, job_id),
                            "items": load_research_job_items(config, job_id, limit=120),
                            "pipeline": load_research_pipeline_stats(config, job_id),
                        }
                    )
                    return
                self.send_response(404)
                self.end_headers()
            except Exception as exc:
                logger.exception("Web GET failed: path=%s", self.path)
                self._send_html(render_error(str(exc)), status=500)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._authorized(config_path):
                return
            if parsed.path == "/api/run-once":
                self._start_background_task(config_path, "run_once", lambda workflow: workflow.run_once(push=True), "正在执行检测、下载、转录和推送")
                return
            if parsed.path == "/api/test-latest":
                self._start_background_task(config_path, "test_latest", lambda workflow: workflow.test_latest(limit_per_target=1, push=True), "正在测试每个博主最新内容")
                return
            if parsed.path == "/api/retry-summary":
                query = parse_qs(parsed.query)
                self._start_retry_summary(config_path, query.get("id", [""])[0])
                return
            if parsed.path == "/api/retry-download":
                query = parse_qs(parsed.query)
                self._start_retry_stage(config_path, query.get("id", [""])[0], "download")
                return
            if parsed.path == "/api/retry-transcribe":
                query = parse_qs(parsed.query)
                self._start_retry_stage(config_path, query.get("id", [""])[0], "transcribe")
                return
            if parsed.path == "/api/retry-full":
                query = parse_qs(parsed.query)
                self._start_retry_stage(config_path, query.get("id", [""])[0], "auto")
                return
            if parsed.path == "/api/retry-batch":
                self._start_retry_batch(config_path, self._read_form())
                return
            if parsed.path == "/api/retry-research-failed":
                query = parse_qs(parsed.query)
                self._start_retry_research_failed(config_path, int(query.get("id", ["0"])[0] or 0))
                return
            if parsed.path == "/api/research/restart":
                query = parse_qs(parsed.query)
                self._start_restart_research_job(config_path, int(query.get("id", ["0"])[0] or 0))
                return
            if parsed.path == "/api/repush-aweme":
                query = parse_qs(parsed.query)
                self._repush_aweme(config_path, query.get("id", [""])[0])
                return
            if parsed.path == "/api/curation":
                self._update_curation(config_path, self._read_form())
                return
            if parsed.path == "/api/favorite":
                query = parse_qs(parsed.query)
                self._toggle_favorite(config_path, query.get("id", [""])[0])
                return
            if parsed.path == "/api/generate-weekly":
                self._generate_weekly_brief(config_path)
                return
            if parsed.path == "/api/test-feishu-card":
                self._test_feishu(config_path, force_card=True)
                return
            if parsed.path == "/api/test-feishu-text":
                self._test_feishu(config_path, force_card=False)
                return
            if parsed.path == "/api/research-blogger":
                self._start_research_blogger(config_path, self._read_form())
                return
            if parsed.path == "/api/research-video":
                self._start_research_video(config_path, self._read_form())
                return
            if parsed.path == "/api/research/cancel":
                query = parse_qs(parsed.query)
                self._cancel_research_job(config_path, int(query.get("id", ["0"])[0] or 0))
                return
            if parsed.path == "/api/research/pause":
                query = parse_qs(parsed.query)
                self._pause_research_job(config_path, int(query.get("id", ["0"])[0] or 0))
                return
            if parsed.path == "/api/research/resume":
                query = parse_qs(parsed.query)
                self._resume_research_job(config_path, int(query.get("id", ["0"])[0] or 0))
                return
            if parsed.path == "/api/restart-web":
                self._restart_web(config_path)
                return
            if parsed.path == "/api/config":
                self._save_frontend_config(config_path, self._read_json())
                return
            if parsed.path == "/api/source/toggle":
                self._toggle_source(config_path, self._read_json())
                return
            if parsed.path == "/api/source/delete":
                self._delete_source_json(config_path, self._read_json())
                return
            if parsed.path == "/api/source/add":
                self._add_source_json(config_path, self._read_json())
                return
            if parsed.path == "/api/source/category":
                self._update_source_category(config_path, self._read_json())
                return
            if parsed.path == "/api/source/categories":
                self._update_source_categories(config_path, self._read_json())
                return
            if parsed.path == "/sources/add":
                self._add_source(config_path, self._read_form())
                return
            if parsed.path == "/sources/promote":
                self._promote_source(config_path, self._read_form())
                return
            if parsed.path == "/sources/update":
                self._update_source(config_path, self._read_form())
                return
            if parsed.path == "/sources/delete":
                self._delete_source(config_path, self._read_form())
                return
            if parsed.path != "/config":
                self.send_response(404)
                self.end_headers()
                return

            form = self._read_form()
            try:
                config = load_config(config_path)
                save_config(config, update_config_from_form(config, form))
                self.send_response(303)
                self.send_header("Location", "/config")
                self.end_headers()
            except Exception as exc:
                logger.exception("Config update failed")
                self._send_html(render_error(str(exc)), status=400)

        def _read_form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length).decode("utf-8") if length else ""
            return parse_qs(body, keep_blank_values=True)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(length).decode("utf-8") if length else ""
            if not body.strip():
                return {}
            data = json.loads(body)
            return data if isinstance(data, dict) else {}

        def _send_html(self, body: str, status: int = 200) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, data: Any, status: int = 200) -> None:
            payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_frontend_app(self) -> bool:
            index_path = _frontend_dist_dir() / "index.html"
            if not index_path.exists():
                return False
            payload = index_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return True

        def _send_frontend_asset(self, request_path: str) -> None:
            rel = request_path.lstrip("/")
            asset_path = (_frontend_dist_dir() / rel).resolve()
            dist_dir = _frontend_dist_dir().resolve()
            if dist_dir not in asset_path.parents or not asset_path.exists() or not asset_path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            payload = asset_path.read_bytes()
            content_type = mimetypes.guess_type(str(asset_path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _authorized(self, config_path: str) -> bool:
            password = str(load_config(config_path).get("app.web_password", "") or "")
            if not password:
                return True
            header = self.headers.get("Authorization", "")
            if header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
                except Exception:
                    decoded = ""
                _user, _sep, candidate = decoded.partition(":")
                if hmac.compare_digest(candidate, password):
                    return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="KenRadar"')
            self.end_headers()
            return False

        def _start_background_task(self, config_path: str, task_id: str, task_factory: Any, message: str, *, force: bool = False) -> None:
            if not _TASK_LOCK.acquire(blocking=False):
                if not force:
                    position = _enqueue_background_task(config_path, task_id, task_factory, message)
                    self._send_json(
                        {
                            "ok": True,
                            "queued": True,
                            "task_id": task_id,
                            "queue_position": position,
                            "message": f"已有任务正在运行，已加入队列（第 {position} 位）",
                            "state": _TASK_STATE,
                        },
                        status=202,
                    )
                    return
                logger.warning("Force-starting %s while previous task lock is still held", task_id)
                try:
                    _TASK_LOCK.release()
                except RuntimeError:
                    pass
                if not _TASK_LOCK.acquire(blocking=False):
                    self._send_json({"ok": False, "message": "已有任务正在运行，无法接管任务锁"}, status=409)
                    return

            _start_locked_task_thread(
                {
                    "config_path": config_path,
                    "task_id": task_id,
                    "task_factory": task_factory,
                    "message": message,
                    "queued_at": "",
                },
                release_lock=True,
            )
            self._send_json({"ok": True, "task_id": task_id, "message": "任务已启动", "state": _TASK_STATE}, status=202)

        def _start_retry_summary(self, config_path: str, aweme_id: str) -> None:
            if not aweme_id:
                self._send_json({"ok": False, "message": "缺少 aweme_id"}, status=400)
                return

            async def task(workflow: Any) -> dict[str, Any]:
                return await workflow.retry_summary(aweme_id)

            self._start_background_task(config_path, f"retry-summary-{aweme_id}", task, "正在重试 AI 整理和笔记生成")

        def _start_retry_stage(self, config_path: str, aweme_id: str, retry_from: str) -> None:
            if not aweme_id:
                self._send_json({"ok": False, "message": "缺少 aweme_id"}, status=400)
                return

            async def task(workflow: Any) -> dict[str, Any]:
                if retry_from == "download":
                    return await workflow.retry_download(aweme_id)
                if retry_from == "transcribe":
                    return await workflow.retry_transcribe(aweme_id)
                return await workflow.retry_full_pipeline(aweme_id)

            labels = {"download": "正在从下载阶段重试", "transcribe": "正在从转录阶段重试", "auto": "正在执行全流程智能重试"}
            self._start_background_task(config_path, f"retry-{retry_from}-{aweme_id}", task, labels.get(retry_from, "正在重试"))

        def _start_retry_batch(self, config_path: str, form: dict[str, list[str]]) -> None:
            raw_ids = ",".join(form.get("aweme_ids", []))
            aweme_ids = [item.strip() for item in raw_ids.replace("\n", ",").split(",") if item.strip()]
            retry_from = _field(form, "retry_from", "auto").strip() or "auto"
            if not aweme_ids:
                self._send_json({"ok": False, "message": "请选择要重试的内容"}, status=400)
                return

            async def task(workflow: Any) -> dict[str, Any]:
                def on_progress(current: int, total: int, aweme_id: str, stage: str, message: str) -> None:
                    _TASK_STATE["progress"] = {
                        "total": total,
                        "current": current,
                        "aweme_id": aweme_id,
                        "stage": stage,
                        "message": message,
                    }

                return await workflow.retry_batch(aweme_ids, retry_from=retry_from, on_progress=on_progress)

            self._start_background_task(config_path, f"retry-batch-{len(aweme_ids)}", task, f"正在批量重试 {len(aweme_ids)} 条内容")

        def _start_retry_research_failed(self, config_path: str, job_id: int) -> None:
            if job_id <= 0:
                self._send_json({"ok": False, "message": "缺少 job_id"}, status=400)
                return

            async def task(workflow: Any) -> dict[str, Any]:
                return await workflow.retry_research_failed(job_id)

            self._start_background_task(config_path, f"retry-research-failed-{job_id}", task, f"正在重跑研究任务 #{job_id} 的失败条目")

        def _start_restart_research_job(self, config_path: str, job_id: int) -> None:
            if job_id <= 0:
                self._send_json({"ok": False, "message": "缺少 job_id"}, status=400)
                return
            reason = f"用户重启研究任务，原任务 #{job_id} 已取消"
            try:
                _mark_research_job_cancelled(config_path, job_id, reason)
            except Exception as exc:
                logger.exception("Prepare restart research job failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)
                return

            async def task(workflow: Any) -> dict[str, Any]:
                return await workflow.restart_research_job(job_id)

            self._start_background_task(
                config_path,
                f"restart-research-{job_id}",
                task,
                f"正在重启研究任务 #{job_id}",
                force=True,
            )

        def _start_research_blogger(self, config_path: str, form: dict[str, list[str]]) -> None:
            blogger = (_field(form, "blogger") or _field(form, "blogger_select")).strip()
            if not blogger:
                self._send_json({"ok": False, "message": "请选择或输入研究博主"}, status=400)
                return
            limit = int(_field(form, "limit", 10) or 0)
            since = _field(form, "since").strip()
            until = _field(form, "until").strip()
            force = "force" in form
            push = "push" in form

            async def task(workflow: Any) -> dict[str, Any]:
                return await workflow.research_blogger(blogger=blogger, limit=limit, push=push, force=force, since=since, until=until)

            self._start_background_task(config_path, f"research-blogger-{blogger}", task, f"正在研究博主：{blogger}")

        def _start_research_video(self, config_path: str, form: dict[str, list[str]]) -> None:
            video = _field(form, "video").strip()
            aweme_id = _field(form, "aweme_id").strip()
            if not video and not aweme_id:
                self._send_json({"ok": False, "message": "请输入视频链接或 aweme_id"}, status=400)
                return
            force = "force" in form
            push = "push" in form
            label = aweme_id or video[:64]

            async def task(workflow: Any) -> dict[str, Any]:
                return await workflow.research_video(video=video, aweme_id=aweme_id, push=push, force=force)

            self._start_background_task(config_path, f"research-video-{label}", task, "正在研究单个视频")

        def _repush_aweme(self, config_path: str, aweme_id: str) -> None:
            try:
                from kenradar.notification.feishu import FeishuPusher
                from kenradar.storage import create_database

                config = load_config(config_path)
                row = load_aweme_detail(config, aweme_id)
                if not row:
                    self._send_json({"ok": False, "message": "未找到内容"}, status=404)
                    return
                item = {
                    "aweme_id": aweme_id,
                    "blogger_name": row.get("nickname") or "未知博主",
                    "title": row.get("title") or "无标题",
                    "create_time": row.get("create_time"),
                    "text": row.get("summary_text") or "",
                    "summary_status": row.get("summary_status") or "pending",
                    "summary_path": row.get("summary_path") or "",
                    "video_url": row.get("video_url") or f"https://www.douyin.com/video/{aweme_id}",
                    "detail_url": f"{str(config.get('app.web_base_url', 'http://172.30.10.150:8765')).rstrip('/')}/aweme?id={aweme_id}",
                }
                ok = FeishuPusher(config, create_database(config)).push([item])
                self._send_json({"ok": ok, "message": "已重新推送" if ok else "推送失败"})
            except Exception as exc:
                logger.exception("Repush failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _toggle_favorite(self, config_path: str, aweme_id: str) -> None:
            if not aweme_id:
                self._send_json({"ok": False, "message": "缺少 aweme_id"}, status=400)
                return
            try:
                from kenradar.storage import create_database

                config = load_config(config_path)
                config_db = create_database(config)
                config_db.initialize()
                favorite = config_db.toggle_favorite(aweme_id)
                self._send_json({"ok": True, "favorite": favorite, "message": "已收藏" if favorite else "已取消收藏"})
            except Exception as exc:
                logger.exception("Toggle favorite failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _update_curation(self, config_path: str, form: dict[str, list[str]]) -> None:
            aweme_id = _field(form, "aweme_id").strip()
            if not aweme_id:
                self._send_json({"ok": False, "message": "缺少 aweme_id"}, status=400)
                return
            try:
                from kenradar.storage import create_database

                config = load_config(config_path)
                database = create_database(config)
                database.initialize()
                topic_pool_status = _field(form, "topic_pool_status").strip()
                research_status = _field(form, "research_status").strip()
                user_note = _field(form, "user_note").strip()
                database.set_content_curation(
                    aweme_id,
                    favorite=("favorite" in form),
                    topic_pool_status=topic_pool_status,
                    research_status=research_status,
                    user_note=user_note,
                )
                self._send_json({"ok": True, "message": "内容标记已保存"})
            except Exception as exc:
                logger.exception("Update curation failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _test_feishu(self, config_path: str, force_card: bool) -> None:
            try:
                from kenradar.notification.feishu import build_kenradar_feishu_card, send_feishu_card
                import requests

                config = load_config(config_path)
                webhook = config.feishu_webhook_url
                if not webhook:
                    self._send_json({"ok": False, "message": "未配置飞书 Webhook"}, status=400)
                    return
                now = datetime.now()
                videos = [
                    {
                        "short_title": "KenRadar 测试简报",
                        "short_summary": "这是一条 Web 后台触发的测试消息，用于验证飞书 text/card 推送链路是否正常。",
                        "blogger_name": "系统测试",
                        "publish_time": now.strftime("%Y-%m-%d %H:%M"),
                        "video_url": str(config.get("app.web_base_url", "http://172.30.10.150:8765")),
                        "detail_url": str(config.get("app.web_base_url", "http://172.30.10.150:8765")),
                    }
                ]
                if force_card:
                    payload = build_kenradar_feishu_card(now.strftime("%Y-%m-%d"), now.strftime("%H:%M"), videos, max_items=5)
                    send_feishu_card(webhook, payload)
                else:
                    payload = {"msg_type": "text", "content": {"text": "流媒体更新简报｜测试\n\n1. KenRadar 测试简报\n这是一条 Web 后台触发的测试消息。"}}
                    response = requests.post(webhook, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
                    response.raise_for_status()
                self._send_json({"ok": True, "message": "测试推送已发送"})
            except Exception as exc:
                logger.exception("Feishu test failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _generate_weekly_brief(self, config_path: str) -> None:
            try:
                config = load_config(config_path)
                path = generate_weekly_brief(config)
                self._send_json({"ok": True, "message": f"周报已生成：{path.name}", "path": str(path)})
            except Exception as exc:
                logger.exception("Generate weekly brief failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _restart_web(self, config_path: str) -> None:
            try:
                _mark_running_tasks_cancelled(config_path, "用户在 Web 后台点击中断并重启")
                _TASK_STATE.update(
                    {
                        "running": False,
                        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "restarting",
                        "message": "正在中断当前任务并重启 Web 进程",
                    }
                )
                config = load_config(config_path)
                script = config.root_dir / "kenradarctl.sh"
                self._send_json({"ok": True, "message": "正在重启 KenRadar Web，请稍后刷新页面"})

                def restart_later() -> None:
                    try:
                        subprocess.Popen(
                            [str(script), "restart"],
                            cwd=str(config.root_dir),
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            start_new_session=True,
                        )
                    except Exception:
                        logger.exception("Restart command failed")

                threading.Timer(0.5, restart_later).start()
            except Exception as exc:
                logger.exception("Restart request failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _cancel_research_job(self, config_path: str, job_id: int) -> None:
            if job_id <= 0:
                self._send_json({"ok": False, "message": "缺少 job_id"}, status=400)
                return
            try:
                _mark_research_job_cancelled(config_path, job_id, "用户在 Web 后台取消研究任务")
                _TASK_STATE.update(
                    {
                        "running": False,
                        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "status": "cancelled",
                        "message": f"研究任务 #{job_id} 已请求取消",
                    }
                )
                self._send_json({"ok": True, "message": "已请求取消，流水线会在当前步骤结束后停止"})
            except Exception as exc:
                logger.exception("Cancel research job failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _pause_research_job(self, config_path: str, job_id: int) -> None:
            if job_id <= 0:
                self._send_json({"ok": False, "message": "缺少 job_id"}, status=400)
                return
            try:
                _mark_research_job_paused(config_path, job_id)
                _TASK_STATE.update(
                    {
                        "running": True,
                        "status": "paused",
                        "message": f"研究任务 #{job_id} 已请求暂停，当前单步结束后暂停",
                    }
                )
                self._send_json({"ok": True, "message": "已请求暂停，当前下载/转录/AI 单步结束后暂停"})
            except Exception as exc:
                logger.exception("Pause research job failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _resume_research_job(self, config_path: str, job_id: int) -> None:
            if job_id <= 0:
                self._send_json({"ok": False, "message": "缺少 job_id"}, status=400)
                return

            async def task(workflow: Any) -> dict[str, Any]:
                return await workflow.restart_research_job(job_id)

            self._start_background_task(
                config_path,
                f"resume-research-{job_id}",
                task,
                f"正在接续研究任务 #{job_id}",
                force=True,
            )

        def _save_frontend_config(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                config = load_config(config_path)
                save_config(config, _frontend_config_to_raw(config, data))
                self._send_json({"ok": True, "message": "配置已保存"})
            except Exception as exc:
                logger.exception("Frontend config update failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _toggle_source(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                source_id = str(data.get("id") or "").strip()
                if not source_id:
                    raise ValueError("缺少来源 ID")
                config = load_config(config_path)
                raw = deepcopy(config.raw)
                bloggers = raw.setdefault("bloggers", [])
                for item in bloggers:
                    if isinstance(item, dict) and _source_key(item) == source_id:
                        item["enabled"] = not bool(item.get("enabled", True))
                        save_config(config, raw)
                        self._send_json({"ok": True, "enabled": item["enabled"]})
                        return

                known_source = next((row for row in load_bloggers(config) if source_id in _source_aliases(row)), None)
                if not known_source:
                    raise ValueError("未找到要切换的关注博主")
                sec_uid = str(known_source.get("sec_uid") or "").strip()
                url = str(known_source.get("douyin_url") or known_source.get("url") or "").strip()
                if not sec_uid or sec_uid.startswith("single_video:") or "/user/" not in url:
                    raise ValueError("该来源不是可轮询的抖音博主主页，请登记博主主页 URL 后再开启监控")
                raw["bloggers"].append(
                    {
                        "platform": str(known_source.get("platform") or "douyin"),
                        "url": url,
                        "sec_uid": sec_uid,
                        "name": str(known_source.get("nickname") or sec_uid),
                        "enabled": True,
                    }
                )
                save_config(config, raw)
                self._send_json({"ok": True, "enabled": True})
            except Exception as exc:
                logger.exception("Toggle source failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _delete_source_json(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                source_id = str(data.get("id") or "").strip()
                if not source_id:
                    raise ValueError("缺少来源 ID")
                config = load_config(config_path)
                raw = deepcopy(config.raw)
                bloggers = raw.setdefault("bloggers", [])
                next_bloggers = [item for item in bloggers if not (isinstance(item, dict) and _source_key(item) == source_id)]
                if len(next_bloggers) == len(bloggers):
                    raise ValueError("未找到要移出的关注博主")
                raw["bloggers"] = next_bloggers
                save_config(config, raw)
                self._send_json({"ok": True, "message": "来源已删除"})
            except Exception as exc:
                logger.exception("Delete source failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _add_source_json(self, config_path: str, data: dict[str, Any]) -> None:
            form = {
                "platform": [str(data.get("platform") or "douyin")],
                "name": [str(data.get("name") or "")],
                "url": [str(data.get("url") or "")],
                "sec_uid": [str(data.get("sec_uid") or "")],
                "category": [str(data.get("category") or "")],
                "note": [str(data.get("note") or "")],
            }
            if bool(data.get("enabled", True)):
                form["enabled"] = ["on"]
            try:
                source = _upsert_source_from_form(config_path, form)
                self._send_json({"ok": True, "message": "来源已登记", "source": source})
            except Exception as exc:
                logger.exception("Add source failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _update_source_category(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                source_id = str(data.get("id") or "").strip()
                if not source_id:
                    raise ValueError("缺少来源 ID")
                category = str(data.get("category") or "").strip()
                config = load_config(config_path)
                raw = deepcopy(config.raw)
                for item in raw.setdefault("bloggers", []):
                    if isinstance(item, dict) and _source_key(item) == source_id:
                        if category:
                            item["category"] = category
                        else:
                            item.pop("category", None)
                        save_config(config, raw)
                        self._send_json({"ok": True, "category": category})
                        return
                raise ValueError("未找到要分类的关注博主")
            except Exception as exc:
                logger.exception("Update source category failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _update_source_categories(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                action = str(data.get("action") or "").strip()
                category = _clean_source_category(data.get("category"))
                if not category:
                    raise ValueError("请填写来源分类名称")
                config = load_config(config_path)
                raw = deepcopy(config.raw)
                categories = _configured_source_categories(raw)
                if action == "add":
                    if category not in categories:
                        categories.append(category)
                elif action == "delete":
                    if category in _assigned_source_categories(raw):
                        raise ValueError("该分类仍有博主在使用，请先调整这些来源的分类")
                    categories = [item for item in categories if item != category]
                else:
                    raise ValueError("未知的来源分类操作")
                raw["source_categories"] = categories
                save_config(config, raw)
                self._send_json({"ok": True, "categories": _source_category_options(raw)})
            except Exception as exc:
                logger.exception("Update source categories failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _add_source(self, config_path: str, form: dict[str, list[str]]) -> None:
            try:
                _upsert_source_from_form(config_path, form)
                self.send_response(303)
                self.send_header("Location", "/sources")
                self.end_headers()
            except Exception as exc:
                logger.exception("Add source failed")
                self._send_html(render_error(str(exc)), status=400)

        def _promote_source(self, config_path: str, form: dict[str, list[str]]) -> None:
            try:
                config = load_config(config_path)
                raw = deepcopy(config.raw)
                raw.setdefault("bloggers", [])
                name = _field(form, "name").strip()
                url = _field(form, "url").strip()
                sec_uid = _field(form, "sec_uid").strip()
                if not name:
                    raise ValueError("缺少博主名称")
                if not url and sec_uid:
                    url = f"https://www.douyin.com/user/{sec_uid}"
                if not url:
                    raise ValueError("缺少主页链接或 sec_uid")
                for item in raw["bloggers"]:
                    if not isinstance(item, dict):
                        continue
                    if (sec_uid and str(item.get("sec_uid") or "") == sec_uid) or str(item.get("url") or "") == url:
                        item["name"] = name
                        item["url"] = url
                        item["sec_uid"] = sec_uid or item.get("sec_uid", "")
                        item["enabled"] = True
                        break
                else:
                    raw["bloggers"].append(
                        {
                            "platform": "douyin",
                            "name": name,
                            "url": url,
                            "sec_uid": sec_uid,
                            "enabled": True,
                        }
                    )
                save_config(config, raw)
                self.send_response(303)
                self.send_header("Location", "/sources")
                self.end_headers()
            except Exception as exc:
                logger.exception("Promote source failed")
                self._send_html(render_error(str(exc)), status=400)

        def _update_source(self, config_path: str, form: dict[str, list[str]]) -> None:
            try:
                config = load_config(config_path)
                raw = deepcopy(config.raw)
                bloggers = raw.setdefault("bloggers", [])
                original_key = _field(form, "original_key").strip()
                source = {
                    "platform": _field(form, "platform", "douyin") or "douyin",
                    "url": _field(form, "url").strip(),
                    "sec_uid": _field(form, "sec_uid").strip(),
                    "name": _field(form, "name").strip(),
                    "category": _field(form, "category").strip(),
                    "enabled": "enabled" in form,
                }
                if not source["name"] or not source["url"]:
                    raise ValueError("博主名称和主页链接必填")
                for index, item in enumerate(bloggers):
                    if isinstance(item, dict) and _source_key(item) == original_key:
                        existing_note = item.get("note")
                        if existing_note:
                            source["note"] = existing_note
                        bloggers[index] = {key: value for key, value in source.items() if value not in ("", None)}
                        break
                else:
                    raise ValueError("未找到要修改的关注博主")
                save_config(config, raw)
                self.send_response(303)
                self.send_header("Location", "/sources")
                self.end_headers()
            except Exception as exc:
                logger.exception("Update source failed")
                self._send_html(render_error(str(exc)), status=400)

        def _delete_source(self, config_path: str, form: dict[str, list[str]]) -> None:
            try:
                config = load_config(config_path)
                raw = deepcopy(config.raw)
                bloggers = raw.setdefault("bloggers", [])
                original_key = _field(form, "original_key").strip()
                next_bloggers = [item for item in bloggers if not (isinstance(item, dict) and _source_key(item) == original_key)]
                if len(next_bloggers) == len(bloggers):
                    raise ValueError("未找到要移出的关注博主")
                raw["bloggers"] = next_bloggers
                save_config(config, raw)
                self.send_response(303)
                self.send_header("Location", "/sources")
                self.end_headers()
            except Exception as exc:
                logger.exception("Delete source failed")
                self._send_html(render_error(str(exc)), status=400)

        def log_message(self, format: str, *args: Any) -> None:
            logger.info("web %s - %s", self.address_string(), format % args)

    server = ThreadingHTTPServer((host, port), KenRadarHandler)
    logger.info("KenRadar 控制台已启动: http://%s:%s", host, port)
    server.serve_forever()


def _frontend_dist_dir() -> Path:
    return Path(__file__).resolve().parent / "frontend" / "dist"


def _upsert_source_from_form(config_path: str, form: dict[str, list[str]]) -> dict[str, Any]:
    from kenradar.core.source_resolver import resolve_douyin_source
    from kenradar.storage import create_database

    config = load_config(config_path)
    raw = deepcopy(config.raw)
    raw.setdefault("bloggers", [])
    platform = _field(form, "platform", "douyin")
    if platform != "douyin":
        raise ValueError("当前仅支持自动新增抖音博主")
    resolved = resolve_douyin_source(
        config,
        _field(form, "url").strip(),
        name=_field(form, "name").strip(),
        sec_uid=_field(form, "sec_uid").strip(),
    )
    source = {
        "platform": "douyin",
        "url": resolved.url,
        "sec_uid": resolved.sec_uid,
        "name": resolved.name,
        "category": _field(form, "category").strip(),
        "note": _field(form, "note").strip(),
        "enabled": "enabled" in form,
    }
    replaced = False
    for item in raw["bloggers"]:
        if not isinstance(item, dict):
            continue
        configured_sec_uid = str(item.get("sec_uid") or "")
        configured_url = str(item.get("url") or "")
        if configured_sec_uid == resolved.sec_uid or configured_url == resolved.url:
            item.update({key: value for key, value in source.items() if value not in ("", None)})
            replaced = True
            break
    if not replaced:
        raw["bloggers"].append({key: value for key, value in source.items() if value not in ("", None)})
    save_config(config, raw)
    create_database(config).upsert_blogger(
        url=resolved.url,
        name=resolved.name,
        sec_uid=resolved.sec_uid,
        enabled=("enabled" in form),
    )
    return source


def _build_frontend_bootstrap(config: AppConfig) -> dict[str, Any]:
    library_stats = _safe_query(lambda: load_library_counts(config), {})
    library_limit = min(FRONTEND_LIBRARY_LIMIT, max(100, int(library_stats.get("total_items") or 0)))
    rows = load_aweme_rows(config, limit=library_limit)
    failures = {str(item.get("aweme_id") or ""): item for item in _safe_query(lambda: load_failures(config, limit=500), [])}
    return {
        "videos": [_frontend_video(config, row, failures.get(str(row.get("aweme_id") or ""))) for row in rows],
        "libraryStats": {
            **library_stats,
            "loaded_items": len(rows),
            "display_limit": FRONTEND_LIBRARY_LIMIT,
        },
        "tasks": [_frontend_task(row) for row in _safe_query(lambda: load_research_jobs(config, limit=100), [])],
        "sources": _frontend_sources(config),
        "sourceCategories": _source_category_options(config.raw),
        "pushRecords": [_frontend_push(row) for row in _safe_query(lambda: load_push_logs(config, limit=100), [])],
        "logs": [_frontend_log(row, index) for index, row in enumerate(_safe_query(lambda: load_log_lines(config, limit=300), []))],
        "notes": _safe_query(lambda: load_note_files(config), []),
        "briefs": _safe_query(lambda: load_brief_files(config), []),
        "config": _frontend_config(config),
        "alerts": [_frontend_alert(row, index) for index, row in enumerate(_safe_query(lambda: load_recent_alerts(config, limit=50), []))],
        "system": _frontend_system_info(config),
        "taskState": deepcopy(_TASK_STATE),
    }


def _safe_query(factory: Any, default: Any) -> Any:
    try:
        return factory()
    except Exception:
        logger.exception("Frontend bootstrap query failed")
        return default


def _frontend_video(config: AppConfig, row: dict[str, Any], failure: dict[str, Any] | None = None) -> dict[str, Any]:
    aweme_id = str(row.get("aweme_id") or "")
    summary_path = Path(str(row.get("summary_path") or "")) if row.get("summary_path") else None
    summary_markdown = ""
    if summary_path and summary_path.exists():
        summary_markdown = read_text(summary_path)
    elif row.get("summary_text"):
        summary_markdown = str(row.get("summary_text") or "")
    status = _frontend_content_status(row, failure)
    stage = str((failure or {}).get("stage") or "")
    failure_stage = "transcribe" if stage == "whisper" else stage
    updated_at = _frontend_video_updated_at(row, failure)
    return {
        "id": aweme_id,
        "title": str(row.get("brief_title") or row.get("title") or "无标题"),
        "brief_summary": str(row.get("brief_summary") or ""),
        "blogger": str(row.get("nickname") or "未知博主"),
        "rating": round(float(row.get("value_score") or 0) * 2, 1),
        "recommend_action": str(row.get("recommended_action") or ""),
        "status": status,
        "failed_at_step": failure_stage,
        "failure_stage": failure_stage,
        "failed_at": str((failure or {}).get("failed_at") or ""),
        "error_message": str((failure or {}).get("error_message") or row.get("summary_error") or ""),
        "created_at": _format_aweme_time(row.get("create_time")),
        "published_at": _format_aweme_time(row.get("create_time")),
        "collected_at": _format_datetime_value(row.get("aweme_created_at")),
        "updated_at": updated_at,
        "duration": _format_duration(row.get("duration")),
        "original_url": str(row.get("video_url") or f"https://www.douyin.com/video/{aweme_id}"),
        "download_status": str(row.get("download_status") or "pending"),
        "transcript_status": str(row.get("transcript_status") or "pending"),
        "summary_status": str(row.get("summary_status") or "pending"),
        "push_status": str(row.get("push_status") or "pending"),
        "summary_path": str(row.get("summary_path") or ""),
        "current_stage": _frontend_current_stage(row, failure),
        "pipeline_steps": _frontend_pipeline_steps(row),
        "tags": row.get("tags") or [],
        "whisper_text": _frontend_transcript(row),
        "summary_markdown": summary_markdown,
        "one_sentence_conclusion": str(row.get("one_sentence_conclusion") or ""),
        "importance_score": round(float(row.get("importance_score") or 0) * 2, 1),
        "novelty_score": round(float(row.get("novelty_score") or 0) * 2, 1),
        "information_density": round(float(row.get("information_density") or 0) * 2, 1),
        "business_relevance": round(float(row.get("business_relevance") or 0) * 2, 1),
        "recommendation_reason": str(row.get("recommendation_reason") or ""),
    }


def _frontend_content_status(row: dict[str, Any], failure: dict[str, Any] | None) -> str:
    if failure:
        return "failed"
    if str(row.get("summary_status") or "") == "success":
        return "completed"
    if str(row.get("download_status") or "") == "failed" or str(row.get("transcript_status") or "") == "failed" or str(row.get("summary_status") or "") == "failed":
        return "failed"
    if str(row.get("download_status") or "") in {"done", "success"} or str(row.get("transcript_status") or "") == "success":
        return "processing"
    return "queued"


def _frontend_video_updated_at(row: dict[str, Any], failure: dict[str, Any] | None) -> str:
    return str(
        (failure or {}).get("failed_at")
        or row.get("summary_updated_at")
        or row.get("transcript_updated_at")
        or row.get("transcript_created_at")
        or row.get("aweme_created_at")
        or row.get("create_time")
        or ""
    )


def _frontend_stage_state(raw_status: Any, *, success: bool = False, failed: bool = False) -> str:
    if failed:
        return "failed"
    if success:
        return "success"
    status = str(raw_status or "pending").lower()
    if status in {"done", "success", "completed", "ok"}:
        return "success"
    if status in {"failed", "error", "fail"}:
        return "failed"
    if status in {"running", "processing", "downloading", "transcribing", "summarizing", "noting"}:
        return "processing"
    if status in {"pending", "queued", "waiting"}:
        return "queued"
    return "unknown"


def _frontend_pipeline_steps(row: dict[str, Any]) -> list[dict[str, str]]:
    download_status = str(row.get("download_status") or "pending")
    transcript_status = str(row.get("transcript_status") or "pending")
    summary_status = str(row.get("summary_status") or "pending")
    push_status = str(row.get("push_status") or "pending")
    summary_path = str(row.get("summary_path") or "")
    return [
        {"key": "download", "label": "下载", "state": _frontend_stage_state(download_status, success=bool(row.get("local_path")))},
        {"key": "transcribe", "label": "转录", "state": _frontend_stage_state(transcript_status)},
        {"key": "ai", "label": "AI", "state": _frontend_stage_state(summary_status)},
        {"key": "note", "label": "笔记", "state": _frontend_stage_state(summary_status, success=bool(summary_path) and summary_status == "success")},
        {"key": "push", "label": "推送", "state": _frontend_stage_state(push_status)},
    ]


def _frontend_current_stage(row: dict[str, Any], failure: dict[str, Any] | None) -> str:
    stage = str((failure or {}).get("stage") or "")
    if stage == "whisper":
        return "transcribe"
    if stage in {"download", "transcribe", "ai", "push"}:
        return stage
    for step in _frontend_pipeline_steps(row):
        if step["state"] in {"failed", "processing", "queued"}:
            return step["key"]
    return "done"


def _frontend_transcript(row: dict[str, Any]) -> str:
    text_content = str(row.get("text_content") or "")
    if text_content.strip():
        return text_content
    text_path = Path(str(row.get("text_path") or "")) if row.get("text_path") else None
    if text_path and text_path.exists():
        return read_text(text_path)
    return ""


def _format_aweme_time(value: Any) -> str:
    try:
        timestamp = int(float(value or 0))
    except (TypeError, ValueError):
        timestamp = 0
    if timestamp > 0:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    return str(value or "")


def _format_datetime_value(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    return str(value or "").replace("T", " ")[:16]


def _format_duration(value: Any) -> str:
    try:
        seconds = int(float(value or 0))
    except (TypeError, ValueError):
        return str(value or "")
    if seconds <= 0:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"


def _frontend_task(row: dict[str, Any]) -> dict[str, Any]:
    total = int(row.get("total_count") or 0)
    done = int(row.get("success_count") or 0) + int(row.get("failed_count") or 0) + int(row.get("skipped_count") or 0)
    status = _map_task_status(str(row.get("status") or "queued"))
    progress = 100 if status == "completed" else (round(done / total * 100) if total else (15 if status in {"queued", "processing"} else 0))
    return {
        "id": str(row.get("id") or ""),
        "type": "blogger",
        "target": str(row.get("blogger_name") or row.get("creator_name") or row.get("current_title") or "研究任务"),
        "status": status,
        "total_items": total,
        "completed_items": int(row.get("success_count") or 0),
        "failed_items": int(row.get("failed_count") or 0),
        "skipped_items": int(row.get("skipped_count") or 0),
        "created_at": str(row.get("created_at") or ""),
        "pipeline_stage": _map_task_stage(str(row.get("current_item_status") or row.get("status") or "")),
        "pipeline_progress": progress,
        "force_retry": bool(row.get("force_enabled")),
    }


def _map_task_status(value: str) -> str:
    if value == "paused":
        return "paused"
    if value in {"success", "completed", "transcribe_only_completed"}:
        return "completed"
    if value in {"failed", "cancelled", "partial_failed", "transcribe_only_partial_failed"}:
        return "failed"
    if value in {"pending", "queued"}:
        return "queued"
    return "processing"


def _map_task_stage(value: str) -> str:
    if value in {"downloading", "downloaded", "pending"}:
        return "downloading"
    if value in {"transcribing", "transcribed_waiting_summary"}:
        return "transcribing"
    if value in {"summarizing", "noting"}:
        return "summarizing"
    if value in {"success", "skipped", "completed"}:
        return "completed"
    if value in {"failed", "cancelled"}:
        return "failed"
    return "downloading"


def _frontend_sources(config: AppConfig) -> list[dict[str, Any]]:
    quality_by_name = {str(row.get("nickname") or ""): row for row in _safe_query(lambda: load_source_quality(config), [])}
    sources = []
    for row in _safe_query(lambda: load_bloggers(config), []):
        name = str(row.get("nickname") or "未命名博主")
        db_name = str(row.get("database_nickname") or name)
        sec_uid = str(row.get("sec_uid") or "")
        source_url = str(row.get("douyin_url") or "")
        if sec_uid.startswith("single_video:") or "/video/" in source_url:
            continue
        quality = quality_by_name.get(db_name) or quality_by_name.get(name, {})
        success_rate = float(quality.get("summary_success_rate") or 0)
        average_score = float(quality.get("average_score") or 0)
        source_scope = str(row.get("source_scope") or "database")
        in_config = bool(row.get("in_config"))
        monitor_enabled = bool(row.get("monitor_enabled"))
        source_id = str(row.get("source_key") or sec_uid or source_url or name)
        sources.append(
            {
                "id": source_id,
                "name": name,
                "url": source_url,
                "category": str(row.get("category") or ""),
                "status": "enabled" if monitor_enabled else "disabled",
                "quality_score": round(max(success_rate, average_score * 20)),
                "last_checked": str(row.get("last_check_at") or "暂无"),
                "total_captured": int(row.get("item_count") or 0),
                "parse_success_rate": round(success_rate),
                "source_scope": source_scope,
                "in_config": in_config,
                "monitor_enabled": monitor_enabled,
                "config_enabled": bool(row.get("config_enabled")),
                "can_toggle": bool(sec_uid and not sec_uid.startswith("single_video:") and (source_url == "" or "/video/" not in source_url)),
                "can_delete_config": in_config,
                "source_label": "配置监控" if in_config else "资料库历史",
            }
        )
    return sources


def _frontend_push(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row.get("id") or ""),
        "aweme_id": str(row.get("aweme_id") or ""),
        "title": str(row.get("title") or "无标题"),
        "blogger": str(row.get("nickname") or "未知博主"),
        "push_type": "card" if str(row.get("channel") or "").lower() != "text" else "text",
        "sent_at": str(row.get("pushed_at") or ""),
        "status": "success" if str(row.get("status") or "") == "success" else "failed",
        "response_msg": str(row.get("error_message") or ""),
        "payload": json.dumps({key: row.get(key) for key in row.keys()}, ensure_ascii=False, default=str, indent=2),
    }


def _frontend_log(row: dict[str, Any], index: int) -> dict[str, Any]:
    level = str(row.get("level") or "info").lower()
    if level == "warning":
        level = "warn"
    module = str(row.get("component") or "WebUI")
    module_map = {"download": "Downloader", "whisper": "Whisper", "openai": "AI", "ai": "AI", "feishu": "Feishu", "web": "WebUI", "scheduler": "Scheduler"}
    return {
        "id": f"log_{index}",
        "timestamp": str(row.get("timestamp") or ""),
        "level": level if level in {"info", "warn", "error", "debug"} else "info",
        "module": module_map.get(module.lower(), "WebUI"),
        "message": str(row.get("message") or row.get("line") or ""),
    }


def _frontend_alert(row: dict[str, Any], index: int) -> dict[str, Any]:
    level = str(row.get("level") or "warn").lower()
    component = str(row.get("component") or "system")
    aweme_id = str(row.get("aweme_id") or "")
    title = str(row.get("title") or (f"内容异常 [{aweme_id}]" if aweme_id else "系统告警"))
    return {
        "id": f"alert_{index}",
        "title": title,
        "desc": str(row.get("message") or ""),
        "time": str(row.get("created_at") or ""),
        "level": "critical" if level in {"error", "critical", "fatal"} else "warn",
        "module": component,
    }


def _frontend_system_info(config: AppConfig) -> dict[str, Any]:
    from kenradar.publishing import GithubSyncManager

    gpu_label = "GPU 调度"
    gpu_status = "Active" if bool(config.get("gpu_scheduler.enabled", True)) else "Disabled"
    gpu_percent: int | None = None
    query_tool = str(config.get("gpu_scheduler.memory_check.command") or ("nv" + "idia-smi"))
    try:
        result = subprocess.run(
            [query_tool, "--query-gpu=name,utilization.gpu", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
            check=False,
        )
        first_line = (result.stdout or "").splitlines()[0].strip() if result.stdout else ""
        if result.returncode == 0 and first_line:
            name, _, util = first_line.partition(",")
            gpu_label = name.strip() or gpu_label
            gpu_percent = max(0, min(100, int(float(util.strip() or 0))))
    except Exception:
        gpu_percent = None
    return {
        "port": int(config.get("app.web_port", 8765) or 8765),
        "gpu_label": gpu_label,
        "gpu_status": gpu_status,
        "gpu_percent": gpu_percent,
        "whisper_model": str(config.get("transcribe.model", config.get("ai.whisper.model", "large-v3-turbo"))),
        "log_path": str((config.data_dir / "kenradar.log").relative_to(config.root_dir) if config.data_dir.is_relative_to(config.root_dir) else config.data_dir / "kenradar.log"),
        "health": _safe_query(lambda: load_health(config), {}),
        "background_task": {
            "running": _TASK_STATE.get("running", False),
            "message": _TASK_STATE.get("message", "空闲"),
            "started_at": _TASK_STATE.get("started_at"),
            "finished_at": _TASK_STATE.get("finished_at"),
            "status": _TASK_STATE.get("status", "idle"),
            "progress": _TASK_STATE.get("progress"),
            "queue": _public_task_queue(),
        },
        "publishing": _safe_query(lambda: GithubSyncManager(config).status_summary(), {}),
    }


def _frontend_config(config: AppConfig) -> dict[str, Any]:
    schedule = config.get("schedule", {}) or {}
    whisper = config.get("ai.whisper", {}) or {}
    transcribe = config.get("transcribe", {}) or {}
    organizer = config.get("ai.organizer", {}) or {}
    providers = organizer.get("providers") if isinstance(organizer.get("providers"), list) else []
    provider = providers[0] if providers else {}
    fallback_provider = next(
        (
            item
            for item in providers[1:]
            if isinstance(item, dict) and item.get("enabled", True) and str(item.get("api_type") or "").lower() == "ollama"
        ),
        {},
    )
    download = config.get("download", {}) or {}
    feishu = config.get("notification.channels.feishu", {}) or {}
    github_pages = config.get("publishing.github_pages", {}) or {}
    github_sync = config.get("publishing.github_sync", {}) or {}
    public_base_url = str(github_pages.get("public_base_url") or "")
    return {
        "scheduler": {
            "enabled": bool(schedule.get("enabled", True)),
            "cronExpression": ", ".join(schedule.get("times", []) or []),
            "grace_period_mins": int(schedule.get("retry_interval_seconds", 300) or 300) // 60,
            "max_concurrent_tasks": int(schedule.get("max_items_per_run", 0) or 0),
            "retry_times": int(schedule.get("retry_times", 2) or 2),
            "max_items_per_blogger": int(schedule.get("max_items_per_blogger", 0) or 0),
            "manual_trigger_enabled": bool(schedule.get("manual_trigger_enabled", True)),
        },
        "whisper": {
            "model": str(transcribe.get("model") or whisper.get("model", "large-v3-turbo")),
            "device": str(transcribe.get("device") or whisper.get("device", "cpu")),
            "threads": int(transcribe.get("cpu_threads_per_worker", whisper.get("cpu_threads", 4)) or 4),
            "use_gpu": str(transcribe.get("device") or whisper.get("device", "cpu")) == "cuda",
            "vram_offload_gb": int(config.get("gpu_scheduler.memory_check.min_free_vram_mb_for_whisper_gpu", 4000) or 4000) // 1000,
            "staged_gpu_scheduling": bool(config.get("gpu_scheduler.enabled", True)),
        },
        "ai": {
            "api_type": str(provider.get("api_type") or organizer.get("api_type") or "chat_completions"),
            "endpoint": str(provider.get("endpoint") or organizer.get("endpoint") or "https://apihub.agnes-ai.com/v1"),
            "model": str(provider.get("model") or organizer.get("model") or "agnes-2.0-flash"),
            "provider_name": str(provider.get("name") or "AI"),
            "fallback_enabled": bool(fallback_provider),
            "fallback_provider_name": str(fallback_provider.get("name") or "ollama"),
            "fallback_endpoint": str(fallback_provider.get("endpoint") or ""),
            "fallback_provider_model": str(fallback_provider.get("model") or ""),
            "temperature": float(organizer.get("temperature", 0.2) or 0.2),
            "top_p": float(provider.get("top_p", organizer.get("top_p", 0.9)) or 0.9),
            "top_k": int(provider.get("top_k", organizer.get("top_k", 40)) or 40),
            "timeout_sec": int(organizer.get("request_timeout", organizer.get("timeout", 120)) or 120),
            "max_tokens": int(organizer.get("max_tokens", 2048) or 2048),
            "max_input_chars": int(provider.get("max_input_chars", organizer.get("max_input_chars", 12000)) or 12000),
            "keep_alive": str(provider.get("keep_alive", organizer.get("keep_alive", "10m")) or "10m"),
            "no_think": bool(provider.get("no_think", organizer.get("no_think", True))),
            "compact_prompt": bool(provider.get("compact_prompt", organizer.get("compact_prompt", True))),
            "fallback_model": str(organizer.get("fallback_model") or ""),
            "prompt_template": str(organizer.get("prompt_template") or ""),
        },
        "download": {
            "path": str(download.get("path") or "data/Downloaded"),
            "max_workers": int(download.get("max_workers", 1) or 1),
            "batch_size": int(download.get("batch_size", 5) or 5),
            "batch_cooldown_seconds": int(download.get("batch_cooldown_seconds", download.get("batch_cooldown", 5)) or 5),
            "max_duration_seconds": int(download.get("max_duration_seconds", 900) or 900),
            "retry_failed": bool(download.get("retry_failed", True)),
            "circuit_breaker_failures": int(download.get("circuit_breaker_failures", 5) or 5),
            "circuit_breaker_cooldown_seconds": int(download.get("circuit_breaker_cooldown_seconds", 300) or 300),
            "save_json": bool(download.get("save_json", True)),
        },
        "feishu": {
            "webhook_url": "",
            "message_type": str(feishu.get("message_type") or "auto"),
            "push_threshold_rating": float(feishu.get("push_threshold_rating", 7.5) or 7.5),
            "retry_attempts": int(feishu.get("retry_attempts", 3) or 3),
            "card_max_items": int(feishu.get("card_max_items", 5) or 5),
            "card_theme": str(feishu.get("card_theme") or "blue"),
        },
        "security": {
            "port": int(config.get("app.web_port", 8765) or 8765),
            "bind_ip": str(config.get("app.web_host", "127.0.0.1")),
            "password_auth": bool(config.get("app.web_password", "")),
            "web_password": "",
            "access_token_ttl_hours": 24,
        },
        "publishing": {
            "github_pages_enabled": bool(github_pages.get("enabled", False)),
            "github_pages_output_dir": str(github_pages.get("output_dir") or "./docs"),
            "github_pages_public_base_url": public_base_url,
            "github_pages_public_base_url_configured": bool(public_base_url.strip() and "${" not in public_base_url),
            "github_sync_enabled": bool(github_sync.get("enabled", False)),
            "github_sync_repo_dir": str(github_sync.get("repo_dir") or "."),
            "github_sync_branch": str(github_sync.get("branch") or "main"),
            "github_sync_auto_commit": bool(github_sync.get("auto_commit", False)),
            "github_sync_auto_push": bool(github_sync.get("auto_push", False)),
            "github_sync_include_html_docs": bool(github_sync.get("include_html_docs", True)),
            "github_sync_include_markdown_notes": bool(github_sync.get("include_markdown_notes", True)),
            "github_sync_include_briefs": bool(github_sync.get("include_briefs", True)),
            "github_sync_include_transcripts": bool(github_sync.get("include_transcripts", True)),
        },
    }


def _frontend_config_to_raw(config: AppConfig, data: dict[str, Any]) -> dict[str, Any]:
    raw = deepcopy(config.raw)
    schedule = raw.setdefault("schedule", {})
    transcribe = raw.setdefault("transcribe", {})
    whisper = raw.setdefault("ai", {}).setdefault("whisper", {})
    organizer = raw.setdefault("ai", {}).setdefault("organizer", {})
    download = raw.setdefault("download", {})
    feishu = raw.setdefault("notification", {}).setdefault("channels", {}).setdefault("feishu", {})
    gpu_sched = raw.setdefault("gpu_scheduler", {})
    app_raw = raw.setdefault("app", {})
    scheduler = data.get("scheduler") or {}
    whisper_data = data.get("whisper") or {}
    ai_data = data.get("ai") or {}
    download_data = data.get("download") or {}
    feishu_data = data.get("feishu") or {}
    security_data = data.get("security") or {}
    publishing_data = data.get("publishing") or {}

    schedule["enabled"] = bool(scheduler.get("enabled", True))
    times_text = str(scheduler.get("cronExpression") or "")
    times = [item.strip() for item in times_text.replace("，", ",").split(",") if item.strip()]
    schedule["times"] = times or schedule.get("times", ["10:00", "21:00"])
    schedule["retry_interval_seconds"] = int(scheduler.get("grace_period_mins") or 5) * 60
    schedule["max_items_per_run"] = int(scheduler.get("max_concurrent_tasks") or schedule.get("max_items_per_run", 0) or 0)
    schedule["retry_times"] = int(scheduler.get("retry_times") or schedule.get("retry_times", 2) or 2)
    schedule["max_items_per_blogger"] = int(scheduler.get("max_items_per_blogger") or schedule.get("max_items_per_blogger", 0) or 0)
    schedule["manual_trigger_enabled"] = bool(scheduler.get("manual_trigger_enabled", True))

    whisper_model = str(whisper_data.get("model") or whisper.get("model", "large-v3-turbo"))
    whisper_device = str(whisper_data.get("device") or whisper.get("device", "cpu"))
    whisper_threads = int(whisper_data.get("threads") or whisper.get("cpu_threads", transcribe.get("cpu_threads_per_worker", 4)) or 4)
    whisper["model"] = whisper_model
    whisper["device"] = whisper_device
    whisper["cpu_threads"] = whisper_threads
    transcribe["model"] = whisper_model
    transcribe["device"] = whisper_device
    transcribe["cpu_threads_per_worker"] = whisper_threads
    gpu_sched["enabled"] = bool(whisper_data.get("staged_gpu_scheduling", True))
    mem_check = gpu_sched.setdefault("memory_check", {})
    mem_check["min_free_vram_mb_for_whisper_gpu"] = int(whisper_data.get("vram_offload_gb", 4) or 4) * 1000

    organizer["temperature"] = float(ai_data.get("temperature") or organizer.get("temperature", 0.2) or 0.2)
    organizer["top_p"] = float(ai_data.get("top_p") or organizer.get("top_p", 0.9) or 0.9)
    organizer["top_k"] = int(ai_data.get("top_k") or organizer.get("top_k", 40) or 40)
    organizer["request_timeout"] = int(ai_data.get("timeout_sec") or organizer.get("request_timeout", 120) or 120)
    organizer["max_tokens"] = int(ai_data.get("max_tokens") or organizer.get("max_tokens", 2048) or 2048)
    organizer["max_input_chars"] = int(ai_data.get("max_input_chars") or organizer.get("max_input_chars", 12000) or 12000)
    organizer["keep_alive"] = str(ai_data.get("keep_alive") or organizer.get("keep_alive", "10m"))
    organizer["no_think"] = bool(ai_data.get("no_think", organizer.get("no_think", True)))
    organizer["compact_prompt"] = bool(ai_data.get("compact_prompt", organizer.get("compact_prompt", True)))
    organizer["fallback_model"] = str(ai_data.get("fallback_model") or organizer.get("fallback_model", ""))
    organizer["prompt_template"] = str(ai_data.get("prompt_template") or organizer.get("prompt_template", ""))
    organizer["providers"] = organizer.get("providers") if isinstance(organizer.get("providers"), list) else [{}]
    if not organizer["providers"]:
        organizer["providers"].append({})
    organizer["providers"][0].update(
        {
            "name": organizer["providers"][0].get("name", "agnes"),
            "enabled": True,
            "api_type": str(ai_data.get("api_type") or organizer["providers"][0].get("api_type", "chat_completions")),
            "endpoint": str(ai_data.get("endpoint") or "https://apihub.agnes-ai.com/v1"),
            "model": str(ai_data.get("model") or "agnes-2.0-flash"),
            "request_timeout": int(ai_data.get("timeout_sec") or 120),
            "top_p": organizer["top_p"],
            "top_k": organizer["top_k"],
            "max_input_chars": organizer["max_input_chars"],
            "keep_alive": organizer["keep_alive"],
            "no_think": organizer["no_think"],
            "compact_prompt": organizer["compact_prompt"],
        }
    )
    organizer["endpoint"] = organizer["providers"][0]["endpoint"]
    organizer["model"] = organizer["providers"][0]["model"]
    organizer["api_type"] = organizer["providers"][0]["api_type"]

    download["path"] = str(download_data.get("path") or download.get("path", "data/Downloaded"))
    download["max_workers"] = int(download_data.get("max_workers") or download.get("max_workers", 1) or 1)
    download["batch_size"] = int(download_data.get("batch_size") or download.get("batch_size", 5) or 5)
    download["batch_cooldown_seconds"] = int(download_data.get("batch_cooldown_seconds") or download.get("batch_cooldown_seconds", 5) or 5)
    download["max_duration_seconds"] = int(download_data.get("max_duration_seconds") or download.get("max_duration_seconds", 900) or 900)
    download["retry_failed"] = bool(download_data.get("retry_failed", download.get("retry_failed", True)))
    download["circuit_breaker_failures"] = int(download_data.get("circuit_breaker_failures") or download.get("circuit_breaker_failures", 5) or 5)
    download["circuit_breaker_cooldown_seconds"] = int(
        download_data.get("circuit_breaker_cooldown_seconds") or download.get("circuit_breaker_cooldown_seconds", 300) or 300
    )
    download["save_json"] = bool(download_data.get("save_json", download.get("save_json", True)))

    feishu["message_type"] = str(feishu_data.get("message_type") or feishu.get("message_type", "card"))
    feishu["push_threshold_rating"] = float(feishu_data.get("push_threshold_rating") or feishu.get("push_threshold_rating", 7.5) or 7.5)
    feishu["retry_attempts"] = int(feishu_data.get("retry_attempts") or feishu.get("retry_attempts", 3) or 3)
    feishu["card_max_items"] = int(feishu_data.get("card_max_items") or feishu.get("card_max_items", 5) or 5)
    feishu["card_theme"] = str(feishu_data.get("card_theme") or feishu.get("card_theme", "blue"))
    webhook = str(feishu_data.get("webhook_url") or "").strip()
    if webhook:
        feishu["webhook_url"] = webhook
    app_raw["web_host"] = str(security_data.get("bind_ip") or app_raw.get("web_host", "127.0.0.1"))
    app_raw["web_port"] = int(security_data.get("port") or app_raw.get("web_port", 8765) or 8765)
    password = str(security_data.get("web_password") or "").strip()
    if password:
        app_raw["web_password"] = password
    elif not bool(security_data.get("password_auth", True)):
        app_raw["web_password"] = ""

    publishing = raw.setdefault("publishing", {})
    github_pages = publishing.setdefault("github_pages", {})
    github_sync = publishing.setdefault("github_sync", {})
    github_pages["enabled"] = bool(publishing_data.get("github_pages_enabled", github_pages.get("enabled", False)))
    github_pages["output_dir"] = str(publishing_data.get("github_pages_output_dir") or github_pages.get("output_dir") or "./docs")
    github_pages["public_base_url"] = str(publishing_data.get("github_pages_public_base_url") or github_pages.get("public_base_url") or "").strip()
    github_sync["enabled"] = bool(publishing_data.get("github_sync_enabled", github_sync.get("enabled", False)))
    github_sync["repo_dir"] = str(publishing_data.get("github_sync_repo_dir") or github_sync.get("repo_dir") or ".")
    github_sync["branch"] = str(publishing_data.get("github_sync_branch") or github_sync.get("branch") or "main")
    github_sync["auto_commit"] = bool(publishing_data.get("github_sync_auto_commit", github_sync.get("auto_commit", False)))
    github_sync["auto_push"] = bool(publishing_data.get("github_sync_auto_push", github_sync.get("auto_push", False)))
    github_sync["include_html_docs"] = bool(publishing_data.get("github_sync_include_html_docs", github_sync.get("include_html_docs", True)))
    github_sync["include_markdown_notes"] = bool(publishing_data.get("github_sync_include_markdown_notes", github_sync.get("include_markdown_notes", True)))
    github_sync["include_briefs"] = bool(publishing_data.get("github_sync_include_briefs", github_sync.get("include_briefs", True)))
    github_sync["include_transcripts"] = bool(publishing_data.get("github_sync_include_transcripts", github_sync.get("include_transcripts", True)))
    github_sync["commit_message_template"] = str(github_sync.get("commit_message_template") or "chore: publish KenRadar notes {timestamp}")
    return raw


def _mark_running_tasks_cancelled(config_path: str, reason: str) -> None:
    from kenradar.storage import create_database

    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='cancelled',
                finished_at=NOW(),
                last_error=%s,
                updated_at=NOW()
            WHERE status IN ('pending', 'running')
            """,
            (reason,),
        )
        conn.execute(
            """
            UPDATE research_job_item
            SET status='cancelled',
                error_message=%s,
                updated_at=NOW()
            WHERE status IN ('pending', 'running', 'downloading', 'downloaded', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting')
            """,
            (reason,),
        )


def _mark_research_job_cancelled(config_path: str, job_id: int, reason: str) -> None:
    from kenradar.storage import create_database

    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='cancelled',
                finished_at=NOW(),
                last_error=%s,
                updated_at=NOW()
            WHERE id = %s AND status IN ('pending', 'running')
            """,
            (reason, job_id),
        )
        conn.execute(
            """
            UPDATE research_job_item
            SET status='cancelled',
                error_message=%s,
                updated_at=NOW()
            WHERE job_id = %s AND status IN ('pending', 'running', 'downloading', 'downloaded', 'transcribing', 'transcribed_waiting_summary', 'summarizing', 'noting')
            """,
            (reason, job_id),
        )


def _mark_research_job_paused(config_path: str, job_id: int) -> None:
    from kenradar.storage import create_database

    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='paused',
                last_error='用户在 Web 后台暂停研究任务',
                updated_at=NOW()
            WHERE id = %s AND status = 'running'
            """,
            (job_id,),
        )


def _mark_research_job_resumed(config_path: str, job_id: int) -> None:
    from kenradar.storage import create_database

    config = load_config(config_path)
    database = create_database(config)
    database.initialize()
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE research_job
            SET status='running',
                last_error='',
                updated_at=NOW()
            WHERE id = %s AND status = 'paused'
            """,
            (job_id,),
        )


def _merge_manual_task_progress(progress: dict[str, Any], task_state: dict[str, Any]) -> None:
    if not task_state.get("running"):
        return
    aweme_id = str(progress.get("aweme_id") or "")
    task_id = str(task_state.get("status") or "")
    if not aweme_id or aweme_id not in task_id:
        return

    if task_id.startswith("retry-summary-"):
        stage_key = "ai"
    elif task_id.startswith("retry-transcribe-"):
        stage_key = "transcript"
    elif task_id.startswith("retry-download-"):
        stage_key = "download"
    else:
        stage_key = _first_unfinished_step(progress.get("steps") or [])

    for step in progress.get("steps") or []:
        if step.get("key") == stage_key:
            step["state"] = "running"
            step["status"] = "running"
            step["updated_at"] = str(task_state.get("started_at") or step.get("updated_at") or "")
            step["error"] = ""
        elif stage_key == "ai" and step.get("key") == "note" and step.get("state") != "success":
            step["state"] = "pending"
    progress["overall"] = "running"
    progress["manual_task"] = {
        "status": task_id,
        "message": str(task_state.get("message") or ""),
        "started_at": str(task_state.get("started_at") or ""),
    }
    progress["percent"] = int(sum(int(step.get("weight") or 0) for step in progress.get("steps") or [] if step.get("state") in {"success", "skipped"}) / 4)


def _first_unfinished_step(steps: list[dict[str, Any]]) -> str:
    for step in steps:
        if step.get("state") != "success":
            return str(step.get("key") or "download")
    return "ai"


def _start_embedded_scheduler(config_path: str) -> None:
    global _SCHEDULER_STARTED
    if _SCHEDULER_STARTED:
        return
    try:
        config = load_config(config_path)
        if not config.get("schedule.enabled", True):
            logger.info("内置调度器未启动：schedule.enabled=false")
            return
    except Exception:
        logger.exception("读取调度配置失败，内置调度器未启动")
        return

    def worker() -> None:
        from kenradar.scheduler.scheduler import run_forever_from_path

        try:
            asyncio.run(run_forever_from_path(config_path, task_lock=_TASK_LOCK))
        except Exception:
            logger.exception("内置调度器退出")

    threading.Thread(target=worker, daemon=True, name="kenradar-scheduler").start()
    _SCHEDULER_STARTED = True
    logger.info("内置调度器已随 Web 后台启动")


def update_config_from_form(config: AppConfig, form: dict[str, list[str]]) -> dict[str, Any]:
    raw = deepcopy(config.raw)
    raw.setdefault("schedule", {})
    raw.setdefault("app", {})
    raw.setdefault("output", {})
    raw.setdefault("platforms", {})
    raw.setdefault("ai", {}).setdefault("whisper", {})
    raw.setdefault("ai", {}).setdefault("organizer", {})
    raw.setdefault("download", {})
    raw.setdefault("notification", {}).setdefault("channels", {}).setdefault("feishu", {})

    raw["app"]["name"] = _field(form, "app_name", raw["app"].get("name", "KenRadar"))
    raw["app"]["data_dir"] = _field(form, "data_dir", raw["app"].get("data_dir", "./data"))
    raw["app"]["database_path"] = _field(form, "database_path", raw["app"].get("database_path", "./data/kenradar.db"))
    raw["schedule"]["enabled"] = "schedule_enabled" in form
    raw["schedule"]["times"] = [item.strip() for item in _field(form, "schedule_times").split(",") if item.strip()]
    raw["schedule"]["max_items_per_run"] = int(_field(form, "max_items_per_run", raw["schedule"].get("max_items_per_run", 0)) or 0)
    raw["schedule"]["max_items_per_blogger"] = int(_field(form, "max_items_per_blogger", raw["schedule"].get("max_items_per_blogger", 0)) or 0)
    raw["schedule"]["retry_times"] = int(_field(form, "retry_times", raw["schedule"].get("retry_times", 2)) or 0)
    raw["schedule"]["retry_interval_seconds"] = int(_field(form, "retry_interval_seconds", raw["schedule"].get("retry_interval_seconds", 300)) or 0)
    raw["schedule"]["manual_trigger_enabled"] = "manual_trigger_enabled" in form
    raw["app"]["web_base_url"] = _field(form, "web_base_url", raw["app"].get("web_base_url", "http://172.30.10.150:8765")).rstrip("/")
    web_password = _field(form, "web_password").strip()
    if web_password:
        raw["app"]["web_password"] = web_password
    raw["output"]["obsidian_root"] = _field(form, "obsidian_root", raw["output"].get("obsidian_root", "./data"))

    for platform in ("douyin", "bilibili", "xiaohongshu", "youtube"):
        raw["platforms"].setdefault(platform, {})
        raw["platforms"][platform]["enabled"] = f"platform_{platform}_enabled" in form

    whisper = raw["ai"]["whisper"]
    whisper["enabled"] = "whisper_enabled" in form
    whisper["model"] = _field(form, "whisper_model", whisper.get("model", "large-v3-turbo"))
    whisper["device"] = _field(form, "whisper_device", whisper.get("device", "cuda"))
    whisper["language"] = _field(form, "whisper_language", whisper.get("language", "zh"))
    whisper["save_json"] = "whisper_save_json" in form
    whisper["save_txt"] = "whisper_save_txt" in form
    whisper["retry_failed"] = "whisper_retry_failed" in form
    whisper["cleanup_video"] = "cleanup_video" in form

    organizer = raw["ai"]["organizer"]
    organizer["enabled"] = "organizer_enabled" in form
    organizer["temperature"] = float(_field(form, "organizer_temperature", organizer.get("temperature", 0.2)) or 0.2)
    organizer["top_p"] = float(_field(form, "organizer_top_p", organizer.get("top_p", 0.95)) or 0.95)
    organizer["top_k"] = int(_field(form, "organizer_top_k", organizer.get("top_k", 40)) or 40)
    organizer["max_tokens"] = int(_field(form, "organizer_max_tokens", organizer.get("max_tokens", 2048)))
    organizer["timeout"] = int(_field(form, "organizer_timeout", organizer.get("timeout", 60)) or 60)
    organizer["request_timeout"] = int(_field(form, "organizer_request_timeout", organizer.get("request_timeout", organizer.get("timeout", 120))) or 120)
    organizer["max_concurrent"] = int(_field(form, "organizer_max_concurrent", organizer.get("max_concurrent", 1)) or 1)
    organizer["rpm_limit"] = int(_field(form, "organizer_rpm_limit", organizer.get("rpm_limit", 40)) or 0)
    organizer["fallback_note"] = "organizer_fallback_note" in form
    existing_providers = organizer.get("providers") if isinstance(organizer.get("providers"), list) else []
    organizer["providers"] = _ai_providers_from_form(form, existing_providers, organizer)
    if organizer["providers"]:
        primary = organizer["providers"][0]
        organizer["api_type"] = primary.get("api_type", organizer.get("api_type", "chat_completions"))
        organizer["endpoint"] = primary.get("endpoint", organizer.get("endpoint", ""))
        organizer["model"] = primary.get("model", organizer.get("model", ""))
        if primary.get("api_key"):
            organizer["api_key"] = primary.get("api_key")

    raw["download"]["path"] = _field(form, "download_path", raw["download"].get("path", "./data/Downloaded/"))
    raw["download"]["max_workers"] = int(_field(form, "download_max_workers", raw["download"].get("max_workers", 5)) or 5)
    raw["download"]["batch_size"] = int(_field(form, "download_batch_size", raw["download"].get("batch_size", 6)) or 6)
    raw["download"]["batch_cooldown"] = float(_field(form, "download_batch_cooldown", raw["download"].get("batch_cooldown", 3)) or 0)
    raw["download"]["retry_failed"] = "download_retry_failed" in form
    raw["download"]["circuit_breaker_failures"] = int(_field(form, "download_circuit_breaker_failures", raw["download"].get("circuit_breaker_failures", 3)) or 3)
    raw["download"]["circuit_breaker_cooldown"] = float(_field(form, "download_circuit_breaker_cooldown", raw["download"].get("circuit_breaker_cooldown", 30)) or 0)
    raw["download"]["save_json"] = "save_json" in form
    raw["download"]["max_duration_seconds"] = int(_field(form, "max_duration_seconds", raw["download"].get("max_duration_seconds", 0)) or 0)
    raw["notification"]["enabled"] = "notification_enabled" in form
    raw["notification"].setdefault("alerts", {})["enabled"] = "alerts_enabled" in form
    raw["notification"]["channels"]["feishu"]["message_type"] = _field(form, "feishu_message_type", raw["notification"]["channels"]["feishu"].get("message_type", "auto"))
    raw["notification"]["channels"]["feishu"]["card_max_items"] = int(_field(form, "feishu_card_max_items", raw["notification"]["channels"]["feishu"].get("card_max_items", 5)) or 5)
    raw["notification"]["channels"]["feishu"]["fallback_enabled"] = "feishu_fallback_enabled" in form
    webhook = _field(form, "feishu_webhook").strip()
    if webhook:
        raw["notification"]["channels"]["feishu"]["webhook_url"] = webhook

    return raw


def _field(form: dict[str, list[str]], name: str, default: Any = "") -> str:
    if name not in form:
        return str(default or "")
    return str(form.get(name, [""])[0])


def _source_key(item: dict[str, Any]) -> str:
    return str(item.get("sec_uid") or _extract_source_sec_uid(str(item.get("url") or "")) or item.get("url") or item.get("name") or "").strip()


def _source_aliases(item: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for value in (
        item.get("source_key"),
        item.get("key"),
        item.get("sec_uid"),
        _extract_source_sec_uid(str(item.get("douyin_url") or item.get("url") or "")),
        item.get("douyin_url"),
        item.get("url"),
        item.get("nickname"),
        item.get("name"),
    ):
        text = str(value or "").strip()
        if text:
            aliases.add(text)
    return aliases


def _extract_source_sec_uid(url: str) -> str:
    match = re.search(r"/user/([^/?#]+)", url or "")
    return match.group(1) if match else ""


_DEFAULT_SOURCE_CATEGORIES = ["科技", "财经", "投资", "AI", "商业"]


def _clean_source_category(value: Any) -> str:
    return str(value or "").strip()


def _configured_source_categories(raw: dict[str, Any]) -> list[str]:
    configured = raw.get("source_categories")
    values = configured if isinstance(configured, list) else _DEFAULT_SOURCE_CATEGORIES
    categories: list[str] = []
    for value in values:
        category = _clean_source_category(value)
        if category and category not in categories:
            categories.append(category)
    return categories


def _assigned_source_categories(raw: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    bloggers = raw.get("bloggers", []) or []
    for item in bloggers if isinstance(bloggers, list) else []:
        if not isinstance(item, dict):
            continue
        category = _clean_source_category(item.get("category"))
        if category and category not in categories:
            categories.append(category)
    return categories


def _source_category_options(raw: dict[str, Any]) -> list[str]:
    categories = _configured_source_categories(raw)
    for category in _assigned_source_categories(raw):
        if category not in categories:
            categories.append(category)
    return categories


def _ai_providers_from_form(
    form: dict[str, list[str]],
    existing_providers: list[Any],
    organizer: dict[str, Any],
) -> list[dict[str, Any]]:
    providers: list[dict[str, Any]] = []
    existing_dicts = [dict(item) for item in existing_providers if isinstance(item, dict)]
    primary_existing = existing_dicts[0] if existing_dicts else {}
    for index in range(1):
        prefix = f"provider_{index}"
        existing = primary_existing
        default_name = "agnes"
        default_api_type = "chat_completions"
        default_endpoint = "https://apihub.agnes-ai.com/v1"
        default_model = "agnes-2.0-flash"
        default_env_var = "AGNES_API_KEY"
        provider = {
            "name": _field(form, f"{prefix}_name", existing.get("name", default_name)).strip() or default_name,
            "enabled": f"{prefix}_enabled" in form,
            "api_type": _field(form, f"{prefix}_api_type", existing.get("api_type", default_api_type)).strip() or default_api_type,
            "endpoint": _field(form, f"{prefix}_endpoint", existing.get("endpoint", default_endpoint)).strip(),
            "model": _field(form, f"{prefix}_model", existing.get("model", default_model)).strip(),
            "env_var": _field(form, f"{prefix}_env_var", existing.get("env_var", default_env_var)).strip(),
            "request_timeout": int(_field(form, f"{prefix}_request_timeout", existing.get("request_timeout", organizer.get("request_timeout", 120))) or 120),
            "retry_count": int(existing.get("retry_count", 3) or 3),
            "retry_delay": float(existing.get("retry_delay", 2) or 2),
            "rpm_limit": int(existing.get("rpm_limit", organizer.get("rpm_limit", 0)) or 0),
            "max_tokens": int(organizer.get("max_tokens", 4096) or 4096),
            "temperature": float(organizer.get("temperature", 0.2) or 0.2),
            "top_p": float(organizer.get("top_p", 0.9) or 0.9),
            "top_k": int(organizer.get("top_k", 0) or 0),
            "max_input_chars": int(existing.get("max_input_chars", 12000) or 12000),
            "keep_alive": str(existing.get("keep_alive", "10m") or "10m"),
            "requires_api_key": bool(existing.get("requires_api_key", True)),
            "omit_top_k": True,
            "no_think": bool(existing.get("no_think", False)),
            "compact_prompt": True,
        }
        if existing.get("system_as_user"):
            provider["system_as_user"] = True
        providers.append(provider)
    providers.extend(deepcopy(existing_dicts[1:]))
    return providers
