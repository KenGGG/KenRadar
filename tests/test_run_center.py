"""Run-center classification against a PostgreSQL TEMP table; no live task writes."""
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


@pytest.fixture
def task_rows(monkeypatch):
    from kenradar.web import run_center
    import psycopg
    from psycopg.rows import dict_row

    url = os.environ.get("KENRADAR_RUN_CENTER_TEST_URL")
    if not url:
        pytest.skip("KENRADAR_RUN_CENTER_TEST_URL required; uses only a TEMP table")
    with psycopg.connect(url, row_factory=dict_row) as conn:
        conn.execute("""CREATE TEMP TABLE task_run (
            id bigint, task_type text, status text, message text, priority int DEFAULT 50,
            attempt int DEFAULT 1, max_attempts int DEFAULT 3, error_code text,
            last_error text, created_at timestamptz DEFAULT NOW(), updated_at timestamptz DEFAULT NOW(),
            started_at timestamptz, finished_at timestamptz, available_at timestamptz DEFAULT NOW(),
            heartbeat_at timestamptz, lease_expires_at timestamptz,
            pause_requested_at timestamptz, cancel_requested_at timestamptz,
            progress_json jsonb DEFAULT '{}', stats_json jsonb DEFAULT '{}'
        ) ON COMMIT DROP""")

        @contextmanager
        def connect():
            yield conn

        monkeypatch.setattr(run_center, "create_database", lambda _: SimpleNamespace(connect=connect, close=lambda: None))

        def insert(id, status, **kw):
            row = dict(id=id, task_type="process_url", status=status, message="sample")
            row.update(kw)
            conn.execute(f"INSERT INTO task_run ({','.join(row)}) VALUES ({','.join(['%s'] * len(row))})", list(row.values()))
        yield insert


def test_task_sections_do_not_mix_history_with_execution(task_rows):
    from kenradar.web.run_center import load_run_center
    now = datetime.now(timezone.utc)
    task_rows(1, "running", lease_expires_at=now + timedelta(minutes=5))
    task_rows(2, "queued")
    task_rows(3, "retry_wait")
    task_rows(4, "paused")
    task_rows(5, "failed", last_error="不支持的链接来源")
    task_rows(6, "running", lease_expires_at=now - timedelta(seconds=1))
    task_rows(7, "cancelled")
    task_rows(8, "success")
    task_rows(9, "failed", task_type="company_financial_analysis")
    task_rows(10, "success", stats_json='{"status":"partial_failed","failed":1}')
    active = load_run_center(None, section="active", limit=2)
    assert active["counts"] == {"active": 3, "attention": 4, "history": 3}
    assert active["total"] == 3
    assert len(active["items"]) == 2
    assert active["items"][0]["id"] == 1
    second = load_run_center(None, section="active", limit=2, offset=2)
    assert len(second["items"]) == 1
    assert not ({r["id"] for r in active["items"]} & {r["id"] for r in second["items"]})
    attention = load_run_center(None, section="attention")
    assert {r["display_status"] for r in attention["items"]} == {"paused", "failed", "interrupted", "partial_failed"}
    history = load_run_center(None, section="history")
    assert {r["display_status"] for r in history["items"]} == {"cancelled", "success", "retired"}
    filtered = load_run_center(None, section="attention", status="paused")
    assert filtered["total"] == 1
    assert filtered["items"][0]["id"] == 4
    assert filtered["counts"] == active["counts"]


def test_empty_page_keeps_totals_and_cancelled_is_not_failure(task_rows):
    from kenradar.web.run_center import load_run_center
    task_rows(1, "success", stats_json='{"status":"cancelled"}')
    task_rows(2, "running")  # no lease is not proof of a live worker
    result = load_run_center(None, section="history", offset=100)
    assert result["items"] == []
    assert result["total"] == 1
    assert result["counts"] == {"active": 0, "attention": 1, "history": 1}


def test_explicit_failed_result_is_not_partial_success(task_rows):
    from kenradar.web.run_center import load_run_center
    task_rows(1, "success", stats_json='{"status":"failed","failed":3}')
    result = load_run_center(None, section="attention")
    assert result["items"][0]["display_status"] == "failed"
    assert result["items"][0]["status"] == "success"
