# KenRadar V2 Content Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立抖音/小宇宙统一连接器和单一当前结果的安全替换服务，并交付双平台统一单链接入口。

**Architecture:** 新通用层只认识 `external_source_id` 和 `external_content_id`；平台字段留在 connector/raw metadata。沿用现有四张内容表，不建设媒体、转录、分析或笔记版本表。

**Tech Stack:** Python、PostgreSQL、Alembic、React/TypeScript、pytest

**Spec:** `docs/superpowers/specs/2026-09-01-kenradar-v2-design.md`

## Global Constraints

- 每条内容只保留一份当前媒体、transcript、summary analysis 和 content note。
- 失败候选不得覆盖旧成功结果。
- 不重写抖音 vendor、ASR、organizer、GPU scheduler 或 Obsidian 模板。
- 不实现 B站和 YouTube。
- 新通用业务代码不得使用 `aweme_id`、`sec_uid` 命名。

---

### Task 1: 定义显式双平台连接器契约

**Files:**
- Create: `kenradar/sources/contracts.py`
- Create: `kenradar/sources/registry.py`
- Create: `tests/test_source_connectors.py`
- Modify: `kenradar/sources/base.py`

**Interfaces:**
- Produces: `SourceDescriptor`、`ContentDescriptor`、`ContentPage`、`DownloadResult`、`SourceConnector`、`connector_for_url(url)`。

- [ ] **Step 1: 写协议和显式注册测试**

```python
def test_registry_only_exposes_launch_connectors():
    assert set(CONNECTORS) == {"douyin", "xiaoyuzhou"}
    assert connector_for_url("https://www.douyin.com/video/1").platform == "douyin"
    assert connector_for_url("https://www.xiaoyuzhoufm.com/episode/1").platform == "xiaoyuzhou"
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_source_connectors.py -q`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现最小 dataclass 和 Protocol**

```python
@dataclass(frozen=True)
class ContentPage:
    items: list[ContentDescriptor]
    next_cursor: str | None = None
    has_more: bool = False
    history_capability: str = "unknown"
```

注册表使用普通字典和 URL match 顺序，不做动态发现。

- [ ] **Step 4: 运行测试**

Run: `python -m pytest tests/test_source_connectors.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/sources/contracts.py kenradar/sources/registry.py kenradar/sources/base.py tests/test_source_connectors.py
git commit -m "feat: define media source connector contract"
```

### Task 2: 包装抖音与小宇宙实现

**Files:**
- Create: `kenradar/sources/douyin/connector.py`
- Create: `kenradar/sources/douyin/__init__.py`
- Create: `kenradar/sources/xiaoyuzhou/feed_discovery.py`
- Modify: `kenradar/sources/xiaoyuzhou/adapter.py`
- Modify: `kenradar/sources/registry.py`
- Test: `tests/test_source_connectors.py`
- Test: `tests/test_xiaoyuzhou_sources.py`

**Interfaces:**
- Consumes: Task 1 contracts；现有 `SourceResolver`、`Checker`、`Downloader`、小宇宙 parser/downloader。
- Produces: `DouyinConnector`、`XiaoyuzhouConnector`。

- [ ] **Step 1: 写平台字段隔离与分页结果测试**

```python
def test_douyin_connector_maps_aweme_to_generic_descriptor(connector, raw_aweme):
    item = connector.map_content(raw_aweme)
    assert item.external_content_id == str(raw_aweme["aweme_id"])
    assert "aweme_id" in item.raw_metadata
    assert not hasattr(item, "aweme_id")

def test_xiaoyuzhou_program_without_discoverable_feed_is_limited(xyz_connector):
    source = xyz_connector.resolve_source("https://www.xiaoyuzhoufm.com/podcast/example")
    assert source.history_capability in {"full", "limited"}
    assert source.history_capability == ("full" if source.feed_url else "limited")
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_source_connectors.py tests/test_xiaoyuzhou_sources.py -q`

Expected: FAIL，包装器尚不存在。

- [ ] **Step 3: 实现薄包装器**

```python
class DouyinConnector:
    platform = "douyin"

    def resolve_content(self, url: str) -> ContentDescriptor:
        raw = self.resolver.resolve_video(url)
        return self.map_content(raw)
```

小宇宙现有 `resolve_source()` 保留为兼容方法；`feed_discovery.py` 只从公开页面元数据、HTML feed link 和已提供 URL发现 RSS。新方法返回 descriptor/page，并在无 RSS 或不可完整分页时显式标记 `history_capability=limited`。

- [ ] **Step 4: 运行双平台 parser/connector 测试**

Run: `python -m pytest tests/test_source_connectors.py tests/test_xiaoyuzhou_sources.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/sources/douyin kenradar/sources/xiaoyuzhou/adapter.py kenradar/sources/xiaoyuzhou/feed_discovery.py kenradar/sources/registry.py tests/test_source_connectors.py tests/test_xiaoyuzhou_sources.py
git commit -m "feat: adapt launch platforms to connector contract"
```

### Task 3: 迁移当前结果元数据

**Files:**
- Create: `kenradar/storage/migrations/versions/0015_current_content_result.py`
- Create: `kenradar/storage/repositories/content_current.py`
- Modify: `kenradar/storage/pg_database.py`
- Create: `tests/test_current_content_repository.py`

**Interfaces:**
- Produces: `CurrentContentRepository.get_bundle(content_item_id)`、`replace_analysis_and_note(...)`、`replace_transcript_analysis_and_note(...)`。

- [ ] **Step 1: 写唯一当前结果和新增字段测试**

```python
def test_content_has_one_current_result_bundle(repository, content_item_id):
    bundle = repository.get_bundle(content_item_id)
    assert set(bundle) == {"content", "transcript", "analysis", "note"}
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_current_content_repository.py -q`

Expected: FAIL，repository/列不存在。

- [ ] **Step 3: 编写 0015 与事务 repository**

迁移精确增加设计规格 2.1—2.5 的列，不改变现有唯一约束。repository 的替换 SQL使用一个数据库事务：

```python
def replace_analysis_and_note(self, content_item_id: int, analysis: dict, note: dict) -> None:
    with self.database.connect() as conn:
        self._upsert_analysis(conn, content_item_id, analysis)
        self._upsert_note(conn, content_item_id, note)
```

- [ ] **Step 4: 运行迁移与 repository 测试**

Run: `python -m pytest tests/test_current_content_repository.py -q`

Expected: PASS，重复替换后每种当前实体仍只有一行。

- [ ] **Step 5: 提交**

```bash
git add kenradar/storage/migrations/versions/0015_current_content_result.py kenradar/storage/repositories/content_current.py kenradar/storage/pg_database.py tests/test_current_content_repository.py
git commit -m "feat: persist one current content result"
```

### Task 4: 实现候选结果和成功后替换

**Files:**
- Create: `kenradar/core/current_result.py`
- Modify: `kenradar/core/note_writer.py`
- Modify: `kenradar/core/workflow.py`
- Create: `tests/test_current_result_service.py`

**Interfaces:**
- Produces: `CurrentResultService.reanalyze(content_item_id, profile_name, instruction)`、`retranscribe(content_item_id)`。
- Consumes: Task 3 repository、现有 transcriber/organizer/note validator/resource lease。

- [ ] **Step 1: 写三类故障保护测试**

```python
@pytest.mark.parametrize("failure", ["ai", "note", "database"])
def test_reanalysis_failure_preserves_old_bundle(service, stored_bundle, failure):
    service.fail_at = failure
    with pytest.raises(Exception):
        service.reanalyze(stored_bundle.content_id, "custom", "新的要求")
    assert service.repository.get_bundle(stored_bundle.content_id) == stored_bundle
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_current_result_service.py -q`

Expected: FAIL，服务不存在。

- [ ] **Step 3: 实现候选文件、校验和补偿**

```python
candidate = self.organizer.organize_candidate(transcript, profile_name, instruction)
self.validator.validate_analysis(candidate)
temp_note = self.note_writer.render_temp(content, transcript, candidate)
self.note_writer.validate(temp_note)
with self.resource_lease(f"content:{content_id}:current-result"):
    self.atomic_replacer.replace_with_rollback(temp_note, current_note, persist)
```

重新转录必须先生成 transcript/analysis/note 三个候选；三者全部成功才调用 bundle replace。已有成功分析时，degraded 候选不得替换。

- [ ] **Step 4: 运行服务和原笔记回归测试**

Run: `python -m pytest tests/test_current_result_service.py tests/test_config_and_publishing.py::test_write_item_summary_uses_current_video_note_section_order -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/core/current_result.py kenradar/core/note_writer.py kenradar/core/workflow.py tests/test_current_result_service.py
git commit -m "feat: replace current results only after success"
```

### Task 5: 落实当前媒体保留策略

**Files:**
- Create: `kenradar/core/media_retention.py`
- Modify: `kenradar/core/cleanup.py`
- Modify: `kenradar/jobs/handlers.py`
- Create: `tests/test_media_retention.py`

**Interfaces:**
- Produces: `MediaRetentionService.apply(content_item_id)`；task type `cleanup_media`。

- [ ] **Step 1: 写四种策略测试**

```python
@pytest.mark.parametrize("policy,should_delete", [
    ("delete_after_transcript", True),
    ("retain_forever", False),
    ("retain_days", False),
    ("retain_favorite_only", True),
])
def test_retention_policy(service, content, policy, should_delete):
    content.subscription.media_retention_policy = policy
    assert service.apply(content.id).deleted is should_delete
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_media_retention.py -q`

Expected: FAIL。

- [ ] **Step 3: 复用现有安全清理逻辑实现策略服务**

只删除已成功持久化 transcript/note 对应的当前媒体；删除后保留媒体 URL、sha256、大小和 `media_deleted_at`，不删除内容结果。

- [ ] **Step 4: 运行清理回归测试**

Run: `python -m pytest tests/test_media_retention.py tests/test_config_and_publishing.py -q`

Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add kenradar/core/media_retention.py kenradar/core/cleanup.py kenradar/jobs/handlers.py tests/test_media_retention.py
git commit -m "feat: apply per-source media retention"
```

### Task 6: 交付统一单链接 API 和 Web 入口

**Files:**
- Create: `kenradar/web/routes/process_url.py`
- Modify: `kenradar/web/router.py`
- Modify: `kenradar/jobs/handlers.py`
- Modify: `kenradar/web/frontend/src/types.ts`
- Create: `kenradar/web/frontend/src/components/ProcessUrl.tsx`
- Modify: `kenradar/web/frontend/src/AppContent.tsx`
- Modify: `kenradar/web/frontend/src/hooks/useAppState.ts`
- Test: `tests/test_api_contract.py`

**Interfaces:**
- Produces: `POST /api/content/process-url`；task types `process_url`、`reanalyze_content`、`retranscribe_content`。

- [ ] **Step 1: 写请求契约测试**

```python
def test_process_url_enqueues_manual_priority_100(monkeypatch, tmp_path):
    handler = _FakeHandler()
    queued = []
    monkeypatch.setattr(process_url, "enqueue_process_url", lambda **data: queued.append(data) or {"id": 7, "priority": 100})
    process_url._handle_process_url(handler, _ensure_test_config(tmp_path), {
        "url": "https://www.xiaoyuzhoufm.com/episode/episode-1",
        "profile_name": "standard",
        "user_instruction": "",
        "publish": False,
        "notify": False,
    })
    status, _, body = _parse_response(handler)
    assert status == 202
    assert body["task"]["priority"] == 100
```

- [ ] **Step 2: 验证测试先失败**

Run: `python -m pytest tests/test_api_contract.py -q`

Expected: FAIL，路由不存在。

- [ ] **Step 3: 实现 API、handler 和最小表单**

API 校验 URL、profile 和 instruction 长度，使用显式 connector，入队时生成 request UUID 幂等键；前端提供 URL、模板、要求、发布和通知选项，不增加版本选择 UI。

- [ ] **Step 4: 运行后端和前端验证**

Run: `python -m pytest tests/test_api_contract.py tests/test_source_connectors.py tests/test_current_result_service.py -q`

Run: `cd kenradar/web/frontend && npm run lint && npm run build`

Expected: 全部 PASS。

- [ ] **Step 5: 提交并完成 M4 真实双平台单链接验收**

```bash
git add kenradar/web/routes/process_url.py kenradar/web/router.py kenradar/jobs/handlers.py kenradar/web/frontend/src
git commit -m "feat: add unified media URL processing"
```
