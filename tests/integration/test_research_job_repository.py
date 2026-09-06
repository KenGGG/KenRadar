"""Integration tests for research_job repository and scan-confirm-execute (M6)."""
from __future__ import annotations

import pytest

from kenradar.storage.pg_database import Database


@pytest.fixture
def job_db(content_db: Database) -> Database:
    return content_db


def _seed_subscription(database: Database, platform: str = "douyin", source_key: str = "s1") -> int:
    database.upsert_subscription(
        platform=platform,
        source_key=source_key,
        display_name="测试博主",
        source_url="https://example.com/s1",
        feed_url="",
        history_capability="recent",
        check_interval_minutes=60,
    )
    row = database.find_subscription(platform, source_key)
    assert row is not None
    return int(row["id"])


def test_create_scan_job(job_db: Database) -> None:
    sub_id = _seed_subscription(job_db)
    job = job_db.research_jobs.create_scan_job(
        platform="douyin",
        source_subscription_id=sub_id,
        scan_scope="full",
        history_capability="recent",
        creator_name="测试博主",
    )
    assert int(job["id"]) > 0
    assert job["scan_scope"] == "full"
    assert job["confirm_status"] == "pending"
    assert int(job["discovered_count"]) == 0
    fetched = job_db.research_jobs.get_job(int(job["id"]))
    assert fetched is not None
    assert fetched["scan_scope"] == "full"


def test_add_discovered_items_and_confirm(job_db: Database) -> None:
    sub_id = _seed_subscription(job_db)
    job = job_db.research_jobs.create_scan_job(
        platform="douyin",
        source_subscription_id=sub_id,
        scan_scope="full",
        history_capability="recent",
    )
    job_id = int(job["id"])
    job_db.research_jobs.add_discovered_item(
        job_id=job_id,
        external_content_id="abc123",
        title="旧视频A",
        url="https://example.com/a",
        published_at=None,
    )
    job_db.research_jobs.add_discovered_item(
        job_id=job_id,
        external_content_id="def456",
        title="旧视频B",
        url="https://example.com/b",
        published_at=None,
    )
    # re-add same id is idempotent (ON CONFLICT)
    job_db.research_jobs.add_discovered_item(
        job_id=job_id,
        external_content_id="abc123",
        title="旧视频A",
        url="https://example.com/a",
        published_at=None,
    )
    items = job_db.research_jobs.list_discovered_items(job_id)
    assert len(items) == 2
    refreshed = job_db.research_jobs.get_job(job_id)
    assert int(refreshed["discovered_count"]) == 2

    job_db.research_jobs.set_item_review(job_id, "abc123", "approved")
    job_db.research_jobs.set_item_review(job_id, "def456", "rejected")
    job_db.research_jobs.confirm_job(job_id, confirmed_by="tester", approve=True)
    confirmed = job_db.research_jobs.get_job(job_id)
    assert confirmed["confirm_status"] == "confirmed"
    assert int(confirmed["confirmed_count"]) == 1
    approved = job_db.research_jobs.approved_items(job_id)
    assert len(approved) == 1
    assert approved[0]["external_content_id"] == "abc123"


def test_confirm_reject(job_db: Database) -> None:
    sub_id = _seed_subscription(job_db)
    job = job_db.research_jobs.create_scan_job(
        platform="douyin",
        source_subscription_id=sub_id,
        scan_scope="recent",
        history_capability="recent",
    )
    job_id = int(job["id"])
    job_db.research_jobs.confirm_job(job_id, confirmed_by="tester", approve=False)
    rejected = job_db.research_jobs.get_job(job_id)
    assert rejected["confirm_status"] == "rejected"


def test_list_jobs_by_confirm_status(job_db: Database) -> None:
    sub_id = _seed_subscription(job_db)
    job_db.research_jobs.create_scan_job(
        platform="douyin",
        source_subscription_id=sub_id,
        scan_scope="full",
        history_capability="recent",
    )
    jobs = job_db.research_jobs.list_jobs(confirm_status="pending", limit=10)
    assert len(jobs) >= 1
    assert all(j["confirm_status"] == "pending" for j in jobs)
