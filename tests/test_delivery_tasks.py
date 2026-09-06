from __future__ import annotations

from pathlib import Path

import pytest


def test_publication_failure_never_calls_content_pipeline(tmp_path: Path) -> None:
    from kenradar.publishing.service import PublicationService

    events: list[str] = []

    class Publications:
        def find_success(self, *_args):
            return None

        def start(self, *_args):
            return {"id": 7}

        def fail(self, *_args):
            events.append("failed")

    class Database:
        publications = Publications()

        def get_current_bundle(self, _content_id):
            return {"content": {"content_title": "测试"}, "note": {"note_path": str(tmp_path / "note.md"), "content_sha256": "hash"}}

    class Publisher:
        def publish_markdown(self, *_args):
            events.append("render")
            raise RuntimeError("publish failed")

    service = PublicationService(Database(), Publisher(), sync=lambda: events.append("sync"))
    with pytest.raises(RuntimeError, match="publish failed"):
        service.publish_content(12)

    assert events == ["render", "failed"]


def test_publish_task_calls_only_publication_service() -> None:
    import asyncio

    from kenradar.jobs.handlers import execute_task_run

    calls: list[int] = []

    class Workflow:
        publication_service = type("Service", (), {"publish_content": lambda _self, content_id: calls.append(content_id) or {"processed": 1}})()

    result = asyncio.run(execute_task_run(Workflow(), "publish_content", {"content_item_id": 12}))

    assert calls == [12]
    assert result["success"] == 1


def test_batch_delivery_handlers_only_call_delivery_services() -> None:
    import asyncio

    from kenradar.jobs.handlers import execute_task_run

    calls: list[tuple[str, int]] = []

    class Workflow:
        publication_service = type("Service", (), {"publish_batch": lambda _self, job_id: calls.append(("publish", job_id)) or {}})()
        notification_service = type("Service", (), {"notify_batch": lambda _self, job_id: calls.append(("notify", job_id)) or {}})()

    asyncio.run(execute_task_run(Workflow(), "publish_batch", {"research_job_id": 7}))
    asyncio.run(execute_task_run(Workflow(), "notify_batch", {"research_job_id": 7}))

    assert calls == [("publish", 7), ("notify", 7)]


def test_notification_failure_never_calls_content_pipeline() -> None:
    from kenradar.notification.service import NotificationService

    events: list[str] = []

    class Publications:
        def find_notification_success(self, *_args):
            return None

        def start_notification(self, *_args):
            return {"id": 9}

        def fail_notification(self, *_args):
            events.append("failed")

    class Database:
        publications = Publications()

        def get_current_bundle(self, _content_id):
            return {
                "content": {"content_id": "episode-1", "content_title": "测试节目"},
                "analysis": {"result_hash": "analysis-hash", "result_text": "摘要", "analysis_status": "success"},
                "note": {"note_path": "note.md"},
            }

    class Pusher:
        def push(self, _items):
            events.append("push")
            raise RuntimeError("notify failed")

    service = NotificationService(Database(), Pusher())
    with pytest.raises(RuntimeError, match="notify failed"):
        service.notify_content(12)

    assert events == ["push", "failed"]


def test_notification_audit_records_public_note_url(tmp_path: Path) -> None:
    from kenradar.notification.service import NotificationService

    completed: list[str] = []

    class Publications:
        def find_notification_success(self, *_args): return None
        def start_notification(self, *_args): return {"id": 9}
        def complete_notification(self, _id, target_url): completed.append(target_url)

    class Database:
        publications = Publications()
        def get_current_bundle(self, _content_id):
            return {"content": {"content_id": "episode-1"}, "analysis": {"result_hash": "hash"}, "note": {"note_path": str(tmp_path / "note.md")}}

    class Pusher:
        publisher = type("Publisher", (), {"public_url_for": lambda _self, path: f"https://pages.example/{path.name}"})()
        def push(self, _items): return True

    NotificationService(Database(), Pusher()).notify_content(12)
    assert completed == ["https://pages.example/note.md"]
