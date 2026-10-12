"""V2 SQLite backend. All mutations are Core expressions in short transactions."""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import MetaData, Table, and_, or_, select, update, insert, delete, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from kenradar.domain.states import is_permanent_error, normalize_error_code, retry_delay_seconds
from kenradar.storage.sqlite_engine import JSON_COLUMNS, database_path, diagnostics, sqlite_engine, transaction
from kenradar.storage.sqlite_content import ContentMethods
from kenradar.storage.sqlite_research import ResearchMethods
from kenradar.storage.sqlite_audit import AuditMethods


def utc_now(seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def encode(values: dict[str, Any]) -> dict[str, Any]:
    return {k: json.dumps(v, ensure_ascii=False, allow_nan=False) if k in JSON_COLUMNS and v is not None else v
            for k, v in values.items()}


class LeaseLost(RuntimeError):
    pass


class Database(ContentMethods, ResearchMethods, AuditMethods):
    dialect = "sqlite"

    def __init__(self, database_url: str, *, busy_timeout_ms: int = 5000):
        self.database_url = database_url
        self.path = database_path(database_url)
        self.engine = sqlite_engine(database_url, busy_timeout_ms=busy_timeout_ms)
        self.metadata = MetaData()
        self.config = None
        self._lease: ContextVar[dict | None] = ContextVar(f"lease-{id(self)}", default=None)
        self._step_lease: ContextVar[dict | None] = ContextVar(f"step-lease-{id(self)}", default=None)
        self._active: ContextVar[Any] = ContextVar(f"connection-{id(self)}", default=None)
        self.current_content = self
        self.task_runs = self
        from kenradar.storage.sqlite_runtime import Runtime
        self.runtime = Runtime(self)
        self.source_monitor = self
        from kenradar.storage.sqlite_publication import PublicationRepository
        self.publications = PublicationRepository(self)
        from kenradar.storage.sqlite_research import ResearchRepository
        self.research_jobs = ResearchRepository(self)

    def close(self) -> None:
        self.engine.dispose()

    def table(self, name: str) -> Table:
        if name not in self.metadata.tables:
            if not self.path.is_file():
                raise RuntimeError("数据库未初始化")
            Table(name, self.metadata, autoload_with=self.engine)
        return self.metadata.tables[name]

    def initialize(self) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            if not row or row[0] != "s0001_v2":
                raise RuntimeError("SQLite schema 未迁移至 s0001_v2")
        # Reflect before writes: reflection must not open a second connection
        # from inside an IMMEDIATE write transaction.
        self.metadata.reflect(bind=self.engine)

    @contextmanager
    def lease_scope(self, task: dict):
        token = self._lease.set(task)
        try:
            yield
        finally:
            self._lease.reset(token)

    @contextmanager
    def step_lease_scope(self, step: dict):
        token = self._step_lease.set(step)
        try:
            yield
        finally:
            self._step_lease.reset(token)

    @contextmanager
    def connect(self, *, write: bool = False):
        if self._active.get() is not None:
            raise RuntimeError("嵌套数据库事务被拒绝；原子操作必须复用同一连接")
        with transaction(self.engine, self.path, write=write) as conn:
            marker = self._active.set(conn)
            try:
                if write and self._lease.get():
                    self.assert_lease(conn, self._lease.get())
                if write and self._step_lease.get():
                    self.runtime._assert(conn, self._step_lease.get(), "task_step", "locked_by")
                yield conn
            finally:
                self._active.reset(marker)

    def assert_lease(self, conn: Any, task: dict) -> None:
        t = self.table("task_run")
        row = conn.execute(select(t.c.id).where(
            t.c.id == task["id"], t.c.status == "running", t.c.lease_token == task.get("lease_token"),
            t.c.worker_name == task.get("worker_name"), t.c.attempt == task.get("attempt"),
            t.c.lease_expires_at > utc_now())).fetchone()
        if not task.get("lease_token") or not row:
            raise LeaseLost(f"任务 {task['id']} 租约已失效，拒绝旧 worker 写入")

    def diagnostic(self) -> dict:
        return diagnostics(self.engine, self.path)

    def enqueue_task_step(self, *args, **kwargs):
        return self.runtime.enqueue_task_step(*args, **kwargs)

    def claim_next_task_step(self, *args, **kwargs):
        return self.runtime.claim_next_task_step(*args, **kwargs)

    def complete_task_step(self, *args, **kwargs):
        return self.runtime.complete_task_step(*args, **kwargs)

    def heartbeat_task_step(self, *args, **kwargs):
        return self.runtime.heartbeat_task_step(*args, **kwargs)

    def fail_task_step(self, *args, **kwargs):
        return self.runtime.fail_task_step(*args, **kwargs)

    def write_outbox_event(self, *args, **kwargs):
        return self.runtime.write_outbox_event(*args, **kwargs)

    def claim_outbox_events(self, *args, **kwargs):
        return self.runtime.claim_outbox_events(*args, **kwargs)

    def complete_outbox_event(self, *args, **kwargs):
        return self.runtime.complete_outbox_event(*args, **kwargs)

    def fail_outbox_event(self, *args, **kwargs):
        return self.runtime.fail_outbox_event(*args, **kwargs)

    def _upsert(self, table: str, values: dict, keys: tuple[str, ...], *, conn: Any = None) -> dict:
        t = self.table(table)
        if conn is None:
            with self.connect(write=True) as c:
                return self._upsert(table, values, keys, conn=c)
        values = dict(values)
        old = conn.execute(select(t).where(*(t.c[k] == values[k] for k in keys))).fetchone()
        if old and table in {"creator", "content_item", "source_subscription"}:
            if "extra" in values:
                values["extra"] = {**(old["extra"] or {}), **(values["extra"] or {})}
            preserved = {"profile_url"} if table == "creator" else {"publish_time", "duration", "source_url", "media_url", "cover_url", "local_path"}
            for key in preserved & values.keys():
                if values[key] is None:
                    values[key] = old[key]
            if table == "content_item" and old["download_status"] == "done" and values.get("download_status") == "pending":
                values["download_status"] = "done"
        data = encode(values)
        stmt = sqlite_insert(t).values(**data)
        changes = {k: stmt.excluded[k] for k in data if k not in keys and k not in {"id", "created_at"}}
        stmt = stmt.on_conflict_do_update(index_elements=list(keys), set_=changes).returning(t)
        return dict(conn.execute(stmt).fetchone())

    def ensure_platform(self, code: str, display_name: str | None = None) -> int:
        return self._upsert("platform", {"code": code, "display_name": display_name or code}, ("code",))["id"]

    def upsert_creator(self, platform: str, creator_id: str, name: str, url: str,
                       enabled: bool = True, extra: dict | None = None) -> int:
        return self._upsert("creator", {"platform_id": self.ensure_platform(platform),
            "platform_uid": str(creator_id), "nickname": name, "profile_url": url,
            "enabled": enabled, "extra": extra or {}, "updated_at": utc_now()}, ("platform_id", "platform_uid"))["id"]

    def upsert_blogger(self, url: str, name: str, sec_uid: str, enabled: bool = True,
                       *, preserve_existing_enabled: bool = False) -> int:
        if preserve_existing_enabled:
            t = self.table("creator")
            pid = self.ensure_platform("douyin")
            with self.connect() as conn:
                old = conn.execute(select(t).where(t.c.platform_id == pid, t.c.platform_uid == sec_uid)).fetchone()
                if old:
                    enabled = bool(old["enabled"])
        return self.upsert_creator("douyin", sec_uid, name, url, enabled)

    def upsert_content_item(self, platform: str, content_id: str, creator_id: int, **fields: Any) -> int:
        allowed = set(self.table("content_item").c.keys()) - {"id", "platform_id", "content_id", "creator_id"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"未知内容字段: {sorted(unknown)}")
        if fields.get("publish_time"):
            value = fields["publish_time"]
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value.tzinfo is None:
                raise ValueError("发布时间必须包含时区")
            fields["publish_time"] = value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        return self._upsert("content_item", {"platform_id": self.ensure_platform(platform),
            "content_id": str(content_id), "creator_id": creator_id, **fields,
            "updated_at": utc_now()}, ("platform_id", "content_id"))["id"]

    def find_content_item(self, platform: str, external_id: str) -> dict | None:
        t, p = self.table("content_item"), self.table("platform")
        with self.connect() as conn:
            row = conn.execute(select(t).join(p, t.c.platform_id == p.c.id).where(
                p.c.code == platform, t.c.content_id == str(external_id))).fetchone()
            return dict(row) if row else None

    def get_current_bundle(self, content_item_id: int) -> dict | None:
        tables = {n: self.table(n) for n in ("content_item", "transcript", "ai_analysis", "content_note")}
        with self.connect() as conn:
            content = conn.execute(select(tables["content_item"]).where(tables["content_item"].c.id == content_item_id)).fetchone()
            if not content:
                return None
            bundle = {"content": dict(content)}
            bundle["content"].update(content_title=content["title"], content_status=content["status"])
            for key, name in (("transcript", "transcript"), ("analysis", "ai_analysis"), ("note", "content_note")):
                t = tables[name]
                stmt = select(t).where(t.c.content_item_id == content_item_id)
                if key == "analysis":
                    stmt = stmt.where(t.c.analysis_type == "summary")
                if key == "note":
                    stmt = stmt.where(t.c.note_type == "content")
                row = conn.execute(stmt).fetchone()
                bundle[key] = dict(row) if row else None
                if row:
                    bundle[key][f"{key}_id"] = row["id"]
                    if key in {"transcript", "analysis"}:
                        bundle[key][f"{key}_status"] = row["status"]
                    if key == "note":
                        bundle[key]["note_title"] = row["title"]
            return bundle

    def replace_transcript_analysis_and_note(self, content_item_id: int, transcript: dict | None,
                                             analysis: dict, note: dict) -> None:
        ci, tr, rev = self.table("content_item"), self.table("transcript"), self.table("transcript_revision")
        self.table("ai_analysis"), self.table("content_note")
        if transcript is not None and not str(transcript.get("text_content") or "").strip():
            raise ValueError("转录文本为空，拒绝替换")
        if analysis.get("status", "success") not in {"success", "degraded"} or not note.get("note_path"):
            raise ValueError("无效分析或笔记，保留已有结果")
        with self.connect(write=True) as conn:
            if not conn.execute(select(ci.c.id).where(ci.c.id == content_item_id)).fetchone():
                raise ValueError("内容不存在")
            if transcript is not None:
                old = conn.execute(select(tr).where(tr.c.content_item_id == content_item_id)).fetchone()
                if old:
                    conn.execute(insert(rev).values(content_item_id=content_item_id, text_content=old["text_content"],
                        record_json=json.dumps(dict(old), ensure_ascii=False)))
                values = {k: v for k, v in transcript.items() if k in tr.c and k not in {"id", "created_at"}}
                values.update(content_item_id=content_item_id, completed_at=utc_now(), updated_at=utc_now())
                values.setdefault("status", "success")
                self._upsert("transcript", values, ("content_item_id",), conn=conn)
            a = {k: v for k, v in analysis.items() if k in self.table("ai_analysis").c and k not in {"id", "created_at"}}
            a.update(content_item_id=content_item_id, analysis_type="summary", completed_at=utc_now())
            a.setdefault("status", "success")
            self._upsert("ai_analysis", a, ("content_item_id", "analysis_type"), conn=conn)
            n = {k: v for k, v in note.items() if k in self.table("content_note").c and k not in {"id", "created_at"}}
            n.update(content_item_id=content_item_id, note_type="content", rendered_at=utc_now(), updated_at=utc_now())
            self._upsert("content_note", n, ("content_item_id", "note_type"), conn=conn)
            conn.execute(update(ci).where(ci.c.id == content_item_id).values(status="completed", current_error_code="", current_error_message="", updated_at=utc_now()))

    def replace_analysis_and_note(self, content_item_id: int, analysis: dict, note: dict) -> None:
        self.replace_transcript_analysis_and_note(content_item_id, None, analysis, note)

    def enqueue_task_run(self, task_type: str, payload: dict, message: str, requested_by: str = "web", *,
                         priority: int = 50, idempotency_key: str = "", max_attempts: int = 3) -> dict:
        t = self.table("task_run")
        # Never copy credentials into a task snapshot.
        if any(word in json.dumps(payload).lower() for word in ('"api_key"', '"cookie"', '"webhook"', '"password"')):
            raise ValueError("任务 payload 不得保存秘密")
        values = encode(dict(task_type=task_type, payload_json=payload or {}, message=message,
            requested_by=requested_by, priority=priority, idempotency_key=idempotency_key or None, max_attempts=max(1, max_attempts)))
        stmt = sqlite_insert(t).values(**values).on_conflict_do_nothing(
            index_elements=[t.c.idempotency_key], index_where=t.c.idempotency_key.is_not(None)).returning(t)
        with self.connect(write=True) as conn:
            row = conn.execute(stmt).fetchone()
            if not row:
                row = conn.execute(select(t).where(t.c.idempotency_key == idempotency_key)).fetchone()
            return dict(row)

    def _transition(self, conn: Any, run_id: int, old: str, new: str, reason: str = "", actor: str = "system") -> None:
        conn.execute(insert(self.table("state_transition")).values(object_type="task_run", object_id=str(run_id),
            old_status=old, new_status=new, reason=reason, actor=actor, created_at=utc_now()))

    def claim_next_task_run(self, worker_name: str, lease_seconds: int = 300) -> dict | None:
        t, a = self.table("task_run"), self.table("task_attempt")
        self.table("state_transition")
        with self.connect(write=True) as conn:
            now = utc_now()
            expired = conn.execute(select(t).where(t.c.status == "running", t.c.lease_expires_at <= now)).fetchall()
            for row in expired:
                state = "cancelled" if row["cancel_requested_at"] else ("queued" if row["attempt"] < row["max_attempts"] else "failed")
                conn.execute(update(a).where(a.c.task_run_id == row["id"], a.c.finished_at.is_(None)).values(
                    status="abandoned", error_code="WORKER_LEASE_EXPIRED", finished_at=now))
                conn.execute(update(t).where(t.c.id == row["id"]).values(status=state, worker_name="", lease_token=None,
                    lease_expires_at=None, updated_at=now, finished_at=None if state == "queued" else now))
                self._transition(conn, row["id"], "running", state, "WORKER_LEASE_EXPIRED")
            row = conn.execute(select(t).where(t.c.status.in_(("queued", "retry_wait")), t.c.available_at <= now,
                t.c.cancel_requested_at.is_(None), t.c.pause_requested_at.is_(None)).order_by(
                t.c.priority.desc(), t.c.available_at, t.c.created_at, t.c.id).limit(1)).fetchone()
            if not row:
                return None
            token, attempt = uuid.uuid4().hex, int(row["attempt"]) + 1
            revision = ""
            if self.config:
                revision = getattr(self.config, "source_revision", "") or hashlib.sha256(self.config.path.read_bytes()).hexdigest()
            claimed = conn.execute(update(t).where(t.c.id == row["id"], t.c.status == row["status"]).values(
                status="running", worker_name=worker_name, lease_token=token, attempt=attempt,
                started_at=row["started_at"] or now, updated_at=now, heartbeat_at=now,
                lease_expires_at=utc_now(max(1, lease_seconds)), config_revision=revision).returning(t)).fetchone()
            attempt_row = conn.execute(insert(a).values(task_run_id=row["id"], attempt_no=attempt,
                worker_name=worker_name, lease_token=token, status="running", started_at=now).returning(a.c.id)).fetchone()
            self._transition(conn, row["id"], row["status"], "running", actor=worker_name)
            result = dict(claimed)
            result["attempt_id"] = attempt_row["id"]
            return result

    def heartbeat_task_run(self, task_run_id: int, lease_seconds: int = 300, progress: dict | None = None,
                           *, lease_token: str | None = None, worker_name: str | None = None) -> None:
        t = self.table("task_run")
        scope = self._lease.get()
        token = lease_token or (scope or {}).get("lease_token")
        owner = worker_name or (scope or {}).get("worker_name")
        if not token or not owner:
            raise LeaseLost("心跳必须提供当前租约 token 和 owner")
        with self.connect(write=True) as conn:
            values = dict(heartbeat_at=utc_now(), lease_expires_at=utc_now(max(1, lease_seconds)), updated_at=utc_now())
            if progress:
                values["progress_json"] = json.dumps(progress, ensure_ascii=False)
            result = conn.execute(update(t).where(t.c.id == task_run_id, t.c.status == "running",
                t.c.lease_token == token, t.c.worker_name == owner, t.c.lease_expires_at > utc_now()).values(**values))
            if result.rowcount != 1:
                raise LeaseLost("拒绝过期心跳")

    def _finish(self, run_id: int, state: str, *, stats: dict | None = None, error: str = "", delay: int = 0) -> None:
        t, a, o = self.table("task_run"), self.table("task_attempt"), self.table("outbox_event")
        self.table("state_transition")
        task = self._lease.get()
        if not task or task["id"] != run_id:
            raise LeaseLost("结果提交必须绑定领取时的租约")
        with self.connect(write=True) as conn:
            now = utc_now()
            values = dict(status=state, last_error=error or None, lease_expires_at=None, lease_token=None,
                updated_at=now, finished_at=None if state == "retry_wait" else now)
            if stats is not None:
                values["stats_json"] = json.dumps(stats, ensure_ascii=False)
                if state == "paused":
                    values["checkpoint_json"] = json.dumps(stats.get("checkpoint") or {}, ensure_ascii=False)
                    values["paused_at"] = now
            if delay:
                values["available_at"] = utc_now(delay)
            conn.execute(update(t).where(t.c.id == run_id).values(**values))
            conn.execute(update(a).where(a.c.task_run_id == run_id, a.c.attempt_no == task["attempt"],
                a.c.lease_token == task["lease_token"]).values(status=state, error_message=error or None, finished_at=now))
            self._transition(conn, run_id, "running", state, error, task["worker_name"])
            conn.execute(sqlite_insert(o).values(event_type="task_state_changed", aggregate_type="task_run", aggregate_id=str(run_id),
                idempotency_key=f"task:{run_id}:{task['attempt']}:{state}", payload_json=json.dumps({"status": state}),
                status="pending").on_conflict_do_nothing())

    def complete_task_run(self, task_run_id: int, stats: dict | None = None) -> None:
        self._finish(task_run_id, "success", stats=stats or {})

    def fail_task_run(self, task_run_id: int, error_message: str, retry_delay_seconds: int = 30, **_: Any) -> bool:
        task = self.get_task_run(task_run_id)
        retry = bool(task and task["attempt"] < task["max_attempts"] and not is_permanent_error(normalize_error_code(error_message)))
        self._finish(task_run_id, "retry_wait" if retry else "failed", error=error_message, delay=max(1, retry_delay_seconds) if retry else 0)
        return retry

    def get_task_run(self, task_run_id: int) -> dict | None:
        t = self.table("task_run")
        with self.connect() as conn:
            row = conn.execute(select(t).where(t.c.id == task_run_id)).fetchone()
            return dict(row) if row else None

    def list_task_runs(self, limit: int = 20, status: str | None = None, **_: Any) -> list[dict]:
        t = self.table("task_run")
        stmt = select(t)
        if status:
            stmt = stmt.where(t.c.status == status)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(stmt.order_by(t.c.id.desc()).limit(max(1, min(limit, 1000)))).fetchall()]

    def count_pending_task_runs(self) -> int:
        t = self.table("task_run")
        with self.connect() as conn:
            return conn.execute(select(func.count()).select_from(t).where(t.c.status.in_(("queued", "retry_wait")))).fetchone()[0]

    def start_task_attempt(self, task_run_id: int, worker_name: str) -> int:
        task = self._lease.get()
        if not task or task["id"] != task_run_id or task["worker_name"] != worker_name:
            raise LeaseLost("attempt 已在原子领取中创建；必须提供领取上下文")
        return task["attempt_id"]

    def finish_task_attempt(self, attempt_id: int, status: str, error_message: str = "", **_: Any) -> None:
        # _finish commits task + attempt + audit + outbox atomically.
        a = self.table("task_attempt")
        with self.connect() as conn:
            row = conn.execute(select(a).where(a.c.id == attempt_id)).fetchone()
            if not row or row["status"] != status or row["finished_at"] is None:
                raise LeaseLost("attempt 尚未与任务原子完成，拒绝独立修改")

    def get_latest_active_task_run(self) -> dict | None:
        t = self.table("task_run")
        with self.connect() as conn:
            row = conn.execute(select(t).where(t.c.status.in_(("running", "queued", "retry_wait"))).order_by(
                (t.c.status == "running").desc(), t.c.priority.desc(), t.c.id).limit(1)).fetchone()
            return dict(row) if row else None

    def get_latest_task_run(self) -> dict | None:
        rows = self.list_task_runs(limit=1)
        return rows[0] if rows else None

    def list_queued_task_runs(self, limit: int = 20) -> list[dict]:
        t = self.table("task_run")
        with self.connect() as conn:
            rows = conn.execute(select(t).where(t.c.status.in_(("queued", "retry_wait"))).order_by(
                t.c.priority.desc(), t.c.available_at, t.c.id).limit(limit)).fetchall()
            return [dict(r) for r in rows]

    def control_state(self, task_run_id: int) -> dict:
        task = self.get_task_run(task_run_id) or {}
        return {k: task.get(k) for k in ("status", "cancel_requested_at", "pause_requested_at", "checkpoint_json")}

    def is_task_cancel_requested(self, task_run_id: int) -> bool:
        return bool((self.get_task_run(task_run_id) or {}).get("cancel_requested_at"))

    def is_task_pause_requested(self, task_run_id: int) -> bool:
        return bool((self.get_task_run(task_run_id) or {}).get("pause_requested_at"))

    def _request_control(self, run_id: int, *, cancel: bool, reason: str = "") -> None:
        t = self.table("task_run")
        self.table("state_transition")
        with self.connect(write=True) as conn:
            row = conn.execute(select(t).where(t.c.id == run_id)).fetchone()
            if not row or row["status"] in {"success", "failed", "cancelled"}:
                return
            values = {"cancel_requested_at" if cancel else "pause_requested_at": utc_now(), "updated_at": utc_now()}
            if reason:
                values["last_error"] = reason
            state = row["status"]
            if state != "running":
                state = "cancelled" if cancel else "paused"
                values.update(status=state, finished_at=utc_now() if cancel else None)
            conn.execute(update(t).where(t.c.id == run_id).values(**values))
            self._transition(conn, run_id, row["status"], state, reason, "user")

    def request_task_cancel(self, task_run_id: int, reason: str = "") -> None:
        self._request_control(task_run_id, cancel=True, reason=reason)

    def cancel_active_task_runs(self, reason=""):
        t = self.table("task_run")
        with self.connect() as conn:
            ids = [r[0] for r in conn.execute(select(t.c.id).where(t.c.status.in_(("queued", "running", "retry_wait", "paused")))).fetchall()]
        for run_id in ids:
            self.request_task_cancel(run_id, reason)

    cancel_task_run = request_task_cancel

    cancel_task_run = request_task_cancel

    def request_task_pause(self, task_run_id: int, reason: str = "") -> None:
        self._request_control(task_run_id, cancel=False, reason=reason)

    def pause_task_run(self, task_run_id: int, checkpoint: dict | None = None, reason: str = "") -> None:
        self._finish(task_run_id, "paused", stats={"checkpoint": checkpoint or {}})
        # Checkpoint and outcome must be in the same transaction; _finish receives
        # it in stats and copies it to the checkpoint column.

    def mark_task_cancelled(self, task_run_id: int, reason: str = "") -> None:
        self._finish(task_run_id, "cancelled", error=reason)

    def resume_task_run(self, task_run_id: int) -> None:
        t = self.table("task_run")
        self.table("state_transition")
        with self.connect(write=True) as conn:
            old = conn.execute(select(t).where(t.c.id == task_run_id)).fetchone()
            if not old or old["status"] not in {"paused", "failed"}:
                raise ValueError("仅暂停/失败任务可继续")
            conn.execute(update(t).where(t.c.id == task_run_id).values(status="queued", pause_requested_at=None,
                cancel_requested_at=None, finished_at=None, lease_token=None, worker_name="", available_at=utc_now(),
                resumed_at=utc_now(), updated_at=utc_now(), max_attempts=max(old["max_attempts"], old["attempt"] + 1)))
            self._transition(conn, task_run_id, old["status"], "queued", "用户继续", "user")

    def acquire_resource_lease(self, resource_key: str, owner: str, lease_seconds: int = 900) -> bool:
        t = self.table("resource_lease")
        stmt = sqlite_insert(t).values(resource_key=resource_key, owner=owner,
            lease_expires_at=utc_now(max(1, lease_seconds)), updated_at=utc_now())
        stmt = stmt.on_conflict_do_update(index_elements=[t.c.resource_key], set_={
            "owner": stmt.excluded.owner, "lease_expires_at": stmt.excluded.lease_expires_at, "updated_at": stmt.excluded.updated_at},
            where=or_(t.c.lease_expires_at < utc_now(), t.c.owner == owner)).returning(t.c.owner)
        with self.connect(write=True) as conn:
            return conn.execute(stmt).fetchone() is not None

    def release_resource_lease(self, resource_key: str, owner: str) -> None:
        t = self.table("resource_lease")
        with self.connect(write=True) as conn:
            conn.execute(delete(t).where(t.c.resource_key == resource_key, t.c.owner == owner))

    def upsert_source_subscription(self, *, platform: str, source_type: str, source_key: str, display_name: str,
                                   preserve_existing_enabled: bool = False, **fields: Any) -> int:
        t = self.table("source_subscription")
        pid = self.ensure_platform(platform)
        fields.setdefault("enabled", True)
        if preserve_existing_enabled:
            with self.connect() as conn:
                old = conn.execute(select(t).where(t.c.platform_id == pid, t.c.source_key == source_key)).fetchone()
            if old:
                fields["enabled"] = old["enabled"]
                fields["extra"] = {**(old["extra"] or {}), **(fields.get("extra") or {})}
        return self._upsert("source_subscription", dict(platform_id=pid, source_type=source_type, source_key=source_key,
            display_name=display_name, updated_at=utc_now(), **fields), ("platform_id", "source_key"))["id"]

    def list_source_subscriptions(self, platform: str | None = None, enabled: bool | None = None) -> list[dict]:
        t, p = self.table("source_subscription"), self.table("platform")
        stmt = select(t, p.c.code.label("platform")).join(p, t.c.platform_id == p.c.id)
        if platform:
            stmt = stmt.where(p.c.code == platform)
        if enabled is not None:
            stmt = stmt.where(t.c.enabled == enabled)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(stmt.order_by(t.c.id)).fetchall()]

    def get_source_subscription(self, subscription_id: int) -> dict | None:
        t, p = self.table("source_subscription"), self.table("platform")
        with self.connect() as conn:
            row = conn.execute(select(t, p.c.code.label("platform")).join(p, p.c.id == t.c.platform_id).where(t.c.id == subscription_id)).fetchone()
            return dict(row) if row else None

    find_subscription_by_id = get_source_subscription

    def find_subscription(self, platform: str, source_key: str) -> dict | None:
        return next((r for r in self.list_source_subscriptions(platform) if r["source_key"] == source_key), None)

    def list_due_subscriptions(self, limit: int = 50) -> list[dict]:
        t, p = self.table("source_subscription"), self.table("platform")
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(select(t, p.c.code.label("platform")).join(p, p.c.id == t.c.platform_id).where(
                t.c.enabled == True, t.c.status == "active", t.c.next_check_at <= utc_now()).order_by(t.c.next_check_at, t.c.id).limit(limit)).fetchall()]

    def content_exists(self, platform: str, external_id: str) -> bool:
        return self.find_content_item(platform, external_id) is not None

    def set_source_subscription_enabled(self, subscription_id: int, enabled: bool) -> None:
        t = self.table("source_subscription")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == subscription_id).values(enabled=enabled, updated_at=utc_now()))

    def delete_source_subscription(self, subscription_id: int) -> None:
        t = self.table("source_subscription")
        with self.connect(write=True) as conn:
            conn.execute(delete(t).where(t.c.id == subscription_id))

    def update_source_subscription_category(self, subscription_id: int, category: str) -> None:
        t = self.table("source_subscription")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == subscription_id).values(category=category.strip(), updated_at=utc_now()))

    def upsert_subscription(self, *, platform, source_key, display_name, source_url, feed_url="",
                            history_capability="unknown", check_interval_minutes=60):
        old = self.find_subscription(platform, source_key)
        fields = dict(source_url=source_url or (old or {}).get("source_url"),
            feed_url=feed_url or (old or {}).get("feed_url"), history_capability="full" if feed_url else
            (old or {}).get("history_capability", history_capability))
        if not old:
            fields.update(check_interval_minutes=max(1, check_interval_minutes), next_check_at=utc_now())
        return self.upsert_source_subscription(platform=platform, source_type="podcast" if platform == "xiaoyuzhou" else "creator",
            source_key=source_key, display_name=display_name, preserve_existing_enabled=True, **fields)

    def record_subscription_scan(self, subscription_id, *, success, next_check_at, last_success_at=None, last_error=""):
        def stamp(value):
            if value is None:
                return None
            if isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if value.tzinfo is None:
                raise ValueError("订阅时间必须包含时区")
            return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        t = self.table("source_subscription")
        with self.connect(write=True) as conn:
            values = dict(last_checked_at=utc_now(), next_check_at=stamp(next_check_at),
                consecutive_failures=0 if success else t.c.consecutive_failures + 1,
                last_error="" if success else last_error, updated_at=utc_now())
            if success:
                values["last_success_at"] = stamp(last_success_at) or utc_now()
            conn.execute(update(t).where(t.c.id == subscription_id).values(**values))

    def mark_content_discovered(self, platform, external_id, subscription_id, published_at=None):
        t = self.table("content_item")
        cid = self._content_item_id(external_id, platform=platform)
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == cid).values(discovery_source="monitor",
                discovered_at=func.coalesce(t.c.discovered_at, utc_now()), updated_at=utc_now()))

    def list_content_sources_without_subscription(self, platform, limit=500):
        c, p, item = (self.table(n) for n in ("creator", "platform", "content_item"))
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(select(c.c.platform_uid, c.c.nickname, c.c.profile_url)
                .join(p, p.c.id == c.c.platform_id).where(p.c.code == platform, c.c.platform_uid != "",
                    select(item.c.id).where(item.c.creator_id == c.c.id).exists()).order_by(c.c.platform_uid).limit(limit)).fetchall()]

    def mark_content_failure(self, content_item_id: int, error_code: str, error_message: str) -> None:
        t = self.table("content_item")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == content_item_id).values(current_error_code=error_code,
                current_error_message=error_message, updated_at=utc_now()))
