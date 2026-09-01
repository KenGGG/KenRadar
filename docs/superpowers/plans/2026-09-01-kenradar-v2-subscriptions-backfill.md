# KenRadar V2 Subscriptions and Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让抖音和小宇宙来源由 PostgreSQL 定时调度，并交付先扫描、用户确认、再低优先级执行的可恢复历史处理。

**Architecture:** `source_subscription` 是来源事实源；`research_job + research_job_item` 是历史批次。历史内容按单条 task_run 小批次执行，利用现有优先队列自然让行。

**Tech Stack:** Python、PostgreSQL、Alembic、React/TypeScript、pytest

**Spec:** `docs/superpowers/specs/2026-09-01-kenradar-v2-design.md`

## Global Constraints

- 未经用户确认，历史扫描不得下载媒体。
- 定时新内容优先级 90，历史任务优先级 20。
- 历史批次默认只发送一次完成汇总。
- 小宇宙无法证明完整历史时必须标记 `limited`。
- 不使用小宇宙私有登录接口强抓完整历史。

---

### Task 1: 迁移通用历史批次字段

**Files:**
- Create: `kenradar/storage/migrations/versions/0016_generic_backfill.py`
- Create: `kenradar/storage/repositories/research_job.py`
- Modify: `kenradar/storage/pg_database.py`
- Create: `tests/test_research_job_repository.py`

**Interfaces:**
- Produces: `create_scan()`、`add_scanned_items()`、`confirm_scan()`、`next_pending_item()`、`batch_counts()`。

- [ ] **Step 1: 写扫描状态和通用 ID 测试**

```python
def test_scan_waits_for_confirmation(repository, source_id):
    job_id = repository.create_scan(source_id, "all", {})
    repository.add_scanned_items(job_id, [{"external_content_id": "ep-1", "existing": False}])
    assert repository.get(job_id)["status"] == "awaiting_confirmation"
    assert repository.batch_counts(job_id) == {"total": 1, "existing": 0, "pending": 1}
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_research_job_repository.py -q`

Expected: FAIL。

- [ ] **Step 3: 编写 0016 加法迁移和 repository**

迁移新增设计规格 2.8 的列、状态约束和索引；从 `aweme_id` 回填 `external_content_id`，不删除旧列。

- [ ] **Step 4: 运行迁移和 repository 测试**

Run: `python -m pytest tests/test_research_job_repository.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/storage/migrations/versions/0016_generic_backfill.py kenradar/storage/repositories/research_job.py kenradar/storage/pg_database.py tests/test_research_job_repository.py
git commit -m "feat: add generic scan-confirm backfill state"
```

### Task 2: 按来源调度双平台增量检查

**Files:**
- Modify: `kenradar/core/source_registry.py`
- Modify: `kenradar/scheduler/scheduler.py`
- Modify: `kenradar/jobs/handlers.py`
- Create: `kenradar/core/source_monitor.py`
- Create: `tests/test_source_monitor.py`
- Modify: `tests/test_config_and_publishing.py`

**Interfaces:**
- Produces: `SourceMonitor.due_sources(now)`、`check_source(subscription_id)`；task type `check_source`。

- [ ] **Step 1: 写 due source、去重和解析异常测试**

```python
def test_due_source_is_enqueued_once_per_schedule_window(monitor, now):
    first = monitor.enqueue_due(now)
    second = monitor.enqueue_due(now)
    assert first[0]["id"] == second[0]["id"]

def test_empty_parse_is_not_reported_as_no_update(monitor):
    with pytest.raises(SourceParseChanged):
        monitor.check_source(7)
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_source_monitor.py tests/test_config_and_publishing.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现逐来源调度**

```python
key = f"source-check:{source.id}:{scheduled_window.isoformat()}"
database.enqueue_task_run(
    "check_source", {"subscription_id": source.id},
    f"检查来源：{source.display_name}", priority=90, idempotency_key=key,
)
```

成功更新 `last_checked_at/last_success_at/next_check_at`；失败更新连续失败数和状态。新内容按通用 content ID 入库并入队处理。

- [ ] **Step 4: 运行调度回归测试**

Run: `python -m pytest tests/test_source_monitor.py tests/test_source_registry.py tests/test_config_and_publishing.py -q`

Expected: PASS。

- [ ] **Step 5: 提交并真实验证一次小宇宙自动发现**

```bash
git add kenradar/core/source_registry.py kenradar/core/source_monitor.py kenradar/scheduler/scheduler.py kenradar/jobs/handlers.py tests/test_source_monitor.py tests/test_config_and_publishing.py
git commit -m "feat: schedule database media subscriptions"
```

### Task 3: 实现只读历史扫描

**Files:**
- Create: `kenradar/core/backfill.py`
- Modify: `kenradar/jobs/handlers.py`
- Create: `kenradar/web/routes/backfill.py`
- Modify: `kenradar/web/router.py`
- Create: `tests/test_backfill_service.py`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Produces: `BackfillService.scan(source_id, scope)`；`POST /api/backfills/scan`、`GET /api/backfills/{id}`。

- [ ] **Step 1: 写“扫描不下载”和 limited 能力测试**

```python
def test_scan_only_lists_and_persists_metadata(service, connector):
    job = service.scan(3, {"type": "all"})
    assert connector.download.call_count == 0
    assert job.status == "awaiting_confirmation"

def test_limited_history_is_visible(service):
    assert service.scan(4, {"type": "all"}).history_capability == "limited"
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_backfill_service.py tests/test_api_contract.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 cursor 扫描和 API**

逐页调用 `connector.list_history()`，将 descriptor/raw metadata 写入 job items；通过当前内容完整状态计算 existing/pending，扫描完成后设置 `awaiting_confirmation`。

- [ ] **Step 4: 运行 focused tests**

Run: `python -m pytest tests/test_backfill_service.py tests/test_api_contract.py tests/test_source_connectors.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/core/backfill.py kenradar/jobs/handlers.py kenradar/web/routes/backfill.py kenradar/web/router.py tests/test_backfill_service.py tests/test_api_contract.py
git commit -m "feat: scan history before backfill execution"
```

### Task 4: 实现确认、分块执行和恢复

**Files:**
- Modify: `kenradar/core/backfill.py`
- Modify: `kenradar/jobs/handlers.py`
- Modify: `kenradar/web/routes/backfill.py`
- Modify: `tests/test_backfill_service.py`
- Modify: `tests/integration/test_task_run_repository.py`

**Interfaces:**
- Produces: `confirm(job_id, selected_ids)`、`execute_next(job_id)`；task type `execute_backfill_item`。

- [ ] **Step 1: 写确认、优先级和恢复测试**

```python
def test_confirm_enqueues_one_low_priority_item(service, job_id):
    task = service.confirm(job_id, ["ep-1", "ep-2"])
    assert task["priority"] == 20
    service.execute_next(job_id)
    assert service.repository.batch_counts(job_id)["pending"] == 1
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_backfill_service.py tests/integration/test_task_run_repository.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现单条小批次 continuation**

每次任务 claim 一个 pending item，处理成功后原子更新 item/count，并按 `backfill:{job_id}:{next_item_id}` 入队下一个优先级 20 任务。暂停/取消时不入队 continuation；继续时根据 pending item 恢复。

- [ ] **Step 4: 运行崩溃、暂停、取消和优先级测试**

Run: `python -m pytest tests/test_backfill_service.py tests/integration/test_task_run_repository.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/core/backfill.py kenradar/jobs/handlers.py kenradar/web/routes/backfill.py tests/test_backfill_service.py tests/integration/test_task_run_repository.py
git commit -m "feat: execute recoverable low-priority backfills"
```

### Task 5: 交付来源策略和批次确认 UI

**Files:**
- Modify: `kenradar/web/frontend/src/types.ts`
- Modify: `kenradar/web/frontend/src/components/SourceManager.tsx`
- Modify: `kenradar/web/frontend/src/components/ResearchWorkspace.tsx`
- Modify: `kenradar/web/frontend/src/hooks/useAppState.ts`
- Modify: `kenradar/web/frontend/src/components/RunCenterModel.test.ts`

**Interfaces:**
- Consumes: Tasks 2—4 API。
- Produces: 来源策略编辑、历史扫描结果、确认、暂停、继续、取消 UI。

- [ ] **Step 1: 写前端状态模型测试**

```typescript
it('does not expose execute before scan confirmation', () => {
  expect(backfillActions({ status: 'scanning' })).not.toContain('execute')
  expect(backfillActions({ status: 'awaiting_confirmation' })).toContain('confirm')
})
```

- [ ] **Step 2: 验证测试先失败**

Run: `cd kenradar/web/frontend && npx tsx src/components/RunCenterModel.test.ts`

Expected: FAIL。

- [ ] **Step 3: 实现最小 UI**

来源卡片增加策略和历史扫描按钮；批次页显示 total/existing/pending/history capability，只有 `awaiting_confirmation` 显示确认执行。

- [ ] **Step 4: 运行前端和后端验证**

Run: `cd kenradar/web/frontend && npm run lint && npm run build`

Run: `python -m pytest tests/test_backfill_service.py tests/test_api_contract.py -q`

Expected: 全部 PASS。

- [ ] **Step 5: 提交并完成 M6 真实恢复验收**

```bash
git add kenradar/web/frontend/src
git commit -m "feat: add scan-confirm backfill workspace"
```
