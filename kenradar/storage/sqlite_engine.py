"""Explicit SQLAlchemy/sqlite3 transactions; no implicit new database creation."""
from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool

JSON_COLUMNS = frozenset({"config_json", "extra", "segments_json", "quality_details", "result_json",
                          "payload_json", "progress_json", "stats_json", "checkpoint_json", "metadata_json",
                          "context", "output_ref", "record_json"})


def database_path(url: str) -> Path:
    parsed = make_url(url)
    if parsed.drivername not in {"sqlite", "sqlite+pysqlite"} or not parsed.database or parsed.database == ":memory:":
        raise ValueError("必须配置本机 SQLite 文件库，不接受内存库")
    path = Path(parsed.database).resolve()
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("SQLite 运行库不可放在网络共享目录")
    return path


def sqlite_engine(url: str, *, busy_timeout_ms: int = 5000) -> Engine:
    database_path(url)
    if sqlite3.sqlite_version_info < (3, 51, 3):
        raise RuntimeError(f"SQLite {sqlite3.sqlite_version} 未达到已修复 WAL 的基线 3.51.3")
    timeout = max(1, min(30000, int(busy_timeout_ms)))
    engine = create_engine(url, poolclass=NullPool, connect_args={"timeout": timeout / 1000})

    @event.listens_for(engine, "connect")
    def configure(dbapi: Any, _: Any) -> None:
        from .sqlite_score import parse_score
        dbapi.create_function("kr_score", 1, parse_score, deterministic=True)
        dbapi.isolation_level = None
        cursor = dbapi.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={timeout}")
        cursor.execute("PRAGMA synchronous=FULL")
        if cursor.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("无法启用 SQLite 外键")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin(connection: Connection) -> None:
        mode = connection.get_execution_options().get("sqlite_transaction", "DEFERRED")
        if mode not in {"DEFERRED", "IMMEDIATE"}:
            raise ValueError("未知 SQLite 事务模式")
        connection.exec_driver_sql(f"BEGIN {mode}")

    return engine


class Row(dict):
    def __getitem__(self, key: Any) -> Any:
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def decode(row: Any) -> Row | None:
    if row is None:
        return None
    result = Row(row._mapping)
    for key in JSON_COLUMNS & result.keys():
        if result[key] is not None and isinstance(result[key], str):
            result[key] = json.loads(result[key])
    return result


class Result:
    def __init__(self, result: Any):
        self.raw = result
        self.rowcount = result.rowcount
        self.lastrowid = result.lastrowid

    def fetchone(self) -> Row | None:
        return decode(self.raw.fetchone())

    def fetchall(self) -> list[Row]:
        return [decode(row) for row in self.raw.fetchall()]


class SQLiteConnection:
    """String SQL must already be SQLite SQL. Core expressions use named binds."""
    def __init__(self, connection: Connection, *, write: bool = False):
        self.raw = connection
        self.write = write

    def execute(self, statement: Any, params: Any = None) -> Result:
        if not self.write:
            read = statement.lstrip().upper().startswith(("SELECT", "PRAGMA", "EXPLAIN")) if isinstance(statement, str) else getattr(statement, "is_select", False)
            if not read:
                raise RuntimeError("写操作必须明确使用 write=True 的短事务")
        if isinstance(statement, str):
            if any(marker in statement for marker in ("%s", "::jsonb", "SKIP LOCKED", "NOW()", "ILIKE")):
                raise NotImplementedError("该查询尚未迁移为 SQLite；拒绝静默 SQL 替换")
            result = self.raw.exec_driver_sql(statement, params or ())
        else:
            result = self.raw.execute(statement, params or {})
        return Result(result)


@contextmanager
def transaction(engine: Engine, path: Path, *, write: bool = False) -> Iterator[SQLiteConnection]:
    if not path.is_file():
        raise RuntimeError("SQLite 文件不存在；请明确执行 migrate 初始化或离线导入，不能自动创建空库")
    with engine.connect().execution_options(sqlite_transaction="IMMEDIATE" if write else "DEFERRED") as conn:
        with conn.begin():
            yield SQLiteConnection(conn, write=write)


def diagnostics(engine: Engine, path: Path) -> dict[str, Any]:
    with transaction(engine, path) as conn:
        version = conn.execute("SELECT sqlite_version()").fetchone()[0]
        json_ok = conn.execute("SELECT json_valid('{\"ok\":true}')").fetchone()[0] == 1
        fts5 = conn.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0] == 1
        wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
        busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    # Transactional write probe leaves no durable business/schema changes.
    with engine.connect().execution_options(sqlite_transaction="IMMEDIATE") as probe:
        tx = probe.begin()
        try:
            probe.exec_driver_sql("CREATE TABLE __kenradar_permission_probe (id INTEGER)")
            probe.exec_driver_sql("INSERT INTO __kenradar_permission_probe VALUES (1)")
        finally:
            tx.rollback()
    return {"sqlite_version": version, "json": json_ok, "fts5": fts5, "journal_mode": wal,
            "foreign_keys": foreign_keys, "synchronous": sync, "busy_timeout": busy,
            "integrity": integrity, "foreign_key_errors": foreign_errors,
            "disk_free_bytes": shutil.disk_usage(path.parent).free, "read_write": True}
