# KenRadar V2 Task Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐现有 `task_run + task_attempt` 的暂停、继续、取消、崩溃收尾和错误分类，使其成为 V2 唯一生产任务底座。

**Architecture:** 只扩展现有表、repository 和 worker。研究批次仍由 `research_job` 表示；`task_run` 表示一次可 claim 的执行，不启用 `task_step` 或 `outbox_event`。

**Tech Stack:** Python 3.10+、PostgreSQL、Alembic、pytest

**Spec:** `docs/superpowers/specs/2026-09-01-kenradar-v2-design.md`

## Global Constraints

- 不新增任务表或第二个 worker 协议。
- `task_step` 和 `outbox_event` 不修改、不接入新入口。
- claim 顺序保持 `priority DESC, available_at, created_at, id`。
- 暂停和取消只在安全边界生效，不强杀 ASR 或 AI 调用。
- 公司研究和财务研究 task type 保持现状。

---

### Task 1: 固化任务底座回归基线

**Files:**
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_task_run_repository.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: 当前 `TaskRunRepository.enqueue_task_run()`、`claim_next_task_run()`。
- Produces: PostgreSQL task repository 的幂等、优先级、lease 回收测试契约。

- [ ] **Step 1: 在项目运行环境安装已有依赖并记录基线**

Run: `python -m pip install -e .`

Run: `python -m pytest -q`

Expected: 不再因缺少 `python-multipart` 失败；记录总通过数，不修改业务断言来掩盖失败。

- [ ] **Step 2: 写 repository 集成测试夹具**

```python
import os

import pytest

from kenradar.storage.pg_database import Database

@pytest.fixture
def task_db():
    url = os.environ.get("KENRADAR_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("KENRADAR_TEST_DATABASE_URL is required")
    database = Database(url)
    database.initialize()
    with database.connect() as conn:
        conn.execute("DELETE FROM task_attempt")
        conn.execute("DELETE FROM task_run")
    yield database
    database.close()
```

- [ ] **Step 3: 写当前幂等、优先级和 lease 回收测试**

```python
def test_task_run_claims_highest_priority_and_reuses_idempotency_key(task_db):
    low = task_db.enqueue_task_run("backfill", {}, "low", priority=20, idempotency_key="low")
    high = task_db.enqueue_task_run("process_url", {}, "high", priority=100, idempotency_key="high")
    duplicate = task_db.enqueue_task_run("process_url", {}, "duplicate", priority=100, idempotency_key="high")
    assert duplicate["id"] == high["id"]
    assert task_db.claim_next_task_run("test")["id"] == high["id"]
    assert low["id"] != high["id"]
```

- [ ] **Step 4: 运行基线测试**

Run: `python -m pytest tests/integration/test_task_run_repository.py tests/test_config_and_publishing.py -q`

Expected: PASS；若当前实现暴露真实缺口，将断言标记为后续任务预期失败，不改生产代码。

- [ ] **Step 5: 更新 README 的测试环境说明并提交**

在验证章节加入：

```bash
KENRADAR_TEST_DATABASE_URL=postgresql://... python -m pytest tests/integration -q
```

```bash
git add tests/integration/conftest.py tests/integration/test_task_run_repository.py README.md
git commit -m "test: lock task engine baseline"
```

### Task 2: 迁移任务控制状态

**Files:**
- Create: `kenradar/storage/migrations/versions/0014_task_run_controls.py`
- Modify: `kenradar/domain/states.py`
- Modify: `kenradar/storage/pg_database.py`
- Test: `tests/integration/test_task_run_repository.py`

**Interfaces:**
- Produces: `task_run.pause_requested_at`, `paused_at`, `resumed_at`, `error_code`, `checkpoint_json`, `parent_task_run_id`；状态 `paused`；attempt 状态 `abandoned`。

- [ ] **Step 1: 写迁移失败测试**

```python
def test_task_run_schema_supports_pause_and_checkpoint(task_db):
    with task_db.connect() as conn:
        columns = {row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='task_run'"
        ).fetchall()}
    assert {"pause_requested_at", "checkpoint_json", "error_code"} <= columns
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/integration/test_task_run_repository.py::test_task_run_schema_supports_pause_and_checkpoint -q`

Expected: FAIL，缺少新列。

- [ ] **Step 3: 编写 0014 加法迁移和状态枚举**

```python
def upgrade() -> None:
    op.execute("ALTER TABLE task_run ADD COLUMN IF NOT EXISTS pause_requested_at TIMESTAMPTZ")
    op.execute("ALTER TABLE task_run ADD COLUMN IF NOT EXISTS paused_at TIMESTAMPTZ")
    op.execute("ALTER TABLE task_run ADD COLUMN IF NOT EXISTS resumed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE task_run ADD COLUMN IF NOT EXISTS error_code VARCHAR(128)")
    op.execute("ALTER TABLE task_run ADD COLUMN IF NOT EXISTS checkpoint_json JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE task_run ADD COLUMN IF NOT EXISTS parent_task_run_id INT REFERENCES task_run(id)")
    op.execute("ALTER TABLE task_attempt ADD COLUMN IF NOT EXISTS error_code VARCHAR(128)")
```

同时重建 task/attempt 状态约束，使 `paused`、`abandoned` 合法；downgrade 只删除本迁移新增对象。

- [ ] **Step 4: 运行迁移和状态测试**

Run: `python -m kenradar --config config/config.yaml init-db`

Run: `python -m pytest tests/integration/test_task_run_repository.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/storage/migrations/versions/0014_task_run_controls.py kenradar/domain/states.py kenradar/storage/pg_database.py tests/integration/test_task_run_repository.py
git commit -m "feat: add task pause and recovery state"
```

### Task 3: 补强 repository 的控制和恢复语义

**Files:**
- Modify: `kenradar/storage/repositories/task_run.py`
- Test: `tests/integration/test_task_run_repository.py`

**Interfaces:**
- Produces: `request_task_pause(id)`、`pause_task_run(id, checkpoint)`、`resume_task_run(id)`、`control_state(id)`。
- Changes: `claim_next_task_run()` 在同一事务收尾过期 attempt。

- [ ] **Step 1: 写暂停、恢复和 abandoned attempt 测试**

```python
def test_paused_task_is_not_claimed_until_resumed(task_db):
    row = task_db.enqueue_task_run("backfill", {}, "batch")
    task_db.request_task_pause(row["id"])
    task_db.pause_task_run(row["id"], {"item_id": 42})
    assert task_db.claim_next_task_run("worker") is None
    task_db.resume_task_run(row["id"])
    claimed = task_db.claim_next_task_run("worker")
    assert claimed["id"] == row["id"]
    assert claimed["checkpoint_json"] == {"item_id": 42}
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/integration/test_task_run_repository.py -q`

Expected: FAIL，缺少控制方法或 attempt 未收尾。

- [ ] **Step 3: 实现最小 repository 方法**

```python
def resume_task_run(self, task_run_id: int) -> None:
    with self.database.connect() as conn:
        conn.execute(
            """UPDATE task_run SET status='queued', pause_requested_at=NULL,
               paused_at=NULL, resumed_at=NOW(), available_at=NOW(), updated_at=NOW()
               WHERE id=%s AND status='paused'""",
            (task_run_id,),
        )
```

同样实现请求暂停、落盘 checkpoint、读取控制状态；lease 回收时将对应 running attempt 更新为 `abandoned/WORKER_LEASE_EXPIRED`。重试延迟使用 `min(1800, 30 * 2 ** (attempt - 1))`；`AUTH_REQUIRED`、`CONTENT_PRIVATE`、`CONTENT_DELETED` 直接进入最终失败，其余已声明临时错误才进入 `retry_wait`。

- [ ] **Step 4: 运行 repository 测试**

Run: `python -m pytest tests/integration/test_task_run_repository.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/storage/repositories/task_run.py tests/integration/test_task_run_repository.py
git commit -m "feat: harden task control and lease recovery"
```

### Task 4: 接入 worker 与控制 API

**Files:**
- Modify: `kenradar/jobs/worker.py`
- Modify: `kenradar/jobs/handlers.py`
- Modify: `kenradar/web/app.py`
- Modify: `kenradar/__main__.py`
- Test: `tests/test_config_and_publishing.py`
- Test: `tests/test_api_contract.py`

**Interfaces:**
- Produces: `POST /api/task-pause?id=`、`POST /api/task-resume?id=`；CLI `task-pause`、`task-resume`。
- Consumes: Task 3 repository 控制方法。

- [ ] **Step 1: 写 worker 状态结果和 API 路由测试**

```python
def test_worker_does_not_complete_paused_result(fake_database):
    fake_database.control_state.return_value = {"pause_requested": True}
    result = {"status": "paused", "checkpoint": {"content_id": "42"}}
    assert normalize_task_result(result)["status"] == "paused"
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_config_and_publishing.py tests/test_api_contract.py -q`

Expected: FAIL，`paused` 被归一化为成功或路由不存在。

- [ ] **Step 3: 实现 worker 分支和控制入口**

```python
if stats.get("status") == "paused":
    database.pause_task_run(run_id, stats.get("checkpoint") or {})
    database.finish_task_attempt(attempt_id, "paused")
    return
```

取消结果调用 `mark_task_cancelled()`；普通异常继续使用现有重试。API/CLI 只调用 repository，不直接操作 SQL。

- [ ] **Step 4: 运行 focused 与完整验证**

Run: `python -m pytest tests/integration/test_task_run_repository.py tests/test_config_and_publishing.py tests/test_api_contract.py -q`

Run: `python -m compileall kenradar scripts`

Expected: 全部 PASS。

- [ ] **Step 5: 提交并记录 M1 验收**

```bash
git add kenradar/jobs/worker.py kenradar/jobs/handlers.py kenradar/web/app.py kenradar/__main__.py tests/test_config_and_publishing.py tests/test_api_contract.py
git commit -m "feat: expose durable task controls"
```
