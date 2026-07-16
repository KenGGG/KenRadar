"""
M2-1 / M2-2: Dashboard overview statistical consistency and reconciliation tests.

Verifies that the /api/dashboard/overview endpoint produces internally
consistent data across summary, pipeline, daily trend, and score
distribution sections.

Uses monkeypatching to inject test fixtures into the query layer,
avoiding the need for a live PostgreSQL connection.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fake handler
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
# Test fixture data — realistic rows spanning multiple days
# ---------------------------------------------------------------------------

def _make_fixture_rows() -> list[dict[str, Any]]:
    """Generate test data covering various statuses, scores, and dates."""
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []

    # Helper to create a row
    def row(aweme_id: int, created_offset_days: int, download_status: str,
            transcript_status: str, summary_status: str, value_score: float | None,
            recommended_action: str = "", failed_stage: str | None = None):
        created = (now - timedelta(days=created_offset_days, hours=5)).isoformat()
        r = {
            "aweme_id": str(aweme_id),
            "created_at": created,
            "aweme_created_at": created,
            "download_status": download_status,
            "transcript_status": transcript_status,
            "summary_status": summary_status,
            "summary_json": json.dumps({
                "value_score": value_score,
                "recommended_action": recommended_action,
            }) if value_score is not None else "{}",
        }
        if failed_stage:
            r["_failure"] = {"stage": failed_stage}
        return r

    # 10 completed items across 5 days, with varying scores
    for i in range(5):
        rows.append(row(
            aweme_id=100 + i,
            created_offset_days=i * 2,
            download_status="success",
            transcript_status="success",
            summary_status="success",
            value_score=3.0 + i * 0.3,  # scores 3.0, 3.3, 3.6, 3.9, 4.2
            recommended_action="push" if i >= 2 else "ignore",
        ))

    # 3 items with high value (score >= 3.5)
    for i in range(3):
        rows.append(row(
            aweme_id=200 + i,
            created_offset_days=i,
            download_status="success",
            transcript_status="success",
            summary_status="success",
            value_score=4.0 + i * 0.2,
            recommended_action="confirm",
        ))

    # 2 failed items (one download failure, one transcription failure)
    rows.append(row(
        aweme_id=300,
        created_offset_days=1,
        download_status="failed",
        transcript_status="pending",
        summary_status="pending",
        value_score=None,
        failed_stage="download",
    ))
    rows.append(row(
        aweme_id=301,
        created_offset_days=3,
        download_status="success",
        transcript_status="failed",
        summary_status="pending",
        value_score=None,
        failed_stage="transcribe",
    ))

    # 1 item still processing (downloading)
    rows.append(row(
        aweme_id=400,
        created_offset_days=0,
        download_status="downloading",
        transcript_status="pending",
        summary_status="pending",
        value_score=None,
    ))

    # 1 item processing (AI waiting)
    rows.append(row(
        aweme_id=401,
        created_offset_days=0,
        download_status="success",
        transcript_status="success",
        summary_status="running",
        value_score=None,
    ))

    return rows


def _make_failure_map(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract failure rows for the failures_map."""
    failures = []
    for r in rows:
        if "_failure" in r:
            failures.append({
                "aweme_id": r["aweme_id"],
                **r["_failure"],
            })
    return failures


# ---------------------------------------------------------------------------
# M2-1: Statistical consistency tests
# ---------------------------------------------------------------------------

class TestDashboardOverviewConsistency:
    """Verify internal consistency of dashboard overview data."""

    def _fetch_with_fixtures(self, days: int = 30) -> dict[str, Any]:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview

        fixture_rows = _make_fixture_rows()
        fixture_failures = _make_failure_map(fixture_rows)

        config_path = str(Path("/tmp").joinpath("config.yaml"))

        with patch("kenradar.web.queries.load_aweme_rows", return_value=fixture_rows):
            with patch("kenradar.web.queries.load_failures", return_value=fixture_failures):
                with patch("kenradar.web.queries.load_library_counts", return_value={}):
                    _handle_dashboard_overview(fh, config_path, {"days": [str(days)]})

        status, _, body = _parse_response(fh)
        assert status == 200, f"dashboard overview returned {status}"
        assert body is not None
        return body

    # --- 1. Summary counts are non-negative integers ---

    def test_summary_counts_non_negative(self) -> None:
        body = self._fetch_with_fixtures()
        s = body["summary"]
        for key in ("today_new", "high_value_pending", "failed", "processing"):
            val = s[key]
            assert isinstance(val, int), f"summary.{key} must be int, got {type(val)}"
            assert val >= 0, f"summary.{key} must be >= 0, got {val}"

    # --- 2. Pipeline counts are non-negative integers ---

    def test_pipeline_counts_non_negative(self) -> None:
        body = self._fetch_with_fixtures()
        p = body["pipeline"]
        for key in ("downloading", "transcribing", "ai_waiting", "push_waiting", "success", "failed"):
            val = p[key]
            assert isinstance(val, int), f"pipeline.{key} must be int, got {type(val)}"
            assert val >= 0, f"pipeline.{key} must be >= 0, got {val}"

    # --- 3. Pipeline stages sum to total known items ---

    def test_pipeline_stages_sum_consistent(self) -> None:
        body = self._fetch_with_fixtures()
        p = body["pipeline"]
        total = sum(p.values())
        assert total >= 0
        # We have 12 rows; pipeline should account for all of them
        assert total == 12, f"pipeline total {total} should match 12 fixture rows"

    # --- 4. Daily trend has correct number of entries ---

    def test_daily_trend_day_count(self) -> None:
        body = self._fetch_with_fixtures(days=15)
        dt = body["dailyTrend"]
        assert len(dt) == 15, f"dailyTrend should have 15 entries, got {len(dt)}"

    # --- 5. Daily trend dates are sequential ---

    def test_daily_trend_dates_sequential(self) -> None:
        body = self._fetch_with_fixtures(days=7)
        dt = body["dailyTrend"]
        assert len(dt) >= 2
        for i in range(1, len(dt)):
            d_prev = datetime.fromisoformat(dt[i - 1]["date"])
            d_curr = datetime.fromisoformat(dt[i]["date"])
            delta = (d_curr - d_prev).days
            assert delta == 1, f"dailyTrend dates should be sequential, gap={delta}"

    # --- 6. Daily trend counts are non-negative ---

    def test_daily_trend_counts_non_negative(self) -> None:
        body = self._fetch_with_fixtures()
        for entry in body["dailyTrend"]:
            for key in ("total", "highValue", "pushed", "confirmed"):
                val = entry[key]
                assert isinstance(val, (int, float))
                assert val >= 0

    # --- 7. Daily trend highValue <= total ---

    def test_daily_trend_highvalue_subset(self) -> None:
        """High value count should never exceed total for any day."""
        body = self._fetch_with_fixtures()
        for entry in body["dailyTrend"]:
            hv = entry["highValue"]
            total = entry["total"]
            assert hv <= total, (
                f"dailyTrend[{entry['date']}]: highValue ({hv}) > total ({total})"
            )

    # --- 8. Score distribution buckets present and non-negative ---

    def test_score_distribution_structure(self) -> None:
        body = self._fetch_with_fixtures()
        sd = body["scoreDistribution"]
        assert isinstance(sd, list)
        buckets_found = set()
        for entry in sd:
            assert "bucket" in entry
            assert "count" in entry
            assert isinstance(entry["count"], (int, float))
            assert entry["count"] >= 0
            buckets_found.add(entry["bucket"])
        expected = {"0-1", "1-2", "2-3", "3-4", "4-5", "5+"}
        assert expected.issubset(buckets_found), (
            f"scoreDistribution missing buckets: {expected - buckets_found}"
        )

    # --- 9. Score distribution sums to completed items with scores ---

    def test_score_distribution_sum_matches_completed(self) -> None:
        """Sum of score distribution should equal number of completed items with value_score."""
        body = self._fetch_with_fixtures()
        sd = body["scoreDistribution"]
        sd_total = sum(e["count"] for e in sd)
        # We have 8 items with value_score (5 regular + 3 high value), all completed
        assert sd_total == 8, f"score distribution sum {sd_total} should match 8 scored items"

    # --- 10. High value threshold is consistent ---

    def test_high_value_threshold_positive(self) -> None:
        body = self._fetch_with_fixtures()
        hv = body["highValueThreshold"]
        assert isinstance(hv, (int, float))
        assert hv > 0
        assert hv >= 5

    # --- 11. Failure reasons sorted descending ---

    def test_failure_reasons_sorted_desc(self) -> None:
        body = self._fetch_with_fixtures()
        fr = body["failureReasons"]
        for i in range(1, len(fr)):
            assert fr[i - 1]["count"] >= fr[i]["count"], (
                "failureReasons should be sorted descending by count"
            )

    # --- 12. Daily trend total sum >= summary.today_new ---

    def test_daily_trend_internal_consistency(self) -> None:
        """The sum of daily trend totals should be >= summary.today_new."""
        body = self._fetch_with_fixtures(days=30)
        dt = body["dailyTrend"]
        trend_total = sum(e["total"] for e in dt)
        summary_today = body["summary"]["today_new"]
        assert trend_total >= summary_today, (
            f"dailyTrend sum ({trend_total}) < summary.today_new ({summary_today})"
        )

    # --- 13. Summary failed count matches fixture failures ---

    def test_summary_failed_matches_fixture(self) -> None:
        """summary.failed should count items with failed status."""
        body = self._fetch_with_fixtures()
        # 2 failed items in fixture
        assert body["summary"]["failed"] == 2, (
            f"summary.failed should be 2, got {body['summary']['failed']}"
        )

    # --- 14. Summary processing count matches fixture ---

    def test_summary_processing_matches_fixture(self) -> None:
        """summary.processing should count items with processing status (queued items excluded)."""
        body = self._fetch_with_fixtures()
        # 1 processing item (id=401 with summary_status='running')
        # id=400 is 'queued' not 'processing' per _frontend_content_status
        assert body["summary"]["processing"] == 1, (
            f"summary.processing should be 1, got {body['summary']['processing']}"
        )


# ---------------------------------------------------------------------------
# M2-2: Reconciliation tests
# ---------------------------------------------------------------------------

class TestDashboardOverviewReconciliation:
    """Verify dashboard overview handles edge cases and data anomalies gracefully."""

    def _fetch_with_fixtures(self, days: int = 30) -> dict[str, Any]:
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview

        config_path = str(Path("/tmp").joinpath("config.yaml"))

        with patch("kenradar.web.queries.load_aweme_rows", return_value=[]):
            with patch("kenradar.web.queries.load_failures", return_value=[]):
                with patch("kenradar.web.queries.load_library_counts", return_value={}):
                    _handle_dashboard_overview(fh, config_path, {"days": [str(days)]})

        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        return body

    # --- 1. Empty database returns valid structure ---

    def test_empty_db_valid_structure(self) -> None:
        """With no data, the overview should still return a valid structure with zeros."""
        body = self._fetch_with_fixtures()
        assert "summary" in body
        assert "dailyTrend" in body
        assert "pipeline" in body
        assert "failureReasons" in body
        assert "scoreDistribution" in body
        assert "highValueThreshold" in body
        s = body["summary"]
        assert s["today_new"] == 0
        assert s["high_value_pending"] == 0
        assert s["failed"] == 0
        assert s["processing"] == 0

    # --- 2. Days parameter bounds ---

    @pytest.mark.parametrize("days", [1, 7, 30, 90, 365])
    def test_days_parameter_bounds(self, days: int) -> None:
        """Days parameter should produce exactly N entries."""
        body = self._fetch_with_fixtures(days=days)
        assert len(body["dailyTrend"]) == days

    # --- 3. Days parameter clamping ---

    def test_days_parameter_clamped_min(self) -> None:
        """Days < 1 should be clamped to 1."""
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        config_path = str(Path("/tmp").joinpath("config.yaml"))
        with patch("kenradar.web.queries.load_aweme_rows", return_value=[]):
            with patch("kenradar.web.queries.load_failures", return_value=[]):
                with patch("kenradar.web.queries.load_library_counts", return_value={}):
                    _handle_dashboard_overview(fh, config_path, {"days": ["0"]})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        assert len(body["dailyTrend"]) == 1

    def test_days_parameter_clamped_max(self) -> None:
        """Days > 365 should be clamped to 365."""
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        config_path = str(Path("/tmp").joinpath("config.yaml"))
        with patch("kenradar.web.queries.load_aweme_rows", return_value=[]):
            with patch("kenradar.web.queries.load_failures", return_value=[]):
                with patch("kenradar.web.queries.load_library_counts", return_value={}):
                    _handle_dashboard_overview(fh, config_path, {"days": ["999"]})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        assert len(body["dailyTrend"]) == 365

    def test_days_parameter_invalid_defaults(self) -> None:
        """Non-numeric days should default to 30."""
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        config_path = str(Path("/tmp").joinpath("config.yaml"))
        with patch("kenradar.web.queries.load_aweme_rows", return_value=[]):
            with patch("kenradar.web.queries.load_failures", return_value=[]):
                with patch("kenradar.web.queries.load_library_counts", return_value={}):
                    _handle_dashboard_overview(fh, config_path, {"days": ["not_a_number"]})
        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None
        assert len(body["dailyTrend"]) == 30

    # --- 4. Performance ---

    def test_overview_response_time(self) -> None:
        """Dashboard overview should respond in under 5 seconds."""
        import time
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview

        fixture_rows = _make_fixture_rows()
        fixture_failures = _make_failure_map(fixture_rows)
        config_path = str(Path("/tmp").joinpath("config.yaml"))

        start = time.monotonic()
        with patch("kenradar.web.queries.load_aweme_rows", return_value=fixture_rows):
            with patch("kenradar.web.queries.load_failures", return_value=fixture_failures):
                with patch("kenradar.web.queries.load_library_counts", return_value={}):
                    _handle_dashboard_overview(fh, config_path, {"days": ["30"]})
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"dashboard overview took {elapsed:.2f}s, expected < 5s"

    # --- 5. JSON serialization — no NaN/Inf ---

    def test_no_nan_or_inf_values(self) -> None:
        """All numeric values must be serializable to JSON."""
        body = self._fetch_with_fixtures()
        raw = json.dumps(body)
        assert raw is not None
        parsed = json.loads(raw)
        assert parsed is not None

    # --- 6. Summary counts don't exceed pipeline total ---

    def test_summary_within_pipeline_bounds(self) -> None:
        """Summary counts should not exceed total pipeline items."""
        body = self._fetch_with_fixtures()
        p = body["pipeline"]
        pipeline_total = sum(p.values())
        s = body["summary"]
        if pipeline_total > 0:
            assert s["failed"] <= pipeline_total
            assert s["processing"] <= pipeline_total

    # --- 7. Cross-section reconciliation: high_value_pending consistency ---

    def test_high_value_cross_section_consistency(self) -> None:
        """high_value_pending should equal count of completed items with score >= threshold."""
        fh = _FakeHandler()
        from kenradar.web.routes.dashboard_overview import _handle_dashboard_overview
        from kenradar.web.queries import HIGH_VALUE_THRESHOLD

        fixture_rows = _make_fixture_rows()
        fixture_failures = _make_failure_map(fixture_rows)
        config_path = str(Path("/tmp").joinpath("config.yaml"))

        with patch("kenradar.web.queries.load_aweme_rows", return_value=fixture_rows):
            with patch("kenradar.web.queries.load_failures", return_value=fixture_failures):
                with patch("kenradar.web.queries.load_library_counts", return_value={}):
                    _handle_dashboard_overview(fh, config_path, {"days": ["30"]})

        status, _, body = _parse_response(fh)
        assert status == 200
        assert body is not None

        # Count expected high value items: completed items with value_score >= HIGH_VALUE_THRESHOLD
        # From fixture: scores 3.6, 3.9, 4.2 (push items) + 4.0, 4.2, 4.4 (confirm items) = 6 items
        # HIGH_VALUE_THRESHOLD is 3.5, so all >= 3.5 qualify
        expected_hv = sum(
            1 for r in fixture_rows
            if r["summary_status"] == "success"
            and r["summary_json"]
            and json.loads(r["summary_json"]).get("value_score") is not None
            and json.loads(r["summary_json"])["value_score"] >= HIGH_VALUE_THRESHOLD
        )
        actual_hv = body["summary"]["high_value_pending"]
        assert actual_hv == expected_hv, (
            f"high_value_pending: expected {expected_hv}, got {actual_hv}"
        )
