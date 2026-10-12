from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from test_sqlite_v2 import sqlite_db
from kenradar.storage.offline_migration import TABLES, FORMAT, canonical, write_table, import_snapshot, typed, untyped
from kenradar.storage.sqlite_database import Database
from kenradar.storage.sqlite_backup import backup_database, restore_snapshot, check_snapshot, backup_application, restore_application
from kenradar.core.config import load_config
from kenradar.storage.migration_files import snapshot_files, import_files


def fixture_package(db, package):
    package.mkdir()
    manifest = {"format": FORMAT, "source": "sqlite-fixture-not-real-pg", "source_schema": ["s0001_v2"], "tables": {}, "files": []}
    with db.connect() as conn:
        for name in TABLES:
            table = db.table(name)
            rows = [dict(row._mapping) for row in conn.raw.execute(select(table).order_by(list(table.primary_key.columns)[0])).fetchall()]
            columns = {c.name: "jsonb" if c.name in {"extra", "result_json", "config_json", "segments_json", "payload_json", "checkpoint_json"} else str(c.type).lower() for c in table.c}
            manifest["tables"][name] = write_table(package, name, columns, rows)
    (package / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
    return manifest


def test_offline_import_preserves_content_paths_and_pauses_delivery(sqlite_db, tmp_path):
    db, _ = sqlite_db
    creator = db.upsert_creator("douyin", "0001", "fixture", "")
    cid = db.upsert_content_item("douyin", "000000000000002", creator, title="fixture", source_url="https://example.test/old-root/video")
    db.replace_transcript_analysis_and_note(cid, {"text_content": "原始转录 /old-root 不能全文替换", "status": "success"},
        {"status": "success", "result_json": {"body": "/old-root", "array": []}}, {"note_path": "/old-root/notes/fixture.md"})
    delivery = db.enqueue_task_run("notify_content", {"content_item_id": cid}, "fixture delivery")
    db.claim_next_task_run("old-machine")
    db.write_outbox_event("publish:research", {"job_id": 1}, idempotency_key="fixture-delivery")
    package, target = tmp_path / "snapshot", tmp_path / "target.importing.sqlite3"
    fixture_package(db, package)
    result = import_snapshot(package, target, {"/old-root": str(tmp_path / "new-data")})
    assert not result["production_switch"] and not result["real_migration_accepted"]
    imported = Database("sqlite:///" + target.as_posix())
    imported.initialize()
    try:
        assert imported.get_task_run(delivery["id"])["status"] == "paused"
        assert imported.claim_next_task_run("new-machine") is None
        assert imported.claim_outbox_events() == []
        bundle = imported.get_current_bundle(cid)
        assert bundle["transcript"]["text_content"] == "原始转录 /old-root 不能全文替换"
        assert bundle["analysis"]["result_json"] == {"body": "/old-root", "array": []}
        assert bundle["note"]["note_path"] == str(tmp_path / "new-data/notes/fixture.md")
        assert imported.find_content_item("douyin", "000000000000002")["source_url"] == "https://example.test/old-root/video"
    finally:
        imported.close()
    resumed = import_snapshot(package, target, {"/old-root": str(tmp_path / "new-data")}, resume=True)
    assert resumed["tables"] == result["tables"]
    with pytest.raises(FileExistsError):
        import_snapshot(package, target)
    with pytest.raises(ValueError, match="不一致"):
        import_snapshot(package, target, {"/old-root": "different"}, resume=True)


def test_snapshot_tamper_and_exact_numeric_encoding(sqlite_db, tmp_path):
    db, _ = sqlite_db
    package = tmp_path / "snapshot"
    fixture_package(db, package)
    (package / "content_item.jsonl").write_text("corruption", encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        import_snapshot(package, tmp_path / "broken.importing.sqlite3")
    number = 123456789012345678901234567890
    assert untyped(typed(Decimal(number))) == number
    with pytest.raises(ValueError, match="无损"):
        untyped(typed(Decimal("0.123456789012345678901")))
    with pytest.raises(ValueError, match="临时库"):
        import_snapshot(package, tmp_path / "production.sqlite3")


def test_live_wal_backup_and_restore_full_content(sqlite_db, tmp_path):
    db, _ = sqlite_db
    db.enqueue_task_run("fixture", {"标识": "0001", "values": []}, "fixture snapshot")
    backup = tmp_path / "backups/snapshot.sqlite3"
    snapshot = backup_database(db.path, backup)
    db.enqueue_task_run("fixture", {}, "snapshot之后新增")
    restored = restore_snapshot(backup, tmp_path / "recovered.restoring.sqlite3")
    assert restored["checks"]["content_hashes"] == snapshot["content_hashes"]
    assert restored["checks"]["counts"]["task_run"] == 1
    assert check_snapshot(db.path)["counts"]["task_run"] == 2
    with pytest.raises(FileExistsError):
        backup_database(db.path, backup)
    with pytest.raises(ValueError, match="临时库"):
        restore_snapshot(backup, db.path)


def test_note_file_copy_hash_and_no_overwrite(sqlite_db, tmp_path):
    db, _ = sqlite_db
    old, new = tmp_path / "old-data", tmp_path / "new-data"
    note = old / "notes/douyin/fixture.md"
    note.parent.mkdir(parents=True)
    body = "---\nvideo_id: '0002'\n---\n> [!summary]\n原始内容 /old-root\n"
    note.write_text(body, encoding="utf-8")
    creator = db.upsert_creator("douyin", "0001", "fixture", "")
    cid = db.upsert_content_item("douyin", "0002", creator, title="fixture")
    db.replace_transcript_analysis_and_note(cid, {"text_content": "原稿"}, {"result_json": {}}, {"note_path": str(note)})
    package = tmp_path / "snapshot"
    manifest = fixture_package(db, package)
    with pytest.raises(ValueError, match="停止"):
        snapshot_files(old, package)
    manifest.update(snapshot_files(old, package, writers_stopped=True))
    (package / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
    mappings = {str(old): str(new)}
    result = import_snapshot(package, tmp_path / "files.importing.sqlite3", mappings)
    assert result["status"] == "offline_verified_real_acceptance_pending"
    assert not result["missing_required_files"]
    copied = new / "notes/douyin/fixture.md"
    assert copied.read_text(encoding="utf-8") == body
    assert import_files(package, manifest, mappings)["verified"] == ["notes/douyin/fixture.md"]
    copied.write_text("必须保留用户已修改文件", encoding="utf-8")
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        import_files(package, manifest, mappings)
    assert copied.read_text(encoding="utf-8") == "必须保留用户已修改文件"


def test_full_application_backup_requires_freeze_and_restores_new_paths(sqlite_db, tmp_path):
    db, config_path = sqlite_db
    note = tmp_path / "notes/douyin/fixture.md"
    note.parent.mkdir(parents=True)
    note.write_text("一、内容简述\n四、视频原始转录\n原稿不能变", encoding="utf-8")
    creator = db.upsert_creator("douyin", "0001", "fixture", "")
    cid = db.upsert_content_item("douyin", "0002", creator, title="fixture")
    db.replace_transcript_analysis_and_note(cid, {"text_content": "原始转录"}, {"result_json": {}}, {"note_path": str(note)})
    config = load_config(config_path)
    with pytest.raises(ValueError, match="停止"):
        backup_application(config, tmp_path / "blocked")
    package = tmp_path / "application-backup"
    backup_application(config, package, writers_stopped=True)
    restored_root = tmp_path / "application.restoring"
    target = tmp_path / "full.restoring.sqlite3"
    result = restore_application(package, target, restored_root)
    assert result["files"]["verified"] == ["notes/douyin/fixture.md"]
    assert note.read_text(encoding="utf-8") == (restored_root / "notes/douyin/fixture.md").read_text(encoding="utf-8")
    recovered = Database("sqlite:///" + target.as_posix())
    recovered.initialize()
    try:
        assert recovered.get_current_bundle(cid)["note"]["note_path"] == str(restored_root / "notes/douyin/fixture.md")
        assert recovered.get_current_bundle(cid)["transcript"]["text_content"] == "原始转录"
    finally:
        recovered.close()
    assert db.get_current_bundle(cid)["note"]["note_path"] == str(note)


def test_import_process_crash_after_table_commit_resumes_without_duplicates(sqlite_db, tmp_path):
    db, _ = sqlite_db
    creator = db.upsert_creator("douyin", "0001", "fixture", "")
    db.upsert_content_item("douyin", "0002", creator, title="fixture")
    package, target = tmp_path / "snapshot", tmp_path / "crash.importing.sqlite3"
    fixture_package(db, package)
    code = '''import os,sys
sys.modules['psycopg']=None
from kenradar.storage import offline_migration as migration
original=migration._write_state
def checkpoint(path,state):
    if 'content_item' in state['tables']:
        os._exit(23)
    original(path,state)
migration._write_state=checkpoint
migration.import_snapshot(sys.argv[1],sys.argv[2])
'''
    result = subprocess.run([sys.executable, "-c", code, str(package), str(target)], timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 23
    recovered = import_snapshot(package, target, resume=True)
    assert recovered["tables"]["content_item"]["rows"] == 1
    target_db = Database("sqlite:///" + target.as_posix())
    target_db.initialize()
    try:
        assert target_db.find_content_item("douyin", "0002")
        assert target_db.upsert_creator("douyin", "0003", "新作者", "") > creator
    finally:
        target_db.close()
