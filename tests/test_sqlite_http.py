"""Real HTTP server + file SQLite fixtures. No platform/model/publication calls."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from sqlalchemy import insert

from test_sqlite_v2 import sqlite_db
from kenradar.storage import create_database, reset_database_cache
from kenradar.core.config import load_config
from kenradar.web.sqlite_queries import content_items


def test_list_pagination_and_chinese(sqlite_db):
    db, cfg = sqlite_db
    config = load_config(cfg)
    creator = db.upsert_creator("douyin", "000作者", "作者", "")
    table = db.table("content_item")
    with db.connect(write=True) as conn:
        conn.raw.execute(insert(table), [dict(platform_id=1, content_id=f"00{i}", creator_id=creator,
            title=f"国债 算力 ETF {i}", publish_time=f"2026-10-{1 + i % 9:02d}T00:00:00.000000Z") for i in range(10000)])
    ids, cursor = [], None
    for _ in range(4):
        result = content_items(config, keyword="国债", sort="newest", cursor=cursor, limit=20)
        assert len(result["items"]) == 20
        assert result['total_estimate'] == 10000
        assert result['source_counts'][0]['total_items'] == 10000
        ids.extend(item["id"] for item in result["items"])
        cursor = result["next_cursor"]
    assert len(set(ids)) == 80
    assert content_items(config, keyword="算力", sort="newest")["items"]
    assert content_items(config, keyword="ETF", sort="newest")["items"]
    assert not content_items(config, keyword="%", sort="newest")["items"]
    with pytest.raises(ValueError, match="cursor"):
        content_items(config, keyword="其他", sort="newest", cursor=cursor)
    reset_database_cache()


def test_real_web_and_worker_without_psycopg(sqlite_db, tmp_path):
    db, cfg = sqlite_db
    creator = db.upsert_creator("douyin", "001", "真实文件库 fixture", "")
    db.upsert_content_item("douyin", "009999999999999999999", creator, title="国债内容")
    run = db.enqueue_task_run("system_health_check", {}, "独立 worker fixture")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k not in {"DATABASE_URL", "AGNES_API_KEY", "FEISHU_WEBHOOK_URL"}}
    # Block PG imports even if the developer's optional packages are installed.
    guard = "import sys; sys.modules['psycopg']=None; sys.modules['psycopg_pool']=None; "
    logfile = tmp_path / "http.log"
    with logfile.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-c", guard +
            "from kenradar.web.app import run_web; run_web(sys.argv[1],port=int(sys.argv[2]))", str(cfg), str(port)],
            env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 20
            while True:
                try:
                    with urllib.request.urlopen(base + "/health/live", timeout=1) as response:
                        assert json.load(response)["ok"]
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic() > deadline:
                        pytest.fail(logfile.read_text(encoding="utf-8"))
                    time.sleep(0.1)
            with urllib.request.urlopen(base + "/api/content-items?keyword=" + urllib.parse.quote("国债"), timeout=5) as response:
                body = json.load(response)
                assert body["ok"] and len(body["items"]) == 1
            with urllib.request.urlopen(base + "/health/ready", timeout=5) as response:
                assert json.load(response)["ok"]
            with urllib.request.urlopen(base + "/api/run-center?section=active", timeout=5) as response:
                center = json.load(response)
                assert center["ok"] and center["counts"]["active"] == 1
                assert center["items"][0]["id"] == run["id"]
            with urllib.request.urlopen(base + "/api/settings", timeout=5) as response:
                settings = json.load(response)
            payload = {"group": "automatic", "expected_revision": settings["revision"], "values": {"schedule.enabled": False}}
            for endpoint, method in (("/api/settings/validate", "POST"), ("/api/settings", "PATCH")):
                request = urllib.request.Request(base + endpoint, data=json.dumps(payload).encode(), method=method, headers={"Content-Type": "application/json", "Origin": base})
                with urllib.request.urlopen(request, timeout=5) as response:
                    assert json.load(response)["ok"]
            request = urllib.request.Request(base + "/api/settings", data=json.dumps(payload).encode(), method="PATCH", headers={"Content-Type": "application/json", "Origin": base})
            with pytest.raises(urllib.error.HTTPError) as rejected:
                urllib.request.urlopen(request, timeout=5)
            assert rejected.value.code == 409
            with urllib.request.urlopen(base + "/api/content?platform=douyin&external_id=009999999999999999999", timeout=5) as response:
                body = json.load(response)
                assert body["content_item_id"] > 0 and body["item"]["title"] == "国债内容"
            with urllib.request.urlopen(base + "/api/dashboard/overview", timeout=5) as response:
                body = json.load(response)
                assert body["summary"]["today_new"] == 1
                assert sum(v["total"] for v in body["dailyTrend"]) == 1
            result = subprocess.run([sys.executable, "-c", guard +
                "from kenradar.jobs.worker import TaskWorker; TaskWorker(sys.argv[1],'fixture-worker').run_once()", str(cfg)],
                env=env, capture_output=True, text=True, timeout=20,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            assert result.returncode == 0, result.stderr
            assert db.get_task_run(run["id"])["status"] == "success"
        finally:
            process.terminate()
            process.wait(10)
