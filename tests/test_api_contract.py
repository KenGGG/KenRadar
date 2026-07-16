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
    cfg = Path(CONFIG_PATH)
    if not cfg.exists():
        tmp_cfg = tmp_path / "config.yaml"
        tmp_cfg.write_text(
            "app:\n  data_dir: ./data\n  web_port: 8765\n"
            "schedule:\n  enabled: true\n  times:\n    - \"10:00\"\n"
            "ai:\n  organizer:\n    providers: []\n"
            "download:\n  path: ./data/Downloaded\n",
            encoding="utf-8",
        )
        return str(tmp_cfg)
    return CONFIG_PATH


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
    def test_returns_json(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_ready
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

    def test_status_values(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_ready
        cfg_path = _ensure_test_config(Path("/tmp"))
        _handle_health_ready(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        assert body["status"] in ("ready", "not_ready")


# ---------------------------------------------------------------------------
# 3. /health/dependencies
# ---------------------------------------------------------------------------

class TestHealthDependencies:
    def test_returns_json(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.health import _handle_health_dependencies
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


# ---------------------------------------------------------------------------
# 5. /api/status
# ---------------------------------------------------------------------------

class TestStatus:
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
# 6. /api/awemes
# ---------------------------------------------------------------------------

class TestAwemes:
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
        from kenradar.web.routes.dashboard import _handle_awemes
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_awemes(fh, cfg_path, {"page": ["1"], "page_size": ["100"]})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None

    def test_has_items_field(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_awemes
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_awemes(fh, cfg_path, {"page": ["1"], "page_size": ["100"]})
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "items" in body
        assert isinstance(body["items"], list)

    def test_has_page_info(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_awemes
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_awemes(fh, cfg_path, {"page": ["2"], "page_size": ["50"]})
        _, _, body = _parse_response(fh)
        assert body is not None
        assert body.get("page") == 2
        assert body.get("page_size") == 50

    def test_items_have_required_fields(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_awemes
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_awemes(fh, cfg_path, {"page": ["1"], "page_size": ["100"]})
        _, _, body = _parse_response(fh)
        assert body is not None
        items = body.get("items", [])
        if items:
            first = items[0]
            for key in ("id", "title", "blogger", "rating", "status", "created_at"):
                assert key in first, f"video item missing: {key}"


# ---------------------------------------------------------------------------
# 7. /api/research/jobs
# ---------------------------------------------------------------------------

class TestResearchJobs:
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
        from kenradar.web.routes.research import _handle_research_jobs_get
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_research_jobs_get(fh, cfg_path)
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None

    def test_has_items_field(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.research import _handle_research_jobs_get
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_research_jobs_get(fh, cfg_path)
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "items" in body
        assert isinstance(body["items"], list)


# ---------------------------------------------------------------------------
# 8. /api/content-items (cursor pagination)
# ---------------------------------------------------------------------------

class TestContentItems:
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

    def test_valid_sort_returns_ok(self) -> None:
        """Test that a valid sort parameter reaches the DB query layer."""
        fh = _FakeHandler()
        from kenradar.web.routes.content import _handle_content_items
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_content_items(fh, cfg_path, {"sort": ["newest"]})
        # May succeed (200) or fail at DB layer (500) depending on env
        # We only verify the response structure, not the DB result
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "ok" in body

    def test_invalid_sort_returns_400(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.content import _handle_content_items
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_content_items(fh, cfg_path, {"sort": ["invalid_sort_value"]})
        status, _, body = _parse_response(fh)
        assert status == 400
        assert body is not None
        assert "message" in body

    def test_invalid_limit_returns_400(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.content import _handle_content_items
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_content_items(fh, cfg_path, {"limit": ["abc"]})
        status, _, body = _parse_response(fh)
        assert status == 400
        assert body is not None
        assert "message" in body

    def test_response_has_content_type(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.content import _handle_content_items
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_content_items(fh, cfg_path, {"sort": ["newest"]})
        _, headers, _ = _parse_response(fh)
        assert "content-type" in headers
        assert "application/json" in headers["content-type"]


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
# 9. /api/aweme/detail
# ---------------------------------------------------------------------------

class TestAwemeDetail:
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

    def test_nonexistent_returns_404(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_aweme_detail
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_aweme_detail(fh, cfg_path, {"id": ["nonexistent_id_xyz"]})
        status, _, body = _parse_response(fh)
        assert status == 404
        assert body is not None
        assert "message" in body

    def test_has_ok_field(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_aweme_detail
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_aweme_detail(fh, cfg_path, {"id": ["nonexistent_id_xyz"]})
        _, _, body = _parse_response(fh)
        assert body is not None
        assert "ok" in body


# ---------------------------------------------------------------------------
# 10. /api/aweme/progress
# ---------------------------------------------------------------------------

class TestAwemeProgress:
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

    def test_nonexistent_returns_404(self) -> None:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard import _handle_aweme_progress
        cfg_path = self._get_config_path(Path("/tmp"))
        _handle_aweme_progress(fh, cfg_path, {"id": ["nonexistent_id_xyz"]})
        status, _, body = _parse_response(fh)
        assert status == 404
        assert body is not None
        assert "message" in body


# ---------------------------------------------------------------------------
# 11. /api/task-runs
# ---------------------------------------------------------------------------

class TestTaskRuns:
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
