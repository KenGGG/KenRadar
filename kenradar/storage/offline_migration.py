"""Read-only PG snapshots and resumable offline V2 imports. No production switch."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import sqlite3
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import insert, select, delete

from .sqlite_database import Database, utc_now
from .sqlite_engine import JSON_COLUMNS, sqlite_engine

FORMAT = "kenradar-v2-offline/1"
TABLES = ("platform", "creator", "source_subscription", "content_item", "transcript", "ai_analysis", "content_note",
          "content_curation", "research_job", "research_job_item", "task_run", "task_attempt", "task_step",
          "state_transition", "artifact", "outbox_event", "resource_lease", "publication_log", "push_log", "alert_log",
          "source_daily_metrics", "source_topic_metrics")
PATH_FIELDS = {"content_item": {"local_path"}, "transcript": {"text_path", "json_path"},
               "content_note": {"note_path"}, "research_job": {"report_path"}, "artifact": {"path"}}
DELIVERY_TYPES = {"publish_content", "notify_content", "notify_batch", "publish_research_job", "publish_pages", "github_sync", "push_feishu"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def typed(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("导出时间缺少时区")
        return {"$datetime": value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (bytes, memoryview)):
        return {"$bytes": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("非有限数字不能导出")
    if isinstance(value, dict):
        return {k: typed(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [typed(v) for v in value]
    return value


def untyped(value):
    if isinstance(value, dict) and len(value) == 1:
        if "$datetime" in value or "$date" in value:
            return next(iter(value.values()))
        if "$decimal" in value:
            decimal = Decimal(value["$decimal"])
            # V2 integer fields must not travel through binary floats.
            if decimal == decimal.to_integral_value():
                return int(decimal)
            candidate = float(decimal)
            if Decimal(str(candidate)) != decimal:
                raise ValueError("目标 REAL 无法无损表达源 Decimal，需明确字段映射")
            return candidate
        if "$bytes" in value:
            return base64.b64decode(value["$bytes"], validate=True)
    return value


def write_table(package, name, columns, rows):
    if name not in TABLES:
        raise ValueError("未知 V2 表")
    path = Path(package) / f"{name}.jsonl"
    count, references = 0, []
    classifications = {key: Counter() for key in ("platform_id", "status") if key in columns}
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            for key, counter in classifications.items():
                counter[canonical(row.get(key))] += 1
            for key in JSON_COLUMNS & row.keys():
                value = row[key]
                if isinstance(value, str):
                    value = json.loads(value)
                _reject_secrets(value)
            for key in PATH_FIELDS.get(name, set()):
                if row.get(key):
                    candidate = Path(str(row[key]))
                    exists = candidate.is_file()
                    references.append({"id": row.get("id"), "field": key, "path": str(row[key]),
                        "required": name in {"content_note", "research_job"} or (name == "artifact" and row.get("status") == "active"),
                        "category": "processing_intermediate" if name == "transcript" else "media" if name == "content_item" else "persistent_artifact",
                        "expected_cleaned": name == "content_item" and bool(row.get("media_deleted_at")),
                        "source_exists": exists, "sha256": sha_file(candidate) if exists else None})
            handle.write(canonical({k: typed(v) for k, v in row.items()}) + "\n")
            count += 1
    return {"columns": columns, "rows": count, "sha256": sha_file(path), "file": path.name,
            "path_references": references, "classifications": {k: dict(v) for k, v in classifications.items()}}


def _reject_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "env_var" and item and not __import__("re").fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item)):
                raise ValueError("普通迁移包不能携带 env_var 中的明文密钥")
            if str(key).lower() in {"api_key", "cookie", "cookies", "password", "webhook_url", "authorization", "access_token"} and item:
                if not (isinstance(item, str) and item.startswith("${") and item.endswith("}")):
                    raise ValueError("普通迁移包检测到秘密字段；请先通过独立敏感资料流程处理，不显示真实值")
            _reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secrets(item)


def export_postgres(dsn, package, *, data_root=None, writers_stopped=False):
    """Only this optional source-side function imports psycopg."""
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    package = Path(package).resolve()
    package.mkdir(parents=True, exist_ok=False)
    manifest = {"format": FORMAT, "created_at": utc_now(), "source": "postgresql", "tables": {},
                "files": [], "file_consistency": "requires_source_writers_paused_and_file_snapshot"}
    # Database consistency is real. File consistency is not implied by MVCC.
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as connection:
        connection.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            manifest["snapshot"] = dict(connection.execute("SELECT txid_current_snapshot()::text AS id, current_setting('server_version') AS server_version").fetchone())
            manifest["source_schema"] = [r["version_num"] for r in connection.execute("SELECT version_num FROM alembic_version")]
            actual = {r["table_name"] for r in connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")}
            unknown = actual - set(TABLES) - {"alembic_version"}
            missing = set(TABLES) - actual
            if unknown or missing:
                raise ValueError(f"表覆盖未确认；多余={sorted(unknown)} 缺少={sorted(missing)}")
            for name in TABLES:
                columns = {r["column_name"]: r["data_type"] for r in connection.execute(
                    "SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position", (name,))}
                projected = [sql.SQL("{}::text AS {}").format(sql.Identifier(k), sql.Identifier(k)) if v in {"json", "jsonb"}
                             else sql.Identifier(k) for k, v in columns.items()]
                primary = "resource_key" if name == "resource_lease" else "id"
                statement = sql.SQL("SELECT {} FROM {} ORDER BY {}").format(sql.SQL(",").join(projected), sql.Identifier(name), sql.Identifier(primary))
                with connection.cursor(name=f"export_{name}") as cursor:
                    cursor.execute(statement)
                    manifest["tables"][name] = write_table(package, name, columns, cursor)
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
    if data_root is not None:
        from .migration_files import snapshot_files
        manifest.update(snapshot_files(data_root, package, writers_stopped=writers_stopped))
    (package / "manifest.json").write_text(canonical(manifest) + "\n", encoding="utf-8")
    return manifest


def initialize_target(path):
    path = Path(path)
    # Exclusively reserve the new filename; this function never opens an old DB.
    with path.open("xb"):
        pass
    url = "sqlite:///" + path.resolve().as_posix()
    engine = sqlite_engine(url)
    try:
        with engine.connect() as conn:
            if conn.connection.driver_connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise RuntimeError("无法建立 WAL")
            cfg = Config()
            cfg.set_main_option("script_location", str(Path(__file__).with_name("sqlite_migrations")))
            cfg.attributes["connection"] = conn
            with conn.begin():
                command.upgrade(cfg, "head")
    finally:
        engine.dispose()


def mapped_path(value, mappings):
    if not value:
        return value
    source = str(value).replace("\\", "/")
    for old, new in sorted(mappings.items(), key=lambda pair: -len(pair[0])):
        root = old.replace("\\", "/").rstrip("/")
        if source == root or source.startswith(root + "/"):
            suffix = source[len(root):].lstrip("/")
            if ".." in PurePosixPath(suffix).parts:
                raise ValueError("路径映射包含父目录跳转")
            return str(Path(new) / Path(suffix))
    return value


def normalized_row(name, record, columns, mappings, stamp, changes):
    row = {key: untyped(value) for key, value in record.items()}
    for key in row:
        if key in JSON_COLUMNS and row[key] is not None:
            # Source JSONB was exported as text so arbitrary numeric precision
            # and NULL vs [] vs {} are not lost through a float JSON roundtrip.
            if not isinstance(row[key], str):
                row[key] = canonical(row[key])
        if key in PATH_FIELDS.get(name, set()):
            row[key] = mapped_path(row[key], mappings)
        if columns[key] == "boolean" and row[key] is not None:
            row[key] = int(row[key])
    original = row.get("status")
    if name == "task_run" and original in {"running", "queued", "retry_wait"}:
        row.update(status="paused", lease_expires_at=None, worker_name="", paused_at=stamp)
        if "lease_token" in columns:
            row["lease_token"] = None
        changes.append({"table": name, "id": row["id"], "old": original, "new": "paused", "reason": "migration_requires_review"})
    if name == "task_attempt" and original == "running":
        row.update(status="abandoned", finished_at=stamp)
        changes.append({"table": name, "id": row["id"], "old": original, "new": "abandoned", "reason": "migration_invalidated_lease"})
    if name == "task_step" and original in {"pending", "running", "retry_wait"}:
        row.update(status="paused", lease_expires_at=None, locked_by=None)
        if "lease_token" in columns:
            row["lease_token"] = None
        changes.append({"table": name, "id": row["id"], "old": original, "new": "paused", "reason": "migration_requires_review"})
    if name == "outbox_event" and original in {"pending", "running"}:
        row.update(status="unknown" if original == "running" else "paused", lease_expires_at=None, locked_by=None)
        changes.append({"table": name, "id": row["id"], "old": original, "new": row["status"], "reason": "migration_delivery_requires_reconciliation"})
    if name in {"publication_log", "push_log"} and original == "running":
        row["status"] = "unknown"
        changes.append({"table": name, "id": row["id"], "old": original, "new": "unknown", "reason": "migration_delivery_requires_reconciliation"})
    if name == "resource_lease":
        row["lease_expires_at"] = "1970-01-01T00:00:00.000000Z"
    # Only source-present columns are compared, additional fencing fields get
    # their new-schema defaults. JSON/body/URL strings are never path-rewritten.
    return {k: v for k, v in row.items() if k in columns}


def _row_hash(rows):
    digest = hashlib.sha256()
    for row in rows:
        digest.update((canonical(row) + "\n").encode("utf-8"))
    return digest.hexdigest()


def import_snapshot(package, target, mappings=None, *, resume=False):
    from kenradar.core.file_lock import flock, LOCK_EX, LOCK_UN
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.with_suffix(target.suffix + ".import.lock").open("a+") as lock:
        flock(lock.fileno(), LOCK_EX)
        try:
            return _import_snapshot(package, target, mappings, resume=resume)
        finally:
            flock(lock.fileno(), LOCK_UN)


def _import_snapshot(package, target, mappings=None, *, resume=False):
    package, target = Path(package).resolve(), Path(target).resolve()
    mappings = mappings or {}
    if not target.name.endswith(".importing.sqlite3"):
        raise ValueError("只导入 *.importing.sqlite3 临时库，不正式切换生产写入")
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT or set(manifest["tables"]) != set(TABLES):
        raise ValueError("快照格式或表覆盖不完整")
    identity = hashlib.sha256((sha_file(manifest_path) + canonical(mappings)).encode()).hexdigest()
    state_path = target.with_suffix(target.suffix + ".import-state.json")
    if target.exists():
        if not resume or not state_path.is_file():
            raise FileExistsError("目标已存在，拒绝覆盖；恢复导入必须提供同一 manifest")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["identity"] != identity:
            raise ValueError("恢复导入的 manifest/路径映射不一致")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        initialize_target(target)
        state = {"identity": identity, "tables": {}, "status": "importing", "normalized_at": utc_now()}
        _write_state(state_path, state)
    db = Database("sqlite:///" + target.as_posix())
    db.initialize()
    try:
        changes = []
        for table in db.metadata.sorted_tables:
            name = table.name
            if name not in TABLES:
                continue
            entry = manifest["tables"][name]
            if entry["file"] != f"{name}.jsonl":
                raise ValueError("快照文件名不合法")
            source = package / entry["file"]
            if sha_file(source) != entry["sha256"]:
                raise ValueError(f"快照表校验失败: {name}")
            columns = entry["columns"]
            unknown = set(columns) - set(table.c.keys())
            if unknown:
                raise ValueError(f"源字段未映射: {name}/{sorted(unknown)}")
            rows = [normalized_row(name, json.loads(line), columns, mappings, state["normalized_at"], changes) for line in source.read_text(encoding="utf-8").splitlines()]
            if len(rows) != entry["rows"]:
                raise ValueError(f"源数量不一致: {name}")
            primary = list(table.primary_key.columns)[0]
            stmt = select(*(table.c[k] for k in columns)).order_by(primary)
            if name == "state_transition":
                stmt = stmt.where((table.c.object_type != "migration") | table.c.actor.is_(None) | (table.c.actor != identity))
            expected = _row_hash(rows)
            with db.connect(write=True) as conn:
                if name not in state["tables"]:
                    conn.execute("PRAGMA defer_foreign_keys=ON")
                    if name == "platform":
                        conn.execute(delete(table))  # Fresh baseline seeds, never original production data.
                    # Whole-table replace also recovers a crash after commit but
                    # before its checkpoint file. No upsert duplicates records.
                    existing = conn.execute(select(primary).limit(1)).fetchone()
                    if rows and not existing:
                        conn.raw.execute(insert(table), rows)
                actual = [dict(r._mapping) for r in conn.raw.execute(stmt).fetchall()]
                if len(actual) != len(rows) or _row_hash(actual) != expected:
                    raise ValueError(f"目标内容/主键校验失败: {name}")
            classified = {key: dict(Counter(canonical(r.get(key)) for r in actual)) for key in ("platform_id", "status") if key in columns}
            state["tables"][name] = {"rows": len(rows), "normalized_sha256": expected, "columns": list(columns),
                "source_classifications": entry.get("classifications", {}), "target_classifications": classified}
            _write_state(state_path, state)
        audit = db.table("state_transition")
        with db.connect(write=True) as conn:
            for change in changes:
                object_id = f"{change['table']}:{change['id']}"
                if not conn.execute(select(audit.c.id).where(audit.c.object_type == "migration", audit.c.object_id == object_id, audit.c.actor == identity)).fetchone():
                    conn.execute(insert(audit).values(object_type="migration", object_id=object_id, actor=identity,
                        old_status=change["old"], new_status=change["new"], reason=change["reason"], created_at=state["normalized_at"]))
        diagnostic = db.diagnostic()
        if diagnostic["integrity"] != "ok" or diagnostic["foreign_key_errors"]:
            raise ValueError("目标完整性/外键核对失败")
        from .migration_files import import_files
        files = import_files(package, manifest, mappings)
        references = []
        for name, entry in manifest["tables"].items():
            for reference in entry.get("path_references", []):
                target_path = Path(mapped_path(reference["path"], mappings))
                exists = target_path.is_file()
                matches = exists and reference.get("sha256") is not None and sha_file(target_path) == reference["sha256"]
                references.append({**reference, "table": name, "target_path": str(target_path), "target_exists": exists, "hash_matches": matches})
        missing_required = [r for r in references if r["required"] and not r["hash_matches"]]
        files_complete = "files_root" in manifest and not files["missing"] and not files["unmapped"] and not missing_required
        state.update(status="offline_verified_real_acceptance_pending" if files_complete else "database_verified_files_pending",
            files=files, file_references=references, missing_required_files=missing_required,
            diagnostic=diagnostic, normalizations=changes,
            source_kind=manifest.get("source"), real_migration_accepted=False, production_switch=False)
        _write_state(state_path, state)
        return state
    finally:
        db.close()


def _write_state(path, state):
    temp = path.with_suffix(path.suffix + ".new")
    temp.write_text(canonical(state) + "\n", encoding="utf-8")
    os.replace(temp, path)
