"""Local audit and artifact records. No external delivery side effects."""
import json
from pathlib import Path
from sqlalchemy import insert, select, update


def utc_now(seconds=0):
    from .sqlite_database import utc_now as clock
    return clock(seconds)


class AuditMethods:
    def insert_push_log(self, aweme_id, batch_id, status, error_message=None, message_type=None):
        t = self.table("push_log")
        cid = self._content_item_id(aweme_id, required=False) if aweme_id else None
        with self.connect(write=True) as conn:
            conn.execute(insert(t).values(content_item_id=cid, aweme_id=aweme_id, batch_id=batch_id,
                channel="feishu", status=status, error_message=error_message, message_type=message_type or "card"))

    def insert_alert_log(self, level, component, message, aweme_id=None, title=None, context=None,
                         notified=False, aggregation_window_minutes=60):
        from kenradar.notification.alert import alert_fingerprint
        t = self.table("alert_log")
        fingerprint = alert_fingerprint(level, component, message)
        cid = self._content_item_id(aweme_id, required=False) if aweme_id else None
        if isinstance(context, str):
            context = json.loads(context) if context else {}
        with self.connect(write=True) as conn:
            old = conn.execute(select(t).where(t.c.fingerprint == fingerprint, t.c.resolved_at.is_(None))).fetchone()
            values = dict(level=level, component=component, message=message, content_item_id=cid,
                aweme_id=aweme_id, title=title, context=json.dumps(context or {}, ensure_ascii=False), last_seen_at=utc_now())
            expired = not old or (old["aggregation_window_started_at"] or "") <= utc_now(-max(1, aggregation_window_minutes) * 60)
            if old:
                values["occurrence_count"] = old["occurrence_count"] + 1
                if expired:
                    values.update(aggregation_window_started_at=utc_now(), notified=False)
                row = conn.execute(update(t).where(t.c.id == old["id"]).values(**values).returning(t)).fetchone()
            else:
                row = conn.execute(insert(t).values(**values, fingerprint=fingerprint, notified=notified,
                    first_seen_at=utc_now(), aggregation_window_started_at=utc_now()).returning(t)).fetchone()
            return {**dict(row), "should_notify": expired}

    def mark_alert_notified(self, alert_id, notified):
        t = self.table("alert_log")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == alert_id).values(notified=notified,
                last_notified_at=utc_now() if notified else None))

    def resolve_alert_fingerprint(self, component, message):
        t = self.table("alert_log")
        with self.connect(write=True) as conn:
            rows = conn.execute(update(t).where(t.c.component == component, t.c.message == message,
                t.c.resolved_at.is_(None)).values(resolved_at=utc_now()).returning(t)).fetchall()
            return dict(rows[0]) if rows else None

    def list_recent_alerts(self, limit=50):
        t = self.table("alert_log")
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(select(t).order_by(t.c.created_at.desc(), t.c.id.desc()).limit(limit)).fetchall()]

    def insert_state_transition(self, object_type, object_id, old_status, new_status, reason=None, actor=None):
        t = self.table("state_transition")
        with self.connect(write=True) as conn:
            conn.execute(insert(t).values(object_type=object_type, object_id=str(object_id), old_status=old_status,
                new_status=new_status, reason=reason, actor=actor))

    def register_artifact(self, content_item_id, task_run_id, kind, path, size_bytes=None, sha256=None):
        return self._upsert("artifact", dict(content_item_id=content_item_id, task_run_id=task_run_id,
            kind=kind, path=path, size_bytes=size_bytes, sha256=sha256, status="active", updated_at=utc_now()), ("kind", "path"))["id"]

    def list_artifacts(self, kind=None, status="active"):
        t = self.table("artifact")
        stmt = select(t).where(t.c.status == status).order_by(t.c.created_at.desc())
        if kind:
            stmt = stmt.where(t.c.kind == kind)
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(stmt).fetchall()]

    def deactivate_artifact(self, artifact_id):
        t = self.table("artifact")
        with self.connect(write=True) as conn:
            conn.execute(update(t).where(t.c.id == artifact_id).values(status="deleted", updated_at=utc_now()))

    def cleanup_artifacts(self):
        if self.config is None:
            raise RuntimeError("清理必须明确配置数据根目录")
        root = self.config.data_dir.resolve()
        cleaned = errors = 0
        artifacts = self.list_artifacts(status="deleted")
        for artifact in artifacts:
            path = Path(artifact["path"])
            if not path.is_absolute():
                path = root / path
            path = path.resolve()
            if not path.is_relative_to(root) or path == root:
                errors += 1
                continue
            try:
                if path.is_file():
                    path.unlink()
                    cleaned += 1
            except OSError:
                errors += 1
        return {"cleaned": cleaned, "errors": errors, "total": len(artifacts)}

    def get_task_step(self, step_id):
        t = self.table("task_step")
        with self.connect() as conn:
            row = conn.execute(select(t).where(t.c.id == step_id)).fetchone()
            return dict(row) if row else None

    def list_task_steps(self, task_run_id):
        t = self.table("task_step")
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(select(t).where(t.c.task_run_id == task_run_id).order_by(t.c.id)).fetchall()]
