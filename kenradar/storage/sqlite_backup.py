"""Online SQLite backup API snapshots; restore always creates a new file."""
from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from pathlib import Path
from urllib.parse import quote
import yaml

from .offline_migration import canonical, sha_file, typed, _reject_secrets
from .sqlite_database import utc_now


def readonly_connection(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError("源数据库不存在")
    return sqlite3.connect("file:" + quote(path.as_posix(), safe="/:") + "?mode=ro", uri=True, timeout=5)


def check_snapshot(path):
    with readonly_connection(path) as connection:
        connection.row_factory = sqlite3.Row
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        head = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        # Names come solely from SQLite schema; quote them rather than accepting SQL.
        counts, hashes = {}, {}
        for name in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            info = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            keys = [r["name"] for r in sorted(info, key=lambda r: r["pk"]) if r["pk"]]
            ordering = ",".join('"' + k.replace('"', '""') + '"' for k in keys) or "rowid"
            digest, count = hashlib.sha256(), 0
            for row in connection.execute(f"SELECT * FROM {quoted} ORDER BY {ordering}"):
                digest.update((canonical(typed(dict(row))) + "\n").encode("utf-8"))
                count += 1
            counts[name], hashes[name] = count, digest.hexdigest()
    if integrity != "ok" or foreign_errors:
        raise ValueError("备份完整性或外键校验失败")
    return {"integrity": integrity, "foreign_key_errors": foreign_errors, "schema": head,
            "sqlite_version": sqlite3.sqlite_version, "counts": counts, "content_hashes": hashes, "sha256": sha_file(path)}


def backup_database(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        raise ValueError("备份不能覆盖源库")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb"):
        pass
    src = readonly_connection(source)
    dst = sqlite3.connect(target, timeout=5)
    try:
        src.backup(dst, pages=128, sleep=.05)
    finally:
        dst.close()
        src.close()
    checks = check_snapshot(target)
    manifest = {"format": "kenradar-sqlite-snapshot/1", "created_at": utc_now(),
                "kind": "database_snapshot", "file": target.name, **checks}
    target.with_suffix(target.suffix + ".manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
    return manifest


def restore_snapshot(snapshot, target):
    snapshot, target = Path(snapshot).resolve(), Path(target).resolve()
    if not target.name.endswith(".restoring.sqlite3"):
        raise ValueError("恢复仅写入 *.restoring.sqlite3 临时库，不替换运行库")
    manifest = json.loads(snapshot.with_suffix(snapshot.suffix + ".manifest.json").read_text(encoding="utf-8"))
    actual = check_snapshot(snapshot)
    if manifest.get("format") != "kenradar-sqlite-snapshot/1" or actual["sha256"] != manifest["sha256"] or actual["counts"] != manifest["counts"]:
        raise ValueError("备份 manifest 与数据库不一致")
    restored = backup_database(snapshot, target)
    if restored["counts"] != actual["counts"] or restored["content_hashes"] != actual["content_hashes"] or restored["schema"] != actual["schema"]:
        raise ValueError("恢复后的数量/schema 不一致")
    return {"target": str(target), "checks": restored, "production_switch": False}


def _nonsecret_config(value):
    if isinstance(value, dict):
        return {key: _nonsecret_config(item) for key, item in value.items()
                if not any(token in str(key).lower() for token in ("cookie", "password", "api_key", "webhook", "authorization", "access_token"))
                and not (key == "env_var" and item and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item)))}
    if isinstance(value, list):
        return [_nonsecret_config(item) for item in value]
    return value


def backup_application(config, package, *, writers_stopped=False):
    """Files/config require a stopped-writer window, unlike DB-only snapshots."""
    from .sqlite_engine import database_path, JSON_COLUMNS
    from .migration_files import snapshot_files
    if not writers_stopped:
        raise ValueError("完整应用备份必须先停止文件、配置和数据库写入")
    if config.database_type != "sqlite":
        raise ValueError("仅备份 SQLite 应用")
    runtime = config.data_dir / "runtime/processes.json"
    if runtime.is_file():
        from kenradar.runtime_control import _owned
        states = json.loads(runtime.read_text(encoding="utf-8"))
        if any(_owned(record, config.path.resolve()) for record in states.values()):
            raise ValueError("仍有受管理的 Web/worker，先停止再执行完整备份")
    package = Path(package).resolve()
    package.mkdir(parents=True, exist_ok=False)
    config_hash = sha_file(config.path)
    config_data = _nonsecret_config(yaml.safe_load(config.path.read_text(encoding="utf-8")))
    config_file = package / "config.nonsecret.yaml"
    config_file.write_text(yaml.safe_dump(config_data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    snapshot = package / "database.sqlite3"
    db_manifest = backup_database(database_path(config.database_url), snapshot)
    # Ordinary application packages refuse old config/payload secrets stored in
    # the DB; they must be transferred through a separate local sensitive flow.
    with readonly_connection(snapshot) as connection:
        for name in db_manifest["counts"]:
            quoted = '"' + name.replace('"', '""') + '"'
            fields = {r[1] for r in connection.execute(f"PRAGMA table_info({quoted})")} & JSON_COLUMNS
            for field in fields:
                for row in connection.execute(f'SELECT "{field}" FROM {quoted} WHERE "{field}" IS NOT NULL'):
                    _reject_secrets(json.loads(row[0]))
    files = snapshot_files(config.data_dir, package, writers_stopped=True)
    included = {str(Path(entry["source_path"]).resolve()) for entry in files["files"]}
    gaps = []
    with readonly_connection(snapshot) as connection:
        for name, field, condition in (("content_note", "note_path", "1=1"), ("research_job", "report_path", "1=1"), ("artifact", "path", "status='active'")):
            # Constant identifiers, explicit required-reference fields only.
            for identity, value in connection.execute(f'SELECT id,"{field}" FROM "{name}" WHERE {condition} AND "{field}" IS NOT NULL AND "{field}"<>\'\''):
                resolved = config.resolve_path(value)
                if str(resolved) not in included:
                    gaps.append({"table": name, "id": identity, "field": field, "reason": "missing_or_not_in_file_snapshot"})
    if sha_file(config.path) != config_hash:
        raise ValueError("配置在备份期间变化")
    manifest = {"format": "kenradar-application-backup/1", "kind": "application_with_file_gaps" if gaps else "complete_application", "required_file_gaps": gaps,
        "created_at": utc_now(), "database": db_manifest, "config": {"file": config_file.name, "sha256": sha_file(config_file)},
        "python": __import__("sys").version.split()[0], "production_switch": False, **files}
    (package / "application.manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
    return manifest


def restore_application(package, target, data_root):
    from .migration_files import import_files
    from .offline_migration import PATH_FIELDS, mapped_path
    from .sqlite_database import Database
    from sqlalchemy import select, update
    package, data_root = Path(package).resolve(), Path(data_root).resolve()
    if not data_root.name.endswith(".restoring"):
        raise ValueError("文件恢复只允许全新 *.restoring 数据目录")
    if data_root.exists():
        raise FileExistsError("恢复数据目录已存在，拒绝覆盖")
    manifest = json.loads((package / "application.manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "kenradar-application-backup/1":
        raise ValueError("应用备份格式不支持")
    if manifest.get("kind") != "complete_application" or manifest.get("required_file_gaps"):
        raise ValueError("应用备份存在必要文件缺项，不能宣称完整恢复")
    if check_snapshot(package / "database.sqlite3")["sha256"] != manifest["database"]["sha256"]:
        raise ValueError("应用 manifest 的数据库哈希不一致")
    config_file = package / "config.nonsecret.yaml"
    if manifest["config"]["file"] != config_file.name or sha_file(config_file) != manifest["config"]["sha256"]:
        raise ValueError("备份配置哈希不一致")
    result = restore_snapshot(package / "database.sqlite3", target)
    data_root.mkdir(parents=True, exist_ok=False)
    mappings = {manifest["files_root"]: str(data_root)}
    files = import_files(package, manifest, mappings)
    if files["missing"] or files["unmapped"]:
        raise ValueError("备份文件核对未通过")
    restored = Database("sqlite:///" + Path(target).resolve().as_posix())
    restored.initialize()
    changed = {}
    try:
        for name, fields in PATH_FIELDS.items():
            table = restored.table(name)
            with restored.connect(write=True) as conn:
                rows = conn.execute(select(table.c.id, *(table.c[f] for f in fields))).fetchall()
                changed[name] = 0
                for row in rows:
                    values = {field: mapped_path(row[field], mappings) for field in fields if row[field]}
                    values = {field: val for field, val in values.items() if val != row[field]}
                    if values:
                        conn.execute(update(table).where(table.c.id == row["id"]).values(**values))
                        changed[name] += 1
        checks = restored.diagnostic()
    finally:
        restored.close()
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    config.setdefault("app", {}).update(data_dir=str(data_root), database_url="sqlite:///" + Path(target).resolve().as_posix())
    config["schedule"] = {**config.get("schedule", {}), "enabled": False}
    config["publishing"] = {"github_pages": {"enabled": False}, "github_sync": {"enabled": False}}
    config["notification"] = {"channels": {"feishu": {"enabled": False}}, "research_completion_enabled": False}
    (data_root / "config.restored.nonsecret.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return {**result, "files": files, "path_mapping_counts": changed, "diagnostic": checks,
            "config": str(data_root / "config.restored.nonsecret.yaml"), "production_switch": False}
