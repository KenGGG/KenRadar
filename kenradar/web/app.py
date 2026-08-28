from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import mimetypes
import os
import re
import subprocess
import threading
from copy import deepcopy
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from kenradar.core.config import AppConfig, hash_password, load_config, save_config
from kenradar.notification.alert import AlertManager
from kenradar.storage import create_database
from kenradar.storage.schema_guard import require_schema_current, runtime_version
from kenradar.web import task_state
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
    load_task_run_detail,
    load_task_runs,
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
    render_monitor_tasks_page,
    render_operations_page,
    render_operations_retry_page,
    render_research_job_page,
    render_sources_page,
)

from kenradar.web.helpers import (
    FRONTEND_LIBRARY_LIMIT,
    _assigned_source_categories,
    _build_frontend_bootstrap,
    _clean_source_category,
    _configured_source_categories,
    _first_unfinished_step,
    _format_aweme_time,
    _format_datetime_value,
    _format_duration,
    _frontend_alert,
    _frontend_config,
    _frontend_content_status,
    _frontend_current_stage,
    _frontend_log,
    _frontend_pipeline_steps,
    _frontend_push,
    _frontend_runtime_timeline,
    _frontend_sources,
    _frontend_stage_state,
    _frontend_system_info,
    _frontend_task,
    _frontend_transcript,
    _frontend_video,
    _frontend_video_updated_at,
    _mark_research_job_cancelled,
    _mark_research_job_paused,
    _mark_research_job_resumed,
    _mark_running_tasks_cancelled,
    _map_task_stage,
    _map_task_status,
    _merge_manual_task_progress,
    _preview_xiaoyuzhou_source,
    _readiness_status,
    _runtime_resource_for_stage,
    _runtime_stage_label,
    _safe_query,
    _source_category_options,
    _source_key,
    _source_subscription_id,
    _source_aliases,
)

logger = logging.getLogger(__name__)

_TASK_LOCK = threading.Lock()
_SCHEDULER_STARTED = False
_TASK_DISPATCHER_STARTED = False
_WEB_CONFIG_PATH = ""

def run_web(config_path: str, host: str = "127.0.0.1", port: int = 8765) -> None:
    from kenradar.storage import create_database
    from kenradar.core.source_registry import SourceRegistry

    global _WEB_CONFIG_PATH
    _WEB_CONFIG_PATH = str(config_path)
    task_state.configure(config_path)
    config = load_config(config_path)
    _validate_web_binding_security(config, host)
    require_schema_current(config_path)
    database = create_database(config)
    database.initialize()
    SourceRegistry(config, database).import_config_sources()
    task_state.start_sync(config_path)
    _start_embedded_scheduler(config_path)
    if os.getenv("KENRADAR_EMBEDDED_WORKER", "1").strip().lower() not in {"0", "false", "no"}:
        _start_task_dispatcher(config_path)

    class KenRadarHandler(BaseHTTPRequestHandler):

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path in ("/health/live", "/api/v1/health/live"):
                    self._send_json({"ok": True, "status": "live"})
                    return
                if parsed.path in ("/health/ready", "/api/v1/health/ready"):
                    self._send_json(_readiness_status(config_path))
                    return
                if parsed.path == "/api/v1/version":
                    self._send_json({"ok": True, **runtime_version(config_path)})
                    return
                if not self._authorized(config_path):
                    return
                if parsed.path.startswith("/assets/"):
                    self._send_frontend_asset(parsed.path)
                    return
                # Try route dispatcher for API routes
                if self._dispatch_route(parsed.path, method="GET", query_params=parse_qs(parsed.query), config_path=config_path):
                    return
                if parsed.path in {"/api/bootstrap", "/api/app-state"}:
                    self._send_json(_build_frontend_bootstrap(load_config(config_path)))
                    return
                if parsed.path == "/":
                    if self._send_frontend_app():
                        return
                    self._send_html(render_dashboard(load_config(config_path), task_state.current()))
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
                if parsed.path == "/logs/tasks":
                    if self._send_frontend_app():
                        return
                    query = parse_qs(parsed.query)
                    self._send_html(render_monitor_tasks_page(load_config(config_path), int(query.get("id", ["0"])[0] or 0)))
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
                if parsed.path == "/":
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
                if _should_fallback_to_frontend(parsed.path) and self._send_frontend_app():
                    return
                self.send_response(404)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("客户端在响应完成前断开: path=%s", self.path)
            except Exception as exc:
                logger.exception("Web GET failed: path=%s", self.path)
                try:
                    if parsed.path.startswith("/api") or parsed.path.startswith("/health"):
                        self._send_json({"ok": False, "message": f"服务器错误: {exc}"}, status=500)
                    else:
                        self._send_html(render_error(str(exc)), status=500)
                except (BrokenPipeError, ConnectionResetError):
                    logger.debug("客户端在错误响应完成前断开: path=%s", self.path)

        def _valid_csrf(self, config_path: str) -> bool:
            """CSRF token check (secondary defense).

            The enforced CSRF mitigation is `_valid_request_origin` (Sec-Fetch-Site
            + strict Origin/Host match). This token check remains a no-op until the
            frontend begins sending X-CSRF-Token; requiring it unconditionally today
            would break existing clients that rely on the origin gate alone.
            """
            password = load_config(config_path).web_password
            if not password:
                return True
            token = self.headers.get("X-CSRF-Token", "")
            if not token:
                return True
            expected = hash_password(password)
            return hmac.compare_digest(token, expected)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                if not self._valid_request_origin():
                    self._send_json({"ok": False, "message": "请求来源校验失败"}, status=403)
                    return
                if not self._authorized(config_path):
                    return
                if not self._valid_csrf(config_path):
                    self._send_json({"ok": False, "message": "CSRF token 无效"}, status=403)
                    return
                # Read body once — parse as both form and JSON from same raw bytes
                raw_body = self._read_raw_body()
                form = parse_qs(raw_body, keep_blank_values=True) if raw_body else {}
                data: dict[str, Any] = {}
                stripped = raw_body.strip()
                if stripped:
                    try:
                        data = json.loads(stripped)
                        if not isinstance(data, dict):
                            data = {}
                    except json.JSONDecodeError:
                        data = {}
                # Try route dispatcher first
                if self._dispatch_route(parsed.path, method="POST", form=form, data=data, config_path=config_path):
                    return
                if parsed.path == "/api/favorite":
                    self._toggle_favorite(config_path, data.get("id", ""))
                    return
                if parsed.path == "/api/curation":
                    self._update_curation(config_path, form)
                    return
                if parsed.path == "/api/restart-web":
                    self._restart_web(config_path)
                    return
                if parsed.path == "/api/config":
                    self._save_frontend_config(config_path, data)
                    return
                if parsed.path == "/api/run-once":
                    self._enqueue_task_request(config_path, "run_once", {"push": True}, "正在执行检测、下载、转录和推送")
                    return
                if parsed.path == "/api/test-latest":
                    self._enqueue_task_request(config_path, "test_latest", {"limit_per_target": 1, "push": True}, "正在测试每个博主最新内容")
                    return
                if parsed.path == "/api/task-cancel":
                    qp = parse_qs(parsed.query)
                    run_id = self._parse_int(qp.get("id", [None])[0] or None, "id")
                    if run_id is None:
                        return
                    if run_id <= 0:
                        self._send_json({"ok": False, "message": "缺少 task_run_id"}, status=400)
                        return
                    create_database(load_config(config_path)).request_task_cancel(run_id, "Web 请求取消")
                    self._send_json({"ok": True, "message": f"已请求取消任务 #{run_id}"})
                    return
                if parsed.path == "/api/retry-summary":
                    qp = parse_qs(parsed.query)
                    self._start_retry_summary(config_path, qp.get("id", [""])[0])
                    return
                if parsed.path == "/api/retry-download":
                    qp = parse_qs(parsed.query)
                    self._start_retry_stage(config_path, qp.get("id", [""])[0], "download")
                    return
                if parsed.path == "/api/retry-transcribe":
                    qp = parse_qs(parsed.query)
                    self._start_retry_stage(config_path, qp.get("id", [""])[0], "transcribe")
                    return
                if parsed.path == "/api/retry-full":
                    qp = parse_qs(parsed.query)
                    self._start_retry_stage(config_path, qp.get("id", [""])[0], "auto")
                    return
                if parsed.path == "/api/retry-batch":
                    self._start_retry_batch(config_path, form)
                    return
                if parsed.path == "/api/retry-research-failed":
                    qp = parse_qs(parsed.query)
                    job_id = self._parse_int(qp.get("id", [None])[0] or None, "id")
                    if job_id is None:
                        return
                    self._start_retry_research_failed(config_path, job_id)
                    return
                if parsed.path == "/api/research/restart":
                    qp = parse_qs(parsed.query)
                    job_id = self._parse_int(qp.get("id", [None])[0] or None, "id")
                    if job_id is None:
                        return
                    self._start_restart_research_job(config_path, job_id)
                    return
                if parsed.path == "/api/repush-aweme":
                    qp = parse_qs(parsed.query)
                    self._repush_aweme(config_path, qp.get("id", [""])[0])
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
                    self._start_research_blogger(config_path, form)
                    return
                if parsed.path == "/api/research-video":
                    self._start_research_video(config_path, form)
                    return
                if parsed.path == "/api/research/cancel":
                    qp = parse_qs(parsed.query)
                    job_id = self._parse_int(qp.get("id", [None])[0] or None, "id")
                    if job_id is None:
                        return
                    self._cancel_research_job(config_path, job_id)
                    return
                if parsed.path == "/api/research/pause":
                    qp = parse_qs(parsed.query)
                    job_id = self._parse_int(qp.get("id", [None])[0] or None, "id")
                    if job_id is None:
                        return
                    self._pause_research_job(config_path, job_id)
                    return
                if parsed.path == "/api/research/resume":
                    qp = parse_qs(parsed.query)
                    job_id = self._parse_int(qp.get("id", [None])[0] or None, "id")
                    if job_id is None:
                        return
                    self._resume_research_job(config_path, job_id)
                    return
                if parsed.path == "/config":
                    # Legacy form handler — body already read above as `form`
                    try:
                        config = load_config(config_path)
                        save_config(config, update_config_from_form(config, form))
                        self.send_response(303)
                        self.send_header("Location", "/config")
                        self.end_headers()
                    except Exception as exc:
                        logger.exception("Config update failed")
                        self._send_html(render_error(str(exc)), status=400)
                    return
                self._send_json({"ok": False, "message": "未知请求路径"}, status=404)
            except (BrokenPipeError, ConnectionResetError):
                logger.debug("客户端在响应完成前断开: path=%s", self.path)
            except Exception as exc:
                logger.exception("Web POST failed: path=%s", self.path)
                try:
                    self._send_json({"ok": False, "message": f"服务器错误: {exc}"}, status=500)
                except (BrokenPipeError, ConnectionResetError):
                    logger.debug("客户端在错误响应完成前断开: path=%s", self.path)
            return

        def _read_raw_body(self) -> str:
            length = int(self.headers.get("Content-Length", "0") or 0)
            return self.rfile.read(length).decode("utf-8") if length else ""

        def _read_form(self) -> dict[str, list[str]]:
            return parse_qs(self._read_raw_body(), keep_blank_values=True)

        def _read_json(self) -> dict[str, Any]:
            body = self._read_raw_body()
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
            password = load_config(config_path).web_password
            if not password:
                return True
            header = self.headers.get("Authorization", "")
            if header.startswith("Basic "):
                try:
                    decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
                except Exception:
                    decoded = ""
                _user, _sep, candidate = decoded.partition(":")
                # 常量时间比较（支持明文或 SHA-256 hash）
                stored_hash = hash_password(candidate)
                if hmac.compare_digest(stored_hash, hash_password(password)):
                    return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="KenRadar"')
            self.end_headers()
            return False

        def _valid_request_origin(self) -> bool:
            """CSRF defense for state-changing requests.

            Modern browsers attach Sec-Fetch-Site to navigational/fetch requests:
            cross-site requests are rejected outright. When Origin is present it
            must match Host. Requests without either header (curl, server-side
            tools, legacy same-origin form posts) are allowed.
            """
            fetch_site = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
            if fetch_site == "cross-site":
                return False
            origin = str(self.headers.get("Origin") or "").strip()
            if not origin:
                return True
            parsed = urlparse(origin)
            host = str(self.headers.get("Host") or "").lower()
            return bool(parsed.netloc) and parsed.netloc.lower() == host

        def _parse_int(self, raw: str | None, name: str) -> int | None:
            """Parse a query/form int param, returning None and a 400 on failure.

            Callers must `return` after a None result (response already sent).
            """
            if raw is None:
                return None
            try:
                return int(raw)
            except (TypeError, ValueError):
                self._send_json({"ok": False, "message": f"参数 {name} 必须是整数"}, status=400)
                return None

        def _enqueue_task_request(self, config_path: str, task_type: str, payload: dict[str, Any], message: str, *, force: bool = False) -> None:
            if force:
                logger.warning("收到 force 启动请求，已降级为持久队列排队: task_type=%s", task_type)
            queued = task_state.enqueue(config_path, task_type, payload, message, requested_by="web")
            task_state.sync(config_path)
            self._send_json(
                {
                    "ok": True,
                    "queued": True,
                    "task_id": task_type,
                    "task_run_id": queued["run_id"],
                    "queue_position": queued["queue_position"],
                    "message": f"任务已加入持久队列（第 {queued['queue_position']} 位）",
                    "state": task_state.current(),
                },
                status=202,
            )

        def _start_retry_summary(self, config_path: str, aweme_id: str) -> None:
            if not aweme_id:
                self._send_json({"ok": False, "message": "缺少 aweme_id"}, status=400)
                return

            self._enqueue_task_request(config_path, "retry_summary", {"aweme_id": aweme_id}, "正在重试 AI 整理和笔记生成")

        def _start_retry_stage(self, config_path: str, aweme_id: str, retry_from: str) -> None:
            if not aweme_id:
                self._send_json({"ok": False, "message": "缺少 aweme_id"}, status=400)
                return

            labels = {"download": "正在从下载阶段重试", "transcribe": "正在从转录阶段重试", "auto": "正在执行全流程智能重试"}
            task_type = {"download": "retry_download", "transcribe": "retry_transcribe"}.get(retry_from, "retry_full")
            self._enqueue_task_request(config_path, task_type, {"aweme_id": aweme_id}, labels.get(retry_from, "正在重试"))

        def _start_retry_batch(self, config_path: str, form: dict[str, list[str]]) -> None:
            raw_ids = ",".join(form.get("aweme_ids", []))
            aweme_ids = [item.strip() for item in raw_ids.replace("\n", ",").split(",") if item.strip()]
            retry_from = _field(form, "retry_from", "auto").strip() or "auto"
            if not aweme_ids:
                self._send_json({"ok": False, "message": "请选择要重试的内容"}, status=400)
                return

            self._enqueue_task_request(
                config_path,
                "retry_batch",
                {"aweme_ids": aweme_ids, "retry_from": retry_from},
                f"正在批量重试 {len(aweme_ids)} 条内容",
            )

        def _start_retry_research_failed(self, config_path: str, job_id: int) -> None:
            if job_id <= 0:
                self._send_json({"ok": False, "message": "缺少 job_id"}, status=400)
                return

            self._enqueue_task_request(config_path, "retry_research_failed", {"job_id": job_id}, f"正在重跑研究任务 #{job_id} 的失败条目")

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

            self._enqueue_task_request(
                config_path,
                "restart_research_job",
                {"job_id": job_id},
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

            self._enqueue_task_request(
                config_path,
                "research_blogger",
                {"blogger": blogger, "limit": limit, "push": push, "force": force, "since": since, "until": until},
                f"正在研究博主：{blogger}",
            )

        def _start_research_video(self, config_path: str, form: dict[str, list[str]]) -> None:
            video = _field(form, "video").strip()
            aweme_id = _field(form, "aweme_id").strip()
            if not video and not aweme_id:
                self._send_json({"ok": False, "message": "请输入视频链接或 aweme_id"}, status=400)
                return
            force = "force" in form
            push = "push" in form
            label = aweme_id or video[:64]

            self._enqueue_task_request(
                config_path,
                "research_video",
                {"video": video, "aweme_id": aweme_id, "push": push, "force": force},
                f"正在研究单个视频：{label}",
            )

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
                task_state.sync(config_path)
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
                task_state.sync(config_path)
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
                task_state.sync(config_path)
                self._send_json({"ok": True, "message": "已请求暂停，当前下载/转录/AI 单步结束后暂停"})
            except Exception as exc:
                logger.exception("Pause research job failed")
                self._send_json({"ok": False, "message": str(exc)}, status=500)

        def _resume_research_job(self, config_path: str, job_id: int) -> None:
            if job_id <= 0:
                self._send_json({"ok": False, "message": "缺少 job_id"}, status=400)
                return

            self._enqueue_task_request(
                config_path,
                "restart_research_job",
                {"job_id": job_id},
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
                subscription_id = _source_subscription_id(source_id)
                if subscription_id:
                    database = create_database(config)
                    subscription = database.get_source_subscription(subscription_id)
                    if not subscription:
                        raise ValueError("未找到要切换的订阅源")
                    enabled = not bool(subscription.get("enabled"))
                    database.set_source_subscription_enabled(subscription_id, enabled)
                    _mirror_douyin_subscription(config, subscription, enabled=enabled)
                    self._send_json({"ok": True, "enabled": enabled})
                    return
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
                subscription_id = _source_subscription_id(source_id)
                if subscription_id:
                    database = create_database(config)
                    subscription = database.get_source_subscription(subscription_id)
                    database.delete_source_subscription(subscription_id)
                    if subscription:
                        _mirror_douyin_subscription(config, subscription, remove=True)
                    self._send_json({"ok": True, "message": "订阅源已删除"})
                    return
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
            if str(data.get("platform") or "douyin").strip() == "xiaoyuzhou":
                self._add_xiaoyuzhou_source_json(config_path, data)
                return
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

        def _preview_source_json(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                platform = str(data.get("platform") or "").strip()
                url = str(data.get("url") or "").strip()
                if platform != "xiaoyuzhou":
                    raise ValueError("当前仅支持预览小宇宙来源")
                preview = _preview_xiaoyuzhou_source(load_config(config_path), url)
                self._send_json({"ok": True, "preview": preview})
            except Exception as exc:
                logger.exception("Preview source failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _add_xiaoyuzhou_source_json(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                config = load_config(config_path)
                url = str(data.get("url") or "").strip()
                category = str(data.get("category") or "").strip()
                preview = _preview_xiaoyuzhou_source(config, url)
                database = create_database(config)
                source = database.upsert_source_subscription(
                    platform="xiaoyuzhou",
                    source_type=str(preview.get("source_type") or "feed"),
                    source_key=str(preview.get("source_key") or url),
                    display_name=str(data.get("name") or preview.get("display_name") or "小宇宙来源"),
                    source_url=str(preview.get("source_url") or url),
                    feed_url=str(preview.get("feed_url") or ""),
                    category=category,
                    enabled=bool(data.get("enabled", True)),
                    extra={"preview": preview},
                )
                self._send_json({"ok": True, "message": "小宇宙来源已登记", "source": source})
            except Exception as exc:
                logger.exception("Add xiaoyuzhou source failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _check_source_json(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                source_id = str(data.get("id") or "").strip()
                subscription_id = _source_subscription_id(source_id)
                if not subscription_id:
                    raise ValueError("当前仅支持检查小宇宙订阅源")
                publish = bool(data.get("publish", False))
                push = bool(data.get("push", False))
                limit = int(data.get("limit") or 0)
                self._enqueue_task_request(
                    config_path,
                    "monitor_xiaoyuzhou_sources",
                    {"subscription_id": subscription_id, "limit": limit, "publish": publish, "push": push},
                    f"正在检查小宇宙订阅源 #{subscription_id}",
                )
            except Exception as exc:
                logger.exception("Check source failed")
                self._send_json({"ok": False, "message": str(exc)}, status=400)

        def _update_source_category(self, config_path: str, data: dict[str, Any]) -> None:
            try:
                source_id = str(data.get("id") or "").strip()
                if not source_id:
                    raise ValueError("缺少来源 ID")
                category = str(data.get("category") or "").strip()
                config = load_config(config_path)
                subscription_id = _source_subscription_id(source_id)
                if subscription_id:
                    database = create_database(config)
                    subscription = database.get_source_subscription(subscription_id)
                    database.update_source_subscription_category(subscription_id, category)
                    if subscription:
                        _mirror_douyin_subscription(config, subscription, category=category)
                    self._send_json({"ok": True, "category": category})
                    return
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

    # Initialize route modules
    from kenradar.web.router import init_routes
    init_routes(KenRadarHandler)

    server = ThreadingHTTPServer((host, port), KenRadarHandler)
    logger.info("KenRadar 控制台已启动: http://%s:%s", host, port)
    server.serve_forever()


def _start_task_dispatcher(config_path: str) -> None:
    global _TASK_DISPATCHER_STARTED
    if _TASK_DISPATCHER_STARTED:
        return

    def worker() -> None:
        from kenradar.jobs.worker import TaskWorker

        TaskWorker(config_path, worker_name="web-embedded-worker").run_forever()

    threading.Thread(target=worker, daemon=True, name="kenradar-task-dispatcher").start()
    _TASK_DISPATCHER_STARTED = True
    logger.info("持久任务调度器已启动")


def _run_claimed_task(config_path: str, run_id: int, task_type: str, payload: dict[str, Any], message: str) -> None:
    from kenradar.core.workflow import Workflow

    heartbeat_stop = threading.Event()

    def heartbeat_worker() -> None:
        while not heartbeat_stop.wait(30.0):
            try:
                config = load_config(config_path)
                create_database(config).heartbeat_task_run(run_id, lease_seconds=300)
                task_state.sync(config_path)
            except Exception:
                logger.exception("任务心跳更新失败: run_id=%s", run_id)

    _TASK_LOCK.acquire()
    threading.Thread(target=heartbeat_worker, daemon=True, name=f"kenradar-task-heartbeat-{run_id}").start()
    try:
        config = load_config(config_path)
        create_database(config).heartbeat_task_run(run_id, lease_seconds=300)
        task_state.sync(config_path)
        logger.info("持久任务开始执行: run_id=%s task_type=%s", run_id, task_type)
        stats = asyncio.run(_execute_task_run(Workflow(config), task_type, payload, config_path=config_path, run_id=run_id))
        create_database(config).complete_task_run(run_id, stats=stats)
        logger.info("持久任务执行完成: run_id=%s task_type=%s stats=%s", run_id, task_type, stats)
    except Exception as exc:
        try:
            config = load_config(config_path)
            create_database(config).fail_task_run(run_id, str(exc))
            AlertManager(config, create_database(config)).error(
                "web_task",
                str(exc),
                title=message or task_type or "后台任务",
                context={"task_type": task_type, "task_run_id": run_id},
            )
        except Exception:
            logger.exception("持久任务失败后写库/告警失败: run_id=%s", run_id)
        logger.exception("持久任务执行失败: run_id=%s task_type=%s", run_id, task_type)
    finally:
        heartbeat_stop.set()
        _TASK_LOCK.release()
        task_state.sync(config_path)


async def _execute_task_run(workflow: Any, task_type: str, payload: dict[str, Any], config_path: str = "", run_id: int = 0) -> dict[str, Any]:
    from kenradar.jobs.handlers import execute_task_run

    def on_progress(current: int, total: int, aweme_id: str, stage: str, progress_message: str) -> None:
        progress = {
            "total": total,
            "current": current,
            "aweme_id": aweme_id,
            "stage": stage,
            "message": progress_message,
        }
        if config_path and run_id > 0:
            create_database(load_config(config_path)).heartbeat_task_run(run_id, lease_seconds=300, progress=progress)
            task_state.sync(config_path)

    progress_callback = on_progress
    return await execute_task_run(workflow, task_type, payload, progress_callback=progress_callback)


def _frontend_dist_dir() -> Path:
    return Path(__file__).resolve().parent / "frontend" / "dist"


def _upsert_source_from_form(config_path: str, form: dict[str, list[str]]) -> dict[str, Any]:
    from kenradar.core.source_resolver import resolve_douyin_source
    from kenradar.storage import create_database

    config = load_config(config_path)
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
    database = create_database(config)
    creator_id = database.upsert_blogger(
        url=resolved.url,
        name=resolved.name,
        sec_uid=resolved.sec_uid,
        enabled=source["enabled"],
    )
    subscription = database.upsert_source_subscription(
        platform="douyin",
        source_type="creator",
        source_key=resolved.sec_uid,
        display_name=resolved.name,
        source_url=resolved.url,
        category=source["category"],
        enabled=source["enabled"],
        extra={"creator_id": creator_id, "managed_by_web": True},
    )
    raw = deepcopy(config.raw)
    raw.setdefault("bloggers", [])
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
    return {**source, "id": f"sub:{subscription.get('id')}"}


_SOURCE_FIELD_UNSET = object()


def _mirror_douyin_subscription(
    config: AppConfig,
    subscription: dict[str, Any],
    *,
    enabled: bool | object = _SOURCE_FIELD_UNSET,
    category: str | object = _SOURCE_FIELD_UNSET,
    remove: bool = False,
) -> None:
    if str(subscription.get("platform") or "") != "douyin":
        return
    source_key = str(subscription.get("source_key") or "").strip()
    if not source_key:
        return
    raw = deepcopy(config.raw)
    bloggers = raw.setdefault("bloggers", [])
    matching = [
        item for item in bloggers
        if isinstance(item, dict) and str(item.get("sec_uid") or "").strip() == source_key
    ]
    if remove:
        raw["bloggers"] = [item for item in bloggers if item not in matching]
    else:
        if not matching:
            matching = [{
                "platform": "douyin",
                "sec_uid": source_key,
                "name": str(subscription.get("display_name") or source_key),
                "url": str(subscription.get("source_url") or ""),
                "enabled": bool(subscription.get("enabled")),
            }]
            bloggers.extend(matching)
        for item in matching:
            if enabled is not _SOURCE_FIELD_UNSET:
                item["enabled"] = bool(enabled)
            if category is not _SOURCE_FIELD_UNSET:
                if str(category):
                    item["category"] = str(category)
                else:
                    item.pop("category", None)
    save_config(config, raw)


def _should_fallback_to_frontend(path: str) -> bool:
    if not path or path == "/":
        return False
    blocked_prefixes = ("/api/", "/assets/", "/static/", "/health/", "/logs/", "/sources/", "/file")
    blocked_exact = {
        "/api",
        "/assets",
        "/static",
        "/health",
        "/logs",
        "/sources",
        "/config",
        "/run",
        "/operations",
        "/operations/retry",
        "/aweme",
        "/research/jobs",
    }
    if path in blocked_exact or path.startswith(blocked_prefixes):
        return False
    if Path(path).suffix:
        return False
    return True


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
            "model": str(ai_data.get("model") or "agnes-2.5-flash"),
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
    github_pages["output_dir"] = str(publishing_data.get("github_pages_output_dir") or github_pages.get("output_dir") or "./data/github-pages")
    github_pages["public_base_url"] = str(publishing_data.get("github_pages_public_base_url") or github_pages.get("public_base_url") or "").strip()
    github_sync["enabled"] = bool(publishing_data.get("github_sync_enabled", github_sync.get("enabled", False)))
    github_sync["repo_dir"] = str(publishing_data.get("github_sync_repo_dir") or github_sync.get("repo_dir") or "./data/github-pages")
    github_sync["branch"] = str(publishing_data.get("github_sync_branch") or github_sync.get("branch") or "gh-pages")
    github_sync["auto_commit"] = bool(publishing_data.get("github_sync_auto_commit", github_sync.get("auto_commit", False)))
    github_sync["auto_push"] = bool(publishing_data.get("github_sync_auto_push", github_sync.get("auto_push", False)))
    github_sync["include_html_docs"] = bool(publishing_data.get("github_sync_include_html_docs", github_sync.get("include_html_docs", True)))
    github_sync["include_markdown_notes"] = bool(publishing_data.get("github_sync_include_markdown_notes", github_sync.get("include_markdown_notes", False)))
    github_sync["include_briefs"] = bool(publishing_data.get("github_sync_include_briefs", github_sync.get("include_briefs", False)))
    github_sync["include_transcripts"] = bool(publishing_data.get("github_sync_include_transcripts", github_sync.get("include_transcripts", False)))
    github_sync["commit_message_template"] = str(github_sync.get("commit_message_template") or "chore: publish KenRadar notes {timestamp}")
    return raw


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


def _validate_web_binding_security(config: AppConfig, host: str) -> None:
    if _is_loopback_host(host):
        return
    if not str(config.web_password or "").strip():
        raise RuntimeError(
            "拒绝在非回环地址启动未受保护的 Web 控制台；"
            "请设置 KENRADAR_WEB_PASSWORD/app.web_password，"
            "或使用 --host 127.0.0.1"
        )


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"}


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


def _extract_source_sec_uid(url: str) -> str:
    match = re.search(r"/user/([^/?#]+)", url or "")
    return match.group(1) if match else ""


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
        default_model = "agnes-2.5-flash"
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
