from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest
from sqlalchemy import insert, select, update, text
from sqlalchemy.exc import IntegrityError, OperationalError

from kenradar.core.config import load_config
from kenradar.storage.migrate import upgrade_database, schema_status
from kenradar.storage.sqlite_database import Database, LeaseLost, utc_now


@pytest.fixture
def sqlite_db(tmp_path: Path):
    path = tmp_path / "config" / "config.yaml"
    path.parent.mkdir()
    db_path = tmp_path / "db/fixture.sqlite3"
    path.write_text(f'app:\n  database_url: "sqlite:///{db_path.as_posix()}"\n  data_dir: "{tmp_path.as_posix()}"\nschedule:\n  enabled: false\n', encoding="utf-8")
    upgrade_database(str(path))
    db = Database(load_config(path).database_url)
    db.initialize()
    yield db, path
    db.close()


def _consume(url: str, worker: str) -> None:
    db = Database(url)
    db.initialize()
    while task := db.claim_next_task_run(worker):
        with db.lease_scope(task):
            db.complete_task_run(task["id"], {"worker": worker})
    db.close()


def _crash(url: str) -> None:
    db = Database(url)
    db.initialize()
    db.claim_next_task_run("crashed", lease_seconds=1)
    os._exit(17)


def test_pragmas_schema_and_missing_path(sqlite_db, tmp_path):
    db, cfg = sqlite_db
    before = schema_status(str(cfg))
    upgrade_database(str(cfg))
    assert schema_status(str(cfg)) == before
    assert before["up_to_date"]
    health = db.diagnostic()
    assert health["journal_mode"] == "wal"
    assert health["foreign_keys"] == 1
    assert health["synchronous"] == 2
    assert health["busy_timeout"] == 5000
    assert health["json"] and health["fts5"]
    assert health["integrity"] == "ok" and not health["foreign_key_errors"]
    missing = tmp_path / "missing.sqlite3"
    other = Database("sqlite:///" + missing.as_posix())
    with pytest.raises(RuntimeError, match="不存在"):
        with other.connect():
            pass
    assert not missing.exists()


def test_transaction_ddl_savepoint_and_foreign_keys(sqlite_db):
    db, _ = sqlite_db
    with pytest.raises(RuntimeError):
        with db.connect(write=True) as conn:
            conn.execute("CREATE TABLE rollback_ddl (id INTEGER)")
            raise RuntimeError("inject failure")
    with db.connect() as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='rollback_ddl'").fetchone()
    with db.connect(write=True) as conn:
        conn.execute("CREATE TABLE savepoint_check (id INTEGER)")
        with pytest.raises(RuntimeError):
            with conn.raw.begin_nested():
                conn.execute("INSERT INTO savepoint_check VALUES (1)")
                raise RuntimeError("inject")
        assert conn.execute("SELECT count(*) FROM savepoint_check").fetchone()[0] == 0
    with pytest.raises(IntegrityError):
        with db.connect(write=True) as conn:
            conn.execute(insert(db.table("creator")).values(platform_id=9999, platform_uid="invalid"))


def test_1000_tasks_two_real_processes(sqlite_db):
    db, _ = sqlite_db
    t = db.table("task_run")
    with db.connect(write=True) as conn:
        conn.raw.execute(insert(t), [{"task_type": "fixture", "payload_json": "{}", "idempotency_key": f"fixture:{i}"} for i in range(1000)])
    ctx = multiprocessing.get_context("spawn")
    workers = [ctx.Process(target=_consume, args=(db.database_url, f"worker-{i}")) for i in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
        if worker.is_alive():
            worker.terminate()
            worker.join()
            pytest.fail("并发测试超时")
        assert worker.exitcode == 0
    with db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM task_run WHERE status='success'").fetchone()[0] == 1000
        assert conn.execute("SELECT count(*) FROM task_attempt").fetchone()[0] == 1000
        assert conn.execute("SELECT count(*) FROM state_transition").fetchone()[0] == 2000
        assert conn.execute("SELECT count(*) FROM outbox_event").fetchone()[0] == 1000
        assert not conn.execute("SELECT task_run_id FROM task_attempt GROUP BY task_run_id HAVING count(*)<>1").fetchall()


def test_crash_recovery_and_stale_worker_fencing(sqlite_db):
    db, _ = sqlite_db
    run = db.enqueue_task_run("fixture", {}, "crash", idempotency_key="crash")
    child = multiprocessing.get_context("spawn").Process(target=_crash, args=(db.database_url,))
    child.start()
    child.join(20)
    assert child.exitcode == 17
    old = db.get_task_run(run["id"])
    with db.connect(write=True) as conn:
        conn.execute(update(db.table("task_run")).where(db.table("task_run").c.id == run["id"]).values(lease_expires_at=utc_now(-1)))
    new = db.claim_next_task_run("replacement")
    assert new["id"] == old["id"] and new["lease_token"] != old["lease_token"]
    with pytest.raises(LeaseLost):
        db.heartbeat_task_run(old["id"], lease_token=old["lease_token"], worker_name=old["worker_name"])
    with db.lease_scope(old), pytest.raises(LeaseLost):
        db.complete_task_run(old["id"])
    with db.lease_scope(old), pytest.raises(LeaseLost):
        db.upsert_creator("douyin", "stale", "旧 worker", "")
    with db.lease_scope(new):
        db.complete_task_run(new["id"])
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM task_attempt ORDER BY id").fetchall()[0][0] == "abandoned"


def test_finish_rollback_and_idempotency(sqlite_db, monkeypatch):
    db, _ = sqlite_db
    first = db.enqueue_task_run("fixture", {"nested": [1]}, "测试", idempotency_key="same")
    assert db.enqueue_task_run("fixture", {}, "再次", idempotency_key="same")["id"] == first["id"]
    task = db.claim_next_task_run("owner")
    assert task["payload_json"] == {"nested": [1]}
    original = db._transition
    def fail(*args, **kwargs):
        raise RuntimeError("注入原子完成故障")
    monkeypatch.setattr(db, "_transition", fail)
    with db.lease_scope(task), pytest.raises(RuntimeError):
        db.complete_task_run(task["id"])
    assert db.get_task_run(task["id"])["status"] == "running"
    with db.connect() as conn:
        assert conn.execute("SELECT status FROM task_attempt").fetchone()[0] == "running"
        assert conn.execute("SELECT count(*) FROM outbox_event").fetchone()[0] == 0
    monkeypatch.setattr(db, "_transition", original)
    with db.lease_scope(task):
        db.complete_task_run(task["id"])


def test_content_string_identity_and_atomic_preservation(sqlite_db):
    db, _ = sqlite_db
    creator = db.upsert_creator("douyin", "001234", "作者", "https://example.com")
    cid = db.upsert_content_item("douyin", "009876543210987654321", creator, title="国债与ETF")
    a, n = {"status": "success", "result_json": {"数字": "001"}}, {"note_path": "notes/fixture.md"}
    db.replace_transcript_analysis_and_note(cid, {"text_content": "不可变原稿", "status": "success"}, a, n)
    with pytest.raises(ValueError):
        db.replace_transcript_analysis_and_note(cid, {"text_content": ""}, a, n)
    assert db.find_content_item("douyin", "009876543210987654321")["id"] == cid
    assert db.get_current_bundle(cid)["transcript"]["text_content"] == "不可变原稿"
    assert db.get_current_bundle(cid)["analysis"]["result_json"] == {"数字": "001"}
    db.replace_transcript_analysis_and_note(cid, {"text_content": "第二版原稿", "status": "success"}, a, n)
    with db.connect() as conn:
        assert conn.execute("SELECT text_content FROM transcript_revision").fetchone()[0] == "不可变原稿"


def test_bounded_busy_and_json_distinctions(sqlite_db):
    db, _ = sqlite_db
    other = Database(db.database_url, busy_timeout_ms=50)
    other.initialize()
    with db.connect(write=True):
        with pytest.raises(OperationalError, match="locked"):
            other.enqueue_task_run("fixture", {}, "竞争")
    p = db.table("platform")
    with db.connect(write=True) as conn:
        for name, val in (("null", None), ("object", "{}"), ("array", "[]")):
            conn.execute(insert(p).values(code=name, config_json=val))
    with db.connect() as conn:
        rows = conn.execute(select(p.c.config_json).where(p.c.code.in_(("null", "object", "array"))).order_by(p.c.id)).fetchall()
        assert [r[0] for r in rows] == [None, {}, []]
