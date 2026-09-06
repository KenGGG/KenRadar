from types import SimpleNamespace

import asyncio


def test_worker_retries_task_when_handler_raises_system_exit(monkeypatch):
    from kenradar.jobs import worker as worker_module
    from kenradar.jobs.worker import TaskWorker

    events = []

    class FakeDatabase:
        def is_task_cancel_requested(self, run_id):
            return False

        def is_task_pause_requested(self, run_id):
            return False

        def start_task_attempt(self, run_id, worker_name):
            return 7

        def heartbeat_task_run(self, *args, **kwargs):
            return None

        def fail_task_run(self, run_id, message):
            events.append(("failed", run_id, message))
            return True

        def finish_task_attempt(self, attempt_id, status, message="", error_code=""):
            events.append(("attempt", attempt_id, status, message))

    async def task():
        return {}

    def fail_with_system_exit(awaitable):
        awaitable.close()
        raise SystemExit(1)

    monkeypatch.setattr(worker_module, "execute_task_run", lambda *args, **kwargs: task())
    monkeypatch.setattr(worker_module.asyncio, "wait_for", lambda awaitable, timeout: awaitable)
    monkeypatch.setattr(worker_module.asyncio, "run", fail_with_system_exit)
    monkeypatch.setattr(worker_module, "Workflow", lambda config: SimpleNamespace())

    worker = object.__new__(TaskWorker)
    worker.worker_name = "test-worker"
    worker._execute(
        SimpleNamespace(get=lambda key, default=None: default),
        FakeDatabase(),
        {"id": 3, "task_type": "run_once", "payload_json": {}, "message": "scheduled"},
    )

    assert events == [
        ("failed", 3, "1"),
        ("attempt", 7, "retry_wait", "1"),
    ]


def test_execute_backfill_item_uses_one_workflow_item():
    from kenradar.jobs.handlers import execute_task_run

    calls = []

    class Workflow:
        async def execute_backfill_item(self, job_id):
            calls.append(job_id)
            return {"processed": 1}

    result = asyncio.run(execute_task_run(Workflow(), "execute_backfill_item", {"job_id": 12}))

    assert calls == [12]
    assert result["success"] == 1


def test_restart_research_job_reuses_cancelled_items(monkeypatch):
    from kenradar.core.workflow import Workflow

    events = []

    class FakeDatabase:
        def update_research_job(self, job_id, **changes):
            events.append(("job", job_id, changes))

        def cancel_research_job_items(self, job_id):
            events.append(("items", job_id))

    workflow = object.__new__(Workflow)
    workflow.database = FakeDatabase()

    async def resume(job_id, statuses, suffix):
        events.append(("resume", job_id, statuses, suffix))
        return {"job_id": 47}

    monkeypatch.setattr(workflow, "_retry_research_items", resume)

    assert asyncio.run(workflow.restart_research_job(44)) == {"job_id": 47}
    assert events[-1] == ("resume", 44, ("failed", "cancelled"), "中断续跑")


def test_retry_research_items_sends_completion_notification(monkeypatch):
    from kenradar.core.workflow import Workflow

    class Rows:
        def fetchone(self):
            return {"blogger_id": "creator-1", "blogger_name": "元姐", "platform": "douyin"}

        def fetchall(self):
            return [{"aweme_id": "123"}, {"aweme_id": "456"}]

    class Connection:
        def execute(self, *_args, **_kwargs):
            return Rows()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeDatabase:
        def connect(self):
            return Connection()

        def create_research_job(self, **_kwargs):
            return 52

        def update_research_job(self, *_args, **_kwargs):
            return None

        def upsert_research_job_item(self, *_args, **_kwargs):
            return None

        def is_aweme_fully_processed(self, aweme_id):
            return aweme_id == "123"

    pushed = []
    queued = []
    workflow = object.__new__(Workflow)
    workflow.database = FakeDatabase()
    workflow.config = SimpleNamespace(get=lambda key, default=None: True if key == "notification.research_completion_enabled" else default)
    workflow.pusher = SimpleNamespace(push_research_summary=lambda *args: pushed.append(args) or True)
    monkeypatch.setattr(workflow, "_load_aweme_for_retry", lambda aweme_id: {"aweme_id": aweme_id})
    monkeypatch.setattr(workflow, "_rebuild_aweme_dict", lambda item: item)

    async def run_pipeline(_job_id, _target, candidates, awemes, _stats):
        queued.extend(item["aweme_id"] for item in candidates)
        assert candidates == awemes
        return []

    monkeypatch.setattr(workflow, "_run_research_pipeline", run_pipeline)
    monkeypatch.setattr(workflow, "_write_research_report", lambda *_args: "report.md")
    monkeypatch.setattr(workflow, "_publish_markdown", lambda *_args: "https://example.test/report.html")
    monkeypatch.setattr(workflow, "publish_research_job", lambda _job_id: {})

    stats = asyncio.run(workflow._retry_research_items(44, ("cancelled",), "中断续跑"))

    assert stats["pushed"] is True
    assert queued == ["456"]
    assert pushed == [(52, "元姐", stats)]
