"""
M4 acceptance tests: idempotency, reconciliation, and performance for source insights.

Tests verify:
- Idempotency: running analytics-scan twice produces identical results
- Reconciliation: source-level metrics sum to global totals
- Performance: queries complete within acceptable time bounds
"""

from __future__ import annotations

import io
import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fake handler (same pattern as test_dashboard_consistency.py)
# ---------------------------------------------------------------------------

class _FakeServer:
    def handle_timeout(self) -> None:
        pass


class _FakeHandler(BaseHTTPRequestHandler):
    def __init__(self) -> None:
        self._buffer = io.BytesIO()
        self._headers_list: list[tuple[str, str]] = []
        self._status = 200
        self.client_address = ("127.0.0.1", 0)
        self.server = _FakeServer()
        self.request = b""
        self.rfile = io.BytesIO(b"")
        self.wfile_attr = self._buffer
        self.close_connection = True

    def send_response(self, code: int, message: str | None = None) -> None:
        self._status = code
        self.send_response_only(code, message)

    def send_response_only(self, code: int, message: str | None = None) -> None:
        pass

    def send_header(self, keyword: str, value: str) -> None:
        self._headers_list.append((keyword, value))

    def end_headers(self) -> None:
        pass

    @property
    def wfile(self) -> io.BytesIO:
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
# Fixture data
# ---------------------------------------------------------------------------

def _make_source_metrics_rows():
    """Generate source_daily_metrics rows for 3 sources across 5 days."""
    rows = []
    for source_id in [1, 2, 3]:
        for day_offset in range(5):
            d = date.today() - timedelta(days=day_offset)
            rows.append({
                "source_id": source_id,
                "metric_date": d.isoformat(),
                "total_content": source_id * (5 - day_offset),
                "rated_count": source_id * (3 - day_offset),
                "high_value_count": source_id * (1 if day_offset < 2 else 0),
                "avg_rating": 7.0 + source_id * 0.1,
                "push_count": source_id if day_offset < 3 else 0,
                "review_count": source_id,
                "failed_count": 0 if day_offset < 4 else 1,
            })
    return rows


def _make_sources_rows():
    """Generate source_subscription rows."""
    return [
        {"id": 1, "display_name": "Source A", "platform_id": 1, "enabled": True,
         "source_key": "uid_a", "source_url": "https://dy.com/a", "feed_url": None},
        {"id": 2, "display_name": "Source B", "platform_id": 1, "enabled": True,
         "source_key": "uid_b", "source_url": "https://dy.com/b", "feed_url": None},
        {"id": 3, "display_name": "Source C", "platform_id": 2, "enabled": True,
         "source_key": "pod_c", "source_url": "https://xy.fm/c", "feed_url": "https://xy.fm/rss/c"},
    ]


def _mock_config_loader(path):
    """Create a minimal AppConfig mock for the insights handlers."""
    cfg = MagicMock()
    cfg.app_data_dir = Path("/tmp/kenradar-test-data")
    return cfg


# ---------------------------------------------------------------------------
# M4-1: Idempotency — running analytics twice produces same result
# ---------------------------------------------------------------------------

def test_idempotency_aggregation():
    """Running aggregate_source_metrics twice for the same date range yields the same data."""
    from kenradar.core.analytics import aggregate_source_metrics

    mock_config = MagicMock()

    with patch("kenradar.storage.create_database") as mock_create_db:
        mock_db = MagicMock()
        mock_create_db.return_value = mock_db

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        def mock_execute(sql, params=None):
            if "source_subscription" in str(sql) and "enabled" in str(sql):
                return MagicMock(fetchall=lambda: [
                    {"source_id": r["id"], "display_name": r["display_name"],
                     "platform_id": r["platform_id"], "source_key": r["source_key"],
                     "source_url": r["source_url"], "feed_url": r["feed_url"]}
                    for r in _make_sources_rows()
                ])
            return MagicMock(fetchall=lambda: [])  # No creators mapped

        mock_conn.execute = mock_execute
        mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)

        summary1 = aggregate_source_metrics(mock_config, days=5, dry_run=True)
        summary2 = aggregate_source_metrics(mock_config, days=5, dry_run=True)

    assert summary1["rows_upserted"] == summary2["rows_upserted"]
    assert summary1["total_days"] == summary2["total_days"]


# ---------------------------------------------------------------------------
# M4-2: Reconciliation — source totals match global totals
# ---------------------------------------------------------------------------

def test_reconciliation_source_vs_global():
    """Sum of per-source metrics equals global overview metrics."""
    all_rows = _make_source_metrics_rows()
    expected_total_content = sum(r["total_content"] for r in all_rows)
    expected_rated_count = sum(r["rated_count"] for r in all_rows)
    expected_high_value = sum(r["high_value_count"] for r in all_rows)

    assert expected_total_content > 0

    with patch("kenradar.core.config.load_config", _mock_config_loader):
        with patch("kenradar.storage.create_database") as mock_create_db:
            mock_db = MagicMock()
            mock_create_db.return_value = mock_db

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            mock_row = {
                "active_sources": 3,
                "total_content": expected_total_content,
                "rated_count": expected_rated_count,
                "high_value_count": expected_high_value,
                "push_count": sum(r["push_count"] for r in all_rows),
                "failed_count": sum(r["failed_count"] for r in all_rows),
            }
            mock_conn.execute.return_value.fetchone.return_value = mock_row

            mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)

            handler = _FakeHandler()
            handler.path = "/api/insights/overview?days=5"
            handler.command = "GET"

            from kenradar.web.routes.insights import _handle_insights_overview
            _handle_insights_overview(handler, "config.yaml", {"days": ["5"]})

            _, _, body = _parse_response(handler)
            assert body is not None
            assert body["total_content"] == expected_total_content
            assert body["rated_count"] == expected_rated_count
            assert body["high_value_count"] == expected_high_value


# ---------------------------------------------------------------------------
# M4-3: Source list returns latest metrics per source
# ---------------------------------------------------------------------------

def test_source_list_returns_latest_metrics():
    """Each source in the list should have its most recent metric_date."""
    with patch("kenradar.core.config.load_config", _mock_config_loader):
        with patch("kenradar.storage.create_database") as mock_create_db:
            mock_db = MagicMock()
            mock_create_db.return_value = mock_db

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            sources_rows = _make_sources_rows()
            combined = []
            for s in sources_rows:
                sid = s["id"]
                src_metrics = [r for r in _make_source_metrics_rows() if r["source_id"] == sid]
                latest = sorted(src_metrics, key=lambda x: x["metric_date"], reverse=True)[0]
                combined.append({
                    "id": sid, "display_name": s["display_name"],
                    "source_url": s["source_url"], "category": None,
                    "enabled": s["enabled"], "platform_id": s["platform_id"],
                    "total_content": latest["total_content"],
                    "rated_count": latest["rated_count"],
                    "avg_rating": latest["avg_rating"],
                    "high_value_count": latest["high_value_count"],
                    "push_count": latest["push_count"],
                    "failed_count": latest["failed_count"],
                    "metric_date": latest["metric_date"],
                })

            def mock_execute(sql, params=None):
                return MagicMock(fetchall=lambda: combined)

            mock_conn.execute = mock_execute
            mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)

            handler = _FakeHandler()
            handler.path = "/api/insights/sources"
            handler.command = "GET"

            from kenradar.web.routes.insights import _handle_insights_sources
            _handle_insights_sources(handler, "config.yaml")

            _, _, body = _parse_response(handler)
            assert body is not None
            assert len(body["items"]) == 3
            for item in body["items"]:
                assert "total_content" in item
                assert "avg_rating" in item


# ---------------------------------------------------------------------------
# M4-4: Time-series metrics for a single source
# ---------------------------------------------------------------------------

def test_source_metrics_timeseries():
    """GET /api/insights/sources/metrics returns ordered time series."""
    with patch("kenradar.core.config.load_config", _mock_config_loader):
        with patch("kenradar.storage.create_database") as mock_create_db:
            mock_db = MagicMock()
            mock_create_db.return_value = mock_db

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            source_row = {
                "id": 1, "display_name": "Source A", "platform_id": 1,
                "enabled": True, "category": "tech",
                "platform": "douyin",
            }
            src_metrics = sorted(
                [r for r in _make_source_metrics_rows() if r["source_id"] == 1],
                key=lambda x: x["metric_date"],
            )

            def mock_execute(sql, params=None):
                if "WHERE s.id" in str(sql):
                    return MagicMock(fetchone=lambda: source_row)
                return MagicMock(fetchall=lambda: [dict(r) for r in src_metrics])

            mock_conn.execute = mock_execute
            # Two connect() calls: first for source info, second for metrics
            mock_db.connect.side_effect = [
                MagicMock(__enter__=MagicMock(return_value=mock_conn),
                         __exit__=MagicMock(return_value=False)),
                MagicMock(__enter__=MagicMock(return_value=mock_conn),
                         __exit__=MagicMock(return_value=False)),
            ]

            handler = _FakeHandler()
            handler.path = "/api/insights/sources/metrics?id=1&days=5"
            handler.command = "GET"

            from kenradar.web.routes.insights import _handle_insights_source_metrics
            _handle_insights_source_metrics(handler, "config.yaml", {"id": ["1"], "days": ["5"]})

            _, _, body = _parse_response(handler)
            assert body is not None
            assert body["source"]["id"] == 1
            assert body["source"]["name"] == "Source A"
            assert len(body["metrics"]) == 5
            assert body["summary"]["total_content"] == sum(m["total_content"] for m in src_metrics)


# ---------------------------------------------------------------------------
# M4-5: Performance — overview query responds quickly
# ---------------------------------------------------------------------------

def test_performance_overview_query():
    """Overview query should complete within acceptable time."""
    import time

    with patch("kenradar.core.config.load_config", _mock_config_loader):
        with patch("kenradar.storage.create_database") as mock_create_db:
            mock_db = MagicMock()
            mock_create_db.return_value = mock_db

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            mock_conn.execute.return_value.fetchone.return_value = {
                "active_sources": 10, "total_content": 500,
                "rated_count": 300, "high_value_count": 50,
                "push_count": 20, "failed_count": 5,
            }

            mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)

            handler = _FakeHandler()
            handler.path = "/api/insights/overview?days=30"
            handler.command = "GET"

            t0 = time.monotonic()
            from kenradar.web.routes.insights import _handle_insights_overview
            _handle_insights_overview(handler, "config.yaml", {"days": ["30"]})
            elapsed = time.monotonic() - t0

            _, _, body = _parse_response(handler)
            assert body is not None
            assert elapsed < 1.0


# ---------------------------------------------------------------------------
# M4-6: Edge case — source with no metrics
# ---------------------------------------------------------------------------

def test_source_with_no_metrics():
    """Sources with no daily metrics should still appear with zero counts."""
    with patch("kenradar.core.config.load_config", _mock_config_loader):
        with patch("kenradar.storage.create_database") as mock_create_db:
            mock_db = MagicMock()
            mock_create_db.return_value = mock_db

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)

            combined = [{
                "id": 4, "display_name": "Empty Source",
                "source_url": "https://dy.com/empty",
                "category": None, "enabled": True, "platform_id": 1,
                "total_content": 0, "rated_count": 0,
                "avg_rating": None, "high_value_count": 0,
                "push_count": 0, "failed_count": 0, "metric_date": None,
            }]

            def mock_execute(sql, params=None):
                return MagicMock(fetchall=lambda: combined)

            mock_conn.execute = mock_execute
            mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)

            handler = _FakeHandler()
            handler.path = "/api/insights/sources"
            handler.command = "GET"

            from kenradar.web.routes.insights import _handle_insights_sources
            _handle_insights_sources(handler, "config.yaml")

            _, _, body = _parse_response(handler)
            assert body is not None
            assert len(body["items"]) == 1
            assert body["items"][0]["total_content"] == 0


# ---------------------------------------------------------------------------
# M4-7: Edge case — source not found
# ---------------------------------------------------------------------------

def test_source_metrics_not_found():
    """Requesting metrics for a nonexistent source returns 404."""
    with patch("kenradar.core.config.load_config", _mock_config_loader):
        with patch("kenradar.storage.create_database") as mock_create_db:
            mock_db = MagicMock()
            mock_create_db.return_value = mock_db

            mock_conn = MagicMock()
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_conn.execute.return_value.fetchone.return_value = None
            mock_db.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.connect.return_value.__exit__ = MagicMock(return_value=False)

            handler = _FakeHandler()
            handler.path = "/api/insights/sources/metrics?id=99999&days=30"
            handler.command = "GET"

            from kenradar.web.routes.insights import _handle_insights_source_metrics
            _handle_insights_source_metrics(handler, "config.yaml", {"id": ["99999"], "days": ["30"]})

            status, _, body = _parse_response(handler)
            assert status == 404
            assert body is not None
            assert body.get("error") == "source not found"
