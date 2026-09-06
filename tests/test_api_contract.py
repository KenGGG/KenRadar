"""
Contract tests for KenRadar core API endpoints.

Tests HTTP method, URL, query parameters, response status codes,
top-level fields, error formats, and Content-Type for the core API surface.

Dynamic fields (timestamps, IDs) are validated for type/existence only.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Test harness — fake HTTP handler that captures responses
# ---------------------------------------------------------------------------

class _FakeServer:
    """Dummy server for BaseHTTPRequestHandler init."""
    def handle_timeout(self) -> None:
        pass


class _FakeHandler(BaseHTTPRequestHandler):
    """Minimal BaseHTTPRequestHandler subclass that captures responses."""

    def __init__(self) -> None:
        self._buffer = io.BytesIO()
        self._headers_list: list[tuple[str, str]] = []
        self._status = 200
        self._sent_data: bytes = b""
        # Override the base class __init__ to avoid socket setup
        self.client_address = ("127.0.0.1", 0)
        self.server = _FakeServer()
        self.request = b""
        self.rfile = io.BytesIO(b"")
        self.wfile_attr = self._buffer
        self.close_connection = True

    def send_response(self, code: int, message: str | None = None) -> None:  # type: ignore[override]
        self._status = code
        self.send_response_only(code, message)

    def send_response_only(self, code: int, message: str | None = None) -> None:
        pass

    def send_header(self, keyword: str, value: str) -> None:
        self._headers_list.append((keyword, value))

    def end_headers(self) -> None:
        pass

    @property
    def wfile(self) -> io.BytesIO:  # type: ignore[override]
        return self._buffer

    def get_body(self) -> bytes:
        pos = self._buffer.tell()
        self._buffer.seek(0)
        data = self._buffer.read()
        self._buffer.seek(pos)
        return data

    def log_request(self, code: int = "-", size: int = "-") -> None:
        pass

    def log_error(self, *args: Any) -> None:
        pass


def _parse_response(fh: _FakeHandler) -> tuple[int, dict[str, str], dict[str, Any] | None]:
    """Return (status, headers_dict, parsed_json_body)."""
    headers_dict = {k.lower(): v for k, v in fh._headers_list}
    body_text = fh.get_body().decode("utf-8") if fh._buffer.tell() > 0 else ""
    body: dict[str, Any] | None = None
    if body_text:
        try:
            body = json.loads(body_text)
        except json.JSONDecodeError:
            body = None
    return fh._status, headers_dict, body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONFIG_PATH = "config/config.yaml"


def _ensure_test_config(tmp_path: Path) -> str:
    """Ensure a minimal config.yaml exists for testing."""
    # Contract tests must not open the developer's PostgreSQL connection or
    # probe their configured provider endpoints.
    tmp_cfg = tmp_path / "kenradar-api-contract-config.yaml"
    tmp_cfg.write_text(
        "app:\n  data_dir: ./data\n  web_port: 8765\n"
        "schedule:\n  enabled: true\n  times:\n    - \"10:00\"\n"
        "ai:\n  organizer:\n    providers: []\n"
        "download:\n  path: ./data/Downloaded\n",
        encoding="utf-8",
    )
    return str(tmp_cfg)


# ---------------------------------------------------------------------------
# 1. /health/live
# ---------------------------------------------------------------------------

class TestHealthLive:
    def test_returns_200(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_live
        _handle_health_live(fh)
        status, headers, body = _parse_response(fh)
        assert status == 200
        assert body == {"ok": True, "status": "live"}

    def test_content_type_json(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_live
        _handle_health_live(fh)
        _, headers, _ = _parse_response(fh)
        assert "content-type" in headers
        assert "application/json" in headers["content-type"]


# ---------------------------------------------------------------------------
# 2. /health/ready
# ---------------------------------------------------------------------------

class TestHealthReady:
    def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_ready
        monkeypatch.setattr(
            "kenradar.web.helpers._readiness_status",
            lambda _path: {"ok": True, "status": "ready", "checks": {}},
        )
        cfg_path = _ensure_test_config(Path("/tmp"))
        _handle_health_ready(fh, cfg_path)
        status, headers, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        assert "ok" in body
        assert "status" in body
        assert "checks" in body
        assert isinstance(body["ok"], bool)
        assert isinstance(body["status"], str)
        assert isinstance(body["checks"], dict)

    def test_status_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_ready
        monkeypatch.setattr(
            "kenradar.web.helpers._readiness_status",
            lambda _path: {"ok": False, "status": "not_ready", "checks": {}},
        )
        cfg_path = _ensure_test_config(Path("/tmp"))
        _handle_health_ready(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        assert body["status"] in ("ready", "not_ready")


# ---------------------------------------------------------------------------
# 3. /health/dependencies
# ---------------------------------------------------------------------------

class TestHealthDependencies:
    def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_dependencies
        monkeypatch.setattr(
            "kenradar.web.dependency_health.dependency_status",
            lambda _config: {"all_ok": True, "degraded": False, "dependencies": {}},
        )
        cfg_path = _ensure_test_config(Path("/tmp"))
        _handle_health_dependencies(fh, cfg_path)
        status, headers, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        assert "elapsed_ms" in body
        assert isinstance(body["elapsed_ms"], (int, float))
        assert "all_ok" in body
        assert isinstance(body["all_ok"], bool)


# ---------------------------------------------------------------------------
# 4. /api/bootstrap
# ---------------------------------------------------------------------------

class TestBootstrap:
    def _get_config_path(self, tmp_path: Path) -> str:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app:\n  data_dir: ./data\n  web_port: 8765\n"
            "schedule:\n  enabled: true\n  times:\n    - \"10:00\"\n"
            "ai:\n  organizer:\n    providers: []\n"
            "download:\n  path: ./data/Downloaded\n"
            "notification:\n  channels:\n    feishu:\n      webhook_url: ''\n"
            "publishing:\n  github_pages:\n    enabled: false\n"
            "  github_sync:\n    enabled: false\n",
            encoding="utf-8",
        )
        return str(cfg)

    def test_returns_200(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_bootstrap
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_bootstrap(fh, cfg_path)
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None

    def test_has_required_fields(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_bootstrap
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_bootstrap(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        # Core fields must exist
        assert "videos" in body
        assert "tasks" in body
        assert "sources" in body
        assert "config" in body
        assert "system" in body
        assert "highValueThreshold" in body
        assert "libraryStats" in body

    def test_high_value_threshold_is_number(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_bootstrap
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_bootstrap(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        hv = body.get("highValueThreshold")
        assert hv is not None
        assert isinstance(hv, (int, float))
        assert hv > 0

    def test_videos_are_list(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_bootstrap
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_bootstrap(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        assert isinstance(body["videos"], list)

    def test_bootstrap_is_bounded_and_defers_archive_payloads(self, monkeypatch, tmp_path: Path) -> None:
        from kenradar.web import helpers
        from kenradar.core.config import load_config

        config = load_config(self._get_config_path(tmp_path))
        monkeypatch.setattr(helpers, "load_content_rows", lambda config, limit: [{"aweme_id": str(i)} for i in range(limit)])
        monkeypatch.setattr(helpers, "_frontend_content", lambda config, row, failure=None: {"id": row["aweme_id"], "summary_markdown": ""})
        monkeypatch.setattr(helpers, "_frontend_sources", lambda config: [])
        monkeypatch.setattr(helpers, "_frontend_system_info", lambda config: {})
        monkeypatch.setattr(helpers, "load_library_counts", lambda config: {"total_items": 5000})

        payload = helpers._build_frontend_bootstrap(config)

        assert len(payload["videos"]) <= 30
        assert payload["notes"] == []
        assert payload["briefs"] == []
        assert payload["logs"] == []

    def test_config_has_expected_structure(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_bootstrap
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_bootstrap(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        cfg = body.get("config")
        assert cfg is not None
        assert isinstance(cfg, dict)
        for key in ("scheduler", "whisper", "ai", "download", "feishu", "security", "publishing"):
            assert key in cfg, f"config missing key: {key}"


class TestArchiveFiles:
    def test_rejects_unknown_kind(self) -> None:
        from kenradar.web.routes.dashboard import _handle_archive_files

        fh = _FakeHandler()
        _handle_archive_files(fh, CONFIG_PATH, {"kind": ["secrets"]})
        status, _, body = _parse_response(fh)

        assert status == 400
        assert body == {"ok": False, "message": "kind 仅支持 notes 或 briefs"}

    def test_returns_metadata_for_selected_kind(self, monkeypatch) -> None:
        from kenradar.web.routes import dashboard

        monkeypatch.setattr("kenradar.web.queries.load_note_files", lambda config: [{"path": "a.md", "title": "A"}])
        fh = _FakeHandler()
        dashboard._handle_archive_files(fh, CONFIG_PATH, {"kind": ["notes"]})
        status, _, body = _parse_response(fh)

        assert status == 200
        assert body == {"ok": True, "kind": "notes", "items": [{"path": "a.md", "title": "A"}]}

# ---------------------------------------------------------------------------
# 5. /api/status
# ---------------------------------------------------------------------------

class TestStatus:
    @pytest.fixture(autouse=True)
    def _isolate_runtime_queries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kenradar.web import helpers, task_state

        monkeypatch.setattr(task_state, "sync", lambda _path: task_state.current())
        monkeypatch.setattr(helpers, "_frontend_runtime_timeline", lambda _config: {})

    def _get_config_path(self, tmp_path: Path) -> str:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app:\n  data_dir: ./data\n  web_port: 8765\n"
            "schedule:\n  enabled: true\n  times:\n    - \"10:00\"\n"
            "ai:\n  organizer:\n    providers: []\n"
            "download:\n  path: ./data/Downloaded\n"
            "transcribe:\n  model: large-v3-turbo\n"
            "publishing:\n  github_pages:\n    enabled: false\n"
            "  github_sync:\n    enabled: false\n",
            encoding="utf-8",
        )
        return str(cfg)

    def test_returns_json(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_status
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_status(fh, cfg_path)
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None

    def test_has_running_field(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_status
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_status(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "running" in body
        assert isinstance(body["running"], bool)

    def test_has_runtime_timeline(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_status
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_status(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "runtime_timeline" in body
        rt = body["runtime_timeline"]
        assert isinstance(rt, dict)
        if rt:  # non-empty
            for key in ("entries", "locks", "lanes", "progress_percent"):
                assert key in rt, f"runtime_timeline missing: {key}"


# ---------------------------------------------------------------------------
# 6. Removed V1 collection/detail/progress endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# M1-2: /api/content-items cursor pagination unit tests
# ---------------------------------------------------------------------------

class TestCursorPagination:
    """Test cursor encoding/decoding contract for /api/content-items."""

    def test_encode_decode_roundtrip(self) -> None:
        from kenradar.web.queries import _encode_cursor, _decode_cursor
        sv, iid = 4.2, 12345
        encoded = _encode_cursor(sv, iid)
        assert isinstance(encoded, str)
        assert len(encoded) > 0
        decoded_sv, decoded_iid = _decode_cursor(encoded)
        assert abs(float(decoded_sv) - sv) < 0.001
        assert int(decoded_iid) == iid

    def test_encode_produces_base64_url_safe(self) -> None:
        from kenradar.web.queries import _encode_cursor
        encoded = _encode_cursor(1.0, 0)
        # base64url uses A-Z, a-z, 0-9, -, _ (no padding)
        import re
        assert re.match(r"^[A-Za-z0-9\-_]+$", encoded)

    def test_decode_invalid_cursor_raises(self) -> None:
        from kenradar.web.queries import _decode_cursor
        with pytest.raises(Exception):
            _decode_cursor("not-valid-base64!!!")

    def test_decode_truncated_padding_works(self) -> None:
        """Cursor without padding should still decode correctly."""
        from kenradar.web.queries import _encode_cursor, _decode_cursor
        encoded = _encode_cursor(3.5, 999)
        # Truncate any trailing '=' that base64 might add
        stripped = encoded.rstrip("=")
        sv, iid = _decode_cursor(stripped)
        assert abs(sv - 3.5) < 0.001
        assert iid == 999

    def test_cursor_is_opaque(self) -> None:
        """Different (sort_value, id) pairs should produce different cursors."""
        from kenradar.web.queries import _encode_cursor
        c1 = _encode_cursor(1.0, 1)
        c2 = _encode_cursor(1.0, 2)
        c3 = _encode_cursor(2.0, 1)
        assert c1 != c2
        assert c1 != c3
        assert c2 != c3


# ---------------------------------------------------------------------------
# 9. /api/content
# ---------------------------------------------------------------------------

class TestContentDetail:
    def test_rejects_missing_locator(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.content_detail import _handle_content_detail
        _handle_content_detail(fh, "config/config.yaml", {})
        status, _, body = _parse_response(fh)
        assert status == 400
        assert body is not None
        assert body["ok"] is False

# ---------------------------------------------------------------------------
# 11. /api/task-runs
# ---------------------------------------------------------------------------

class TestTaskRuns:
    @pytest.fixture(autouse=True)
    def _isolate_task_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from kenradar.web.routes import dashboard

        monkeypatch.setattr(dashboard, "load_task_runs", lambda _config, **_kwargs: [])
    def _get_config_path(self, tmp_path: Path) -> str:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app:\n  data_dir: ./data\n  web_port: 8765\n"
            "schedule:\n  enabled: true\n  times:\n    - \"10:00\"\n"
            "ai:\n  organizer:\n    providers: []\n"
            "download:\n  path: ./data/Downloaded\n"
            "transcribe:\n  model: large-v3-turbo\n"
            "publishing:\n  github_pages:\n    enabled: false\n"
            "  github_sync:\n    enabled: false\n",
            encoding="utf-8",
        )
        return str(cfg)

    def test_returns_json(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_task_runs
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_task_runs(fh, cfg_path)
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        assert "items" in body
        assert isinstance(body["items"], list)


# ---------------------------------------------------------------------------
# 12. /api/research/job
# ---------------------------------------------------------------------------

class TestResearchJob:
    @pytest.fixture(autouse=True)
    def _isolate_research_job_queries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("kenradar.web.queries.load_research_job", lambda _config, _id: None)
        monkeypatch.setattr("kenradar.web.queries.load_research_job_items", lambda _config, _id, **_kwargs: [])
        monkeypatch.setattr("kenradar.web.queries.load_research_pipeline_stats", lambda _config, _id: {})
    def _get_config_path(self, tmp_path: Path) -> str:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app:\n  data_dir: ./data\n  web_port: 8765\n"
            "schedule:\n  enabled: true\n  times:\n    - \"10:00\"\n"
            "ai:\n  organizer:\n    providers: []\n"
            "download:\n  path: ./data/Downloaded\n"
            "transcribe:\n  model: large-v3-turbo\n"
            "publishing:\n  github_pages:\n    enabled: false\n"
            "  github_sync:\n    enabled: false\n",
            encoding="utf-8",
        )
        return str(cfg)

    def test_returns_json(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.research import _handle_research_job_get
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_research_job_get(fh, cfg_path, {"id": ["0"]})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        assert "job" in body
        assert "items" in body
        assert "pipeline" in body


# ---------------------------------------------------------------------------
# 13. /api/dashboard/overview
# ---------------------------------------------------------------------------

class TestDashboardOverview:
    def _get_config_path(self, tmp_path: Path) -> str:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app:\n  data_dir: ./data\n  web_port: 8765\n"
            "schedule:\n  enabled: true\n  times:\n    - \"10:00\"\n"
            "ai:\n  organizer:\n    providers: []\n"
            "download:\n  path: ./data/Downloaded\n"
            "transcribe:\n  model: large-v3-turbo\n"
            "publishing:\n  github_pages:\n    enabled: false\n"
            "  github_sync:\n    enabled: false\n",
            encoding="utf-8",
        )
        return str(cfg)

    def test_returns_json(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_dashboard_overview(fh, cfg_path, {})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None

    def test_has_summary(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_dashboard_overview(fh, cfg_path, {})
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "summary" in body
        s = body["summary"]
        assert isinstance(s, dict)
        for key in ("today_new", "high_value_pending", "failed", "processing"):
            assert key in s, f"summary missing: {key}"
            assert isinstance(s[key], int), f"summary.{key} should be int"

    def test_has_pipeline(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_dashboard_overview(fh, cfg_path, {})
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "pipeline" in body
        p = body["pipeline"]
        assert isinstance(p, dict)
        for key in ("downloading", "transcribing", "ai_waiting", "push_waiting", "success", "failed"):
            assert key in p, f"pipeline missing: {key}"
            assert isinstance(p[key], int), f"pipeline.{key} should be int"

    def test_has_daily_trend(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_dashboard_overview(fh, cfg_path, {"days": ["7"]})
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "dailyTrend" in body
        dt = body["dailyTrend"]
        assert isinstance(dt, list)
        if dt:
            first = dt[0]
            for key in ("date", "total", "highValue", "pushed", "confirmed"):
                assert key in first, f"dailyTrend item missing: {key}"

    def test_has_score_distribution(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_dashboard_overview(fh, cfg_path, {})
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "scoreDistribution" in body
        sd = body["scoreDistribution"]
        assert isinstance(sd, list)

    def test_has_high_value_threshold(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_dashboard_overview(fh, cfg_path, {})
        _, _, body = _parse_response(fh)
        assert body is not None
        hv = body.get("highValueThreshold")
        assert hv is not None
        assert isinstance(hv, (int, float))
        assert hv > 0


# ---------------------------------------------------------------------------
# 11. /api/task-pause and /api/task-resume
# ---------------------------------------------------------------------------

class TestTaskControlRoutes:
    """Contract tests for durable task pause/resume endpoints."""

    @staticmethod
    def _config_path(tmp_path: Path) -> str:
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "app:\n  data_dir: ./data\n  web_port: 8765\n"
            "schedule:\n  enabled: false\n"
            "ai:\n  organizer:\n    providers: []\n"
            "download:\n  path: ./data/Downloaded\n"
            "transcribe:\n  model: large-v3-turbo\n"
            "publishing:\n  github_pages:\n    enabled: false\n"
            "  github_sync:\n    enabled: false\n"
            "app.database_url: ${KENRADAR_TEST_DATABASE_URL}\n",
            encoding="utf-8",
        )
        return str(cfg)

    def test_pause_without_id_returns_400(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes import tasks as task_routes

        task_routes._handle_task_pause(fh, "config/config.yaml", {})
        status, _, body = _parse_response(fh)
        assert status == 400
        assert body is not None and body.get("ok") is False

    def test_pause_unknown_task_returns_404(self, monkeypatch) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes import tasks as task_routes

        class _FakeDatabase:
            def get_task_run(self, task_run_id):
                return None

            def close(self):
                return None

        monkeypatch.setattr(
            "kenradar.storage.create_database", lambda config: _FakeDatabase()
        )
        task_routes._handle_task_pause(fh, "config/config.yaml", {"id": ["999"]})
        status, _, body = _parse_response(fh)
        assert status == 404
        assert body is not None and body.get("ok") is False

    def test_pause_parks_queued_task_immediately(self, monkeypatch) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes import tasks as task_routes

        calls: list[tuple] = []

        class _FakeDatabase:
            def get_task_run(self, task_run_id):
                return {
                    "id": task_run_id,
                    "status": "queued",
                    "pause_requested_at": None,
                }

            def request_task_pause(self, task_run_id, reason=""):
                calls.append(("request_pause", task_run_id))

            def pause_task_run(self, task_run_id, checkpoint, reason=""):
                calls.append(("pause", task_run_id))

            def resume_task_run(self, task_run_id):
                calls.append(("resume", task_run_id))

            def close(self):
                return None

        monkeypatch.setattr(
            "kenradar.storage.create_database", lambda config: _FakeDatabase()
        )
        task_routes._handle_task_pause(fh, "config/config.yaml", {"id": ["7"]})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None and body.get("ok") is True
        assert ("pause", 7) in calls

    def test_resume_calls_repository_resume(self, monkeypatch) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes import tasks as task_routes

        calls: list[tuple] = []

        class _FakeDatabase:
            def get_task_run(self, task_run_id):
                return {
                    "id": task_run_id,
                    "status": "paused",
                    "pause_requested_at": None,
                }

            def resume_task_run(self, task_run_id):
                calls.append(("resume", task_run_id))

            def close(self):
                return None

        monkeypatch.setattr(
            "kenradar.storage.create_database", lambda config: _FakeDatabase()
        )
        task_routes._handle_task_resume(fh, "config/config.yaml", {"id": ["7"]})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None and body.get("ok") is True
        assert calls == [("resume", 7)]


# ---------------------------------------------------------------------------
# 12. /api/content/process-url (V2 M4 unified single-link pipeline)
# ---------------------------------------------------------------------------

class TestProcessUrlRoute:
    """Contract tests for the unified single-link processing endpoint."""

    @staticmethod
    def _config_path() -> str:
        return "config/config.yaml"

    def _enqueue(self, monkeypatch, url, expected_task_id=12):
        from kenradar.web.routes import process_url as process_routes

        captured: dict[str, Any] = {}

        class _FakeDatabase:
            def enqueue_task_run(self, task_type, payload, message, requested_by="web", *, priority=50, idempotency_key=""):
                captured["payload"] = payload
                captured["task_type"] = task_type
                captured["idempotency_key"] = idempotency_key
                return {"id": expected_task_id}

            def close(self):
                return None

        monkeypatch.setattr(
            "kenradar.storage.create_database", lambda config: _FakeDatabase()
        )
        fh = _FakeHandler()
        process_routes._handle_process_url_post(
            fh, self._config_path(), {}, {}, {"url": url}
        )
        return fh, captured

    def test_post_enqueues_process_url_task_with_202(self, monkeypatch) -> None:
        fh, captured = self._enqueue(monkeypatch, "https://www.douyin.com/video/7123456789")
        status, _, body = _parse_response(fh)
        assert status == 202
        assert body is not None and body.get("ok") is True
        assert body.get("task_id") == 12
        assert captured["task_type"] == "process_url"
        assert captured["payload"]["url"] == "https://www.douyin.com/video/7123456789"

    def test_post_accepts_xiaoyuzhou_url(self, monkeypatch) -> None:
        fh, captured = self._enqueue(
            monkeypatch, "https://www.xiaoyuzhoufm.com/episode/abc123"
        )
        status, _, body = _parse_response(fh)
        assert status == 202
        assert captured["task_type"] == "process_url"

    def test_post_rejects_missing_url_with_400(self, monkeypatch) -> None:
        from kenradar.web.routes import process_url as process_routes

        class _FakeDatabase:
            def enqueue_task_run(self, *args, **kwargs):
                raise AssertionError("不应入队")

            def close(self):
                return None

        monkeypatch.setattr("kenradar.storage.create_database", lambda config: _FakeDatabase())
        fh = _FakeHandler()
        process_routes._handle_process_url_post(fh, self._config_path(), {}, {}, b"{}")
        status, _, body = _parse_response(fh)
        assert status == 400
        assert body is not None and body.get("ok") is False

    def test_post_rejects_unsupported_url_with_400(self, monkeypatch) -> None:
        from kenradar.web.routes import process_url as process_routes

        class _FakeDatabase:
            def enqueue_task_run(self, *args, **kwargs):
                raise AssertionError("不应入队")

            def close(self):
                return None

        monkeypatch.setattr("kenradar.storage.create_database", lambda config: _FakeDatabase())
        fh = _FakeHandler()
        process_routes._handle_process_url_post(
            fh, self._config_path(), {}, {}, {"url": "https://example.com/x"},
        )
        status, _, body = _parse_response(fh)
        assert status == 400

    def test_post_accepts_form_encoded_body(self, monkeypatch) -> None:
        from kenradar.web.routes import process_url as process_routes

        captured: dict[str, Any] = {}

        class _FakeDatabase:
            def enqueue_task_run(self, task_type, payload, message, requested_by="web", *, priority=50, idempotency_key=""):
                captured["payload"] = payload
                return {"id": 3}

            def close(self):
                return None

        monkeypatch.setattr("kenradar.storage.create_database", lambda config: _FakeDatabase())
        fh = _FakeHandler()
        process_routes._handle_process_url_post(
            fh, self._config_path(), {}, {"url": ["https://v.douyin.com/AbCdEf/"]}, {}
        )
        status, _, body = _parse_response(fh)
        assert status == 202
        assert captured["payload"]["url"] == "https://v.douyin.com/AbCdEf/"

    def test_json_body_wins_over_junk_form_parse(self, monkeypatch) -> None:
        from kenradar.web.routes import process_url as process_routes

        captured: dict[str, Any] = {}

        class _FakeDatabase:
            def enqueue_task_run(self, task_type, payload, message, requested_by="web", *, priority=50, idempotency_key=""):
                captured["payload"] = payload
                return {"id": 4}

            def close(self):
                return None

        monkeypatch.setattr("kenradar.storage.create_database", lambda config: _FakeDatabase())
        url = "https://www.xiaoyuzhoufm.com/episode/abc"
        fh = _FakeHandler()
        # parse_qs turns a JSON body into a junk key; the JSON dict must win.
        junk_form = {json.dumps({"url": url}): [""]}
        process_routes._handle_process_url_post(
            fh, self._config_path(), {}, junk_form, {"url": url}
        )
        status, _, body = _parse_response(fh)
        assert status == 202
        assert captured["payload"]["url"] == url

    def test_get_returns_405(self) -> None:
        from kenradar.web.routes import process_url as process_routes

        fh = _FakeHandler()
        process_routes._handle_process_url_get(fh, self._config_path(), {})
        status, _, _ = _parse_response(fh)
        assert status == 405
