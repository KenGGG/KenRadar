# KenRadar V2 Publishing and Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 GitHub 和飞书变成独立幂等任务，收敛 WebUI 到 V2 入口，并通过真实双跑安全切换。

**Architecture:** 内容事务直接向同一 `task_run` 表写后续任务；`publication_log` 与补强后的 `push_log` 保存操作历史。Web 继续使用 React/Vite 和现有后端，不引入新服务。

**Tech Stack:** Python、PostgreSQL、Alembic、React/TypeScript、pytest

**Spec:** `docs/superpowers/specs/2026-09-01-kenradar-v2-design.md`

## Global Constraints

- 发布或通知失败不得调用下载、ASR、AI。
- 同一 source hash 不产生空 Git commit。
- 同一通知幂等键不得重复发送。
- 人工审核默认关闭。
- 不重新设计 Obsidian 笔记格式，不删除旧路由和兼容视图。

---

### Task 1: 迁移发布与通知审计

**Files:**
- Create: `kenradar/storage/migrations/versions/0017_publication_notification_logs.py`
- Create: `kenradar/storage/repositories/publication.py`
- Modify: `kenradar/storage/pg_database.py`
- Create: `tests/test_publication_repository.py`

**Interfaces:**
- Produces: `PublicationRepository.start/complete/fail/find_success()`；push log 幂等写入。

- [ ] **Step 1: 写发布和通知幂等测试**

```python
def test_publication_idempotency_is_scoped_by_source_hash(repository, content_id):
    first = repository.start(content_id, "hash-a", "publish:1:hash-a")
    duplicate = repository.start(content_id, "hash-a", "publish:1:hash-a")
    changed = repository.start(content_id, "hash-b", "publish:1:hash-b")
    assert first.id == duplicate.id
    assert changed.id != first.id
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_publication_repository.py -q`

Expected: FAIL。

- [ ] **Step 3: 编写 0017 和 repository**

创建设计规格 2.6 的 `publication_log`；给 `push_log` 增加 `idempotency_key/research_job_id/target_url/attempt_count` 和部分唯一索引。历史记录不回填虚假幂等键。

- [ ] **Step 4: 运行迁移测试**

Run: `python -m pytest tests/test_publication_repository.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/storage/migrations/versions/0017_publication_notification_logs.py kenradar/storage/repositories/publication.py kenradar/storage/pg_database.py tests/test_publication_repository.py
git commit -m "feat: persist idempotent publication attempts"
```

### Task 2: 拆出独立发布和通知任务

**Files:**
- Create: `kenradar/publishing/service.py`
- Create: `kenradar/notification/service.py`
- Modify: `kenradar/jobs/handlers.py`
- Modify: `kenradar/core/current_result.py`
- Modify: `kenradar/core/backfill.py`
- Create: `tests/test_delivery_tasks.py`

**Interfaces:**
- Produces: task types `publish_content`、`publish_batch`、`notify_content`、`notify_batch`。
- Consumes: `content_item_id` 或 `research_job_id`，不消费媒体路径或 transcript text。

- [ ] **Step 1: 写失败隔离测试**

```python
def test_github_retry_never_calls_content_pipeline(delivery, pipeline):
    delivery.github.side_effect = RuntimeError("push failed")
    with pytest.raises(RuntimeError):
        delivery.publish_content(12)
    pipeline.download.assert_not_called()
    pipeline.transcribe.assert_not_called()
    pipeline.analyze.assert_not_called()

def test_review_is_only_required_when_source_policy_enables_it(delivery, content):
    content.review_status = "pending"
    content.source.review_required = True
    assert delivery.publish_content(content.id)["status"] == "blocked_review"
    content.source.review_required = False
    assert delivery.publish_content(content.id)["status"] != "blocked_review"
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_delivery_tasks.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现小型 delivery services 和 handler**

```python
if task_type == "publish_content":
    return workflow.publication_service.publish_content(int(payload["content_item_id"]))
if task_type == "notify_content":
    return workflow.notification_service.notify_content(int(payload["content_item_id"]))
```

当前结果持久化与后续 task_run 插入使用同一 PostgreSQL 事务。需要发布后通知时，只由发布成功分支入队通知。

- [ ] **Step 4: 运行发布、飞书和内容隔离测试**

Run: `python -m pytest tests/test_delivery_tasks.py tests/test_config_and_publishing.py tests/test_curation_policy.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/publishing/service.py kenradar/notification/service.py kenradar/jobs/handlers.py kenradar/core/current_result.py kenradar/core/backfill.py tests/test_delivery_tasks.py
git commit -m "feat: isolate publishing and notification tasks"
```

### Task 3: 收敛通用内容和操作历史 API

**Files:**
- Create: `kenradar/web/routes/content_detail.py`
- Create: `kenradar/web/routes/delivery.py`
- Modify: `kenradar/web/routes/content.py`
- Modify: `kenradar/web/router.py`
- Modify: `kenradar/web/queries.py`
- Modify: `tests/test_api_contract.py`

**Interfaces:**
- Produces: `GET /api/content/{id}`、`GET /api/content/{id}/operations`、`POST /api/content/{id}/publish`、`POST /api/content/{id}/notify`。

- [ ] **Step 1: 写通用详情契约测试**

```python
def test_content_detail_uses_generic_identity_and_current_result(monkeypatch):
    handler = _FakeHandler()
    monkeypatch.setattr(content_detail, "load_content_detail", lambda _config, _id: {
        "content": {"external_content_id": "episode-1"},
        "current_result": {"transcript": {}, "analysis": {}, "note": {}},
    })
    content_detail._handle_content_detail(handler, CONFIG_PATH, 12)
    _, _, payload = _parse_response(handler)
    assert payload["content"]["external_content_id"]
    assert set(payload["current_result"]) == {"transcript", "analysis", "note"}
    assert "versions" not in payload
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_api_contract.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现查询和重试入口**

operation history 合并读取 `publication_log`、`push_log`、关联 `task_run/task_attempt`；重新发布/通知只入队优先级 60 任务。

- [ ] **Step 4: 运行 API 和真实 PostgreSQL 查询测试**

Run: `python -m pytest tests/test_api_contract.py tests/test_content_filters.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/web/routes/content_detail.py kenradar/web/routes/delivery.py kenradar/web/routes/content.py kenradar/web/router.py kenradar/web/queries.py tests/test_api_contract.py
git commit -m "feat: expose generic content operations"
```

### Task 4: 收敛六入口 WebUI

**Files:**
- Modify: `kenradar/web/frontend/src/components/Navigation.tsx`
- Modify: `kenradar/web/frontend/src/AppContent.tsx`
- Modify: `kenradar/web/frontend/src/components/DetailView.tsx`
- Modify: `kenradar/web/frontend/src/components/RunCenter.tsx`
- Modify: `kenradar/web/frontend/src/components/ArchiveWorkspace.tsx`
- Modify: `kenradar/web/frontend/src/types.ts`
- Modify: `kenradar/web/frontend/src/hooks/useAppState.ts`
- Modify: `kenradar/web/frontend/src/components/RunCenterModel.test.ts`

**Interfaces:**
- Consumes: 统一内容、来源、批次和 delivery API。
- Produces: 今日雷达、订阅来源、处理链接、内容库、批次任务、系统与监控六入口。

- [ ] **Step 1: 写导航和当前结果模型测试**

```typescript
it('shows the six V2 workspaces without version controls', () => {
  expect(V2_NAV.map(item => item.key)).toEqual([
    'radar', 'sources', 'process-url', 'library', 'batches', 'system'
  ])
  expect(contentActions).not.toContain('compare-versions')
})
```

- [ ] **Step 2: 验证测试先失败**

Run: `cd kenradar/web/frontend && npx tsx src/components/RunCenterModel.test.ts`

Expected: FAIL。

- [ ] **Step 3: 调整信息架构而不重做视觉系统**

复用现有卡片、表格、tokens 和页面组件；详情只显示当前结果和操作历史；兼容 `/aweme` 路由重定向到通用详情。

- [ ] **Step 4: 运行前端验证**

Run: `cd kenradar/web/frontend && npx tsx src/components/RunCenterModel.test.ts && npm run lint && npm run build`

Expected: 全部 PASS，构建不新增大型依赖。

- [ ] **Step 5: 提交**

```bash
git add kenradar/web/frontend/src
git commit -m "feat: converge Web UI on V2 workflows"
```

### Task 5: 双跑、非回归与切换

**Files:**
- Create: `scripts/verify_v2_media_radar.py`
- Create: `docs/superpowers/reports/2026-09-01-kenradar-v2-verification.md`
- Modify: `README.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Produces: 只读对账命令和真实验收记录；不产生第二套生产写入。

- [ ] **Step 1: 写只读校验脚本测试**

```python
def test_verifier_reports_identity_and_result_mismatches(snapshot):
    report = compare_snapshot(snapshot)
    assert set(report) >= {"source_mismatches", "content_mismatches", "result_mismatches"}
```

- [ ] **Step 2: 实现只读对账脚本**

脚本比较来源数、发现内容 ID、转录状态、分析状态、笔记路径、发布和通知；默认不写数据库、不下载媒体、不发送通知。

- [ ] **Step 3: 运行完整自动验证**

Run: `python -m compileall kenradar scripts`

Run: `python -m pytest -q`

Run: `cd kenradar/web/frontend && npm run lint && npm run build`

Expected: 全部 PASS。

- [ ] **Step 4: 运行真实双平台验收并填写报告**

Run: `python scripts/verify_v2_media_radar.py --config config/config.yaml`

Run: `./ctl.sh restart && ./ctl.sh status`

验证设计规格第 10 节全部条目；明确记录小宇宙 `full/limited` 能力，不用 mock 结论代替真实结果。

- [ ] **Step 5: 更新运行文档并提交**

```bash
git add scripts/verify_v2_media_radar.py docs/superpowers/reports/2026-09-01-kenradar-v2-verification.md README.md AGENTS.md
git commit -m "docs: verify and adopt KenRadar V2 media radar"
```
