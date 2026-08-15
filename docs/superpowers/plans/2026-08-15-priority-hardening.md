# KenRadar Priority Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 加固 KenRadar 的 Web 安全和迁移门禁，统一来源与策展口径，收敛任务语义，缩小首屏负载，并提供准确、可聚合的运行健康信号。

**Architecture:** 保留已验证的 `task_run + research_job` 生产链路，在其外围增加独立的 schema guard、source registry、curation policy、dependency health 和 alert aggregation 单元。Web bootstrap 改为轻量概要，内容和归档数据使用既有分页/独立接口加载；历史 schema 和响应字段继续兼容。

**Tech Stack:** Python 3.10+、Pydantic、psycopg/PostgreSQL、Alembic、`http.server`、React 19、TypeScript、Vite、pytest。

**Spec:** `docs/superpowers/specs/2026-08-15-priority-hardening-design.md`

## Global Constraints

- 不破坏抖音、小宇宙、Obsidian、GitHub Pages、飞书和持久任务生产链路。
- PostgreSQL 是运行状态和来源订阅事实源；YAML 只作兼容导入/导出。
- 保留 `task_step`、`outbox_event`、`artifact` 历史表，不扩成第二套生产编排。
- 不改变 Obsidian frontmatter、四个固定章节或转录保存规则。
- 不删除 `docs/`、`data/notes/`、`data/briefs/` 或用户运行数据。
- 当前工作区已有用户改动；不得覆盖或回退，提交时只包含能够明确归属本计划的文件或补丁块。

---

### Task 1: Web 安全、schema guard 和动态版本

**Files:**
- Create: `kenradar/storage/schema_guard.py`
- Modify: `ctl.sh`
- Modify: `kenradar/__main__.py`
- Modify: `kenradar/jobs/worker.py`
- Modify: `kenradar/web/app.py`
- Modify: `kenradar/web/routes/health.py`
- Test: `tests/test_config_and_publishing.py`
- Test: `tests/test_api_contract.py`

**Interfaces:**
- Produces: `require_schema_current(config_path: str) -> dict[str, str | bool]`
- Produces: `runtime_version(config_path: str) -> dict[str, Any]`
- Preserves: `run_web(config_path, host, port)` and CLI command names.

- [ ] Add failing tests proving non-loopback/no-password raises, loopback succeeds, env password succeeds, stale schema raises, and version data is dynamic.
- [ ] Run focused tests and confirm failures identify the empty binding guard and missing schema guard.
- [ ] Implement `schema_guard.py` by delegating to `storage.migrate.schema_status`; error text must include current/head and the migrate command.
- [ ] Change `ctl.sh` default `HOST` to `127.0.0.1`, enforce `_validate_web_binding_security()` through `config.web_password`, and call `require_schema_current()` from Web and worker startup.
- [ ] Replace hard-coded version response with `runtime_version()` using package metadata, `platform.python_version()` and Alembic status.
- [ ] Run focused tests, `python -m compileall -q kenradar scripts`, and `git diff --check`.

### Task 2: Unified Curation Policy

**Files:**
- Create: `kenradar/core/curation.py`
- Modify: `kenradar/core/analytics.py`
- Modify: `kenradar/notification/feishu.py`
- Modify: `kenradar/web/queries.py`
- Modify: `kenradar/web/helpers.py`
- Modify: `kenradar/web/frontend/src/types.ts`
- Modify: `kenradar/web/frontend/src/components/ArchiveWorkspace.tsx`
- Test: `tests/test_config_and_publishing.py`
- Test: `tests/test_content_filters.py`

**Interfaces:**
- Produces: `CurationPolicy.from_config(config: AppConfig) -> CurationPolicy`
- Produces: `is_high_value(score)`, `should_push(action, score)`, `should_recommend(action, score)`, `should_research(action, score)`.
- Produces API values `high_value_threshold`, `push_threshold`, `research_threshold` on the 10-point frontend scale.

- [ ] Add failing tests for default thresholds, configured `push_threshold_rating`, failed summaries, empty qualifying set, and SQL threshold construction.
- [ ] Implement immutable `CurationPolicy` with 5-point internal values and explicit 10-point conversion.
- [ ] Replace hard-coded 3.5/4.0/4.2 policy decisions in analytics, Feishu and Web queries.
- [ ] Ensure Feishu archives every item when none qualifies; failed/degraded analyses never become push candidates.
- [ ] Pass policy thresholds to the frontend and remove the 8.5 smart-view constant.
- [ ] Run Python focused tests plus frontend lint/tests.

### Task 3: Source Registry as Runtime Fact Source

**Files:**
- Create: `kenradar/core/source_registry.py`
- Modify: `kenradar/core/checker.py`
- Modify: `kenradar/core/workflow.py`
- Modify: `kenradar/web/helpers.py`
- Modify: `kenradar/web/app.py`
- Modify: `kenradar/storage/pg_database.py`
- Test: `tests/test_config_and_publishing.py`
- Test: `tests/test_source_insights.py`

**Interfaces:**
- Produces: `SourceRegistry(config, database)`.
- Produces: `import_config_sources() -> dict[str, int]`, `list_monitor_targets() -> list[BloggerTarget]`, `diagnostics() -> dict[str, int]`.
- Preserves YAML save on Web edits for compatibility, while runtime reads PostgreSQL subscriptions.

- [ ] Add failing tests for idempotent import, preservation of DB-disabled state, DB-first target loading, empty-DB fallback and diagnostics.
- [ ] Implement import using creator/source_subscription upserts without re-enabling an existing disabled subscription.
- [ ] Change Checker to use SourceRegistry; fall back to YAML only when no Douyin subscriptions exist.
- [ ] Route source add/toggle/delete/category operations through DB first, then mirror YAML.
- [ ] Add non-sensitive source consistency counts to doctor/status.
- [ ] Run focused tests and query the real database to prove config 21 vs DB state reconciles without losing disabled subscriptions.

### Task 4: Task Runtime Consolidation and Partial Failure

**Files:**
- Modify: `kenradar/__main__.py`
- Modify: `kenradar/jobs/worker.py`
- Modify: `kenradar/jobs/handlers.py`
- Modify: `kenradar/core/workflow.py`
- Test: `tests/test_config_and_publishing.py`
- Test: `tests/test_api_contract.py`

**Interfaces:**
- Produces: `normalize_task_result(stats: Mapping[str, Any]) -> dict[str, Any]`.
- Changes `_task_result_error()` to reject explicit task-level failure only.
- Removes `step-worker` from public CLI while retaining historical modules/tables.

- [ ] Add failing tests for explicit failure, complete success, partial failure, all-item failure and CLI absence.
- [ ] Implement normalized statuses `success`, `partial_failed`, `failed`, `cancelled` with legacy counters retained.
- [ ] Update TaskWorker to complete partial batches and retry only task-level/all-item failure.
- [ ] Normalize run-once, research and retry-batch result dictionaries at handler boundary.
- [ ] Remove public `step-worker` command and document the compatibility-only runtime modules in code comments.
- [ ] Run worker/handler tests and verify historical task rows remain readable.

### Task 5: Lightweight Bootstrap and Lazy Archive Data

**Files:**
- Modify: `kenradar/web/helpers.py`
- Modify: `kenradar/web/routes/dashboard.py`
- Modify: `kenradar/web/router.py`
- Modify: `kenradar/web/frontend/src/hooks/useAppState.ts`
- Modify: `kenradar/web/frontend/src/AppContent.tsx`
- Modify: `kenradar/web/frontend/src/components/ArchiveWorkspace.tsx`
- Test: `tests/test_api_contract.py`
- Test: `kenradar/web/frontend/src/hooks/SSEPollingModel.test.ts`

**Interfaces:**
- Bootstrap returns at most 30 recent video summaries and no note/brief bodies or bulk logs.
- Produces `GET /api/archive/files?kind=notes|briefs` and reuses `/api/content-items` for content pages.
- Preserves old bootstrap keys as empty arrays for one compatibility cycle.

- [ ] Add failing API contract tests enforcing item limit, absence of large Markdown bodies and archive endpoint validation.
- [ ] Reduce bootstrap queries and payload while preserving navigation/system/config/task fields.
- [ ] Add archive file endpoint with strict enum validation and metadata-only rows.
- [ ] Add frontend lazy loaders for archive content/files; details continue to use detail endpoint.
- [ ] Run API tests, TypeScript lint/build and measure bootstrap under 500KB and one second on the real service.

### Task 6: Accurate Dependency Health

**Files:**
- Create: `kenradar/web/dependency_health.py`
- Modify: `kenradar/web/routes/health.py`
- Modify: `kenradar/web/helpers.py`
- Test: `tests/test_api_contract.py`
- Test: `tests/test_funasr_lifecycle.py`

**Interfaces:**
- Produces: `dependency_status(config, *, urlopen, process_runner) -> dict[str, Any]` with injectable probes.
- Produces named statuses for postgres/schema, Agnes, FunASR, Ollama, GPU, Feishu and GitHub publishing.

- [ ] Add failing tests for Agnes first + Ollama second provider, idle FunASR, unavailable fallback, disabled optional dependency and stale schema readiness.
- [ ] Implement side-effect-free provider discovery and bounded probes; do not start FunASR or send notifications.
- [ ] Make readiness fail on DB/schema/task table only; optional dependency failures set degraded.
- [ ] Return structured details plus backwards-compatible top-level status strings.
- [ ] Run focused health tests and curl live endpoints.

### Task 7: Alert Aggregation and Recovery

**Files:**
- Create: `kenradar/storage/migrations/versions/0013_alert_aggregation.py`
- Modify: `kenradar/storage/pg_database.py`
- Modify: `kenradar/notification/alert.py`
- Modify: `kenradar/web/queries.py`
- Test: `tests/test_config_and_publishing.py`
- Test: `tests/test_dashboard_consistency.py`

**Interfaces:**
- Produces: `alert_fingerprint(level, component, message) -> str`.
- Changes `insert_alert_log(...) -> dict[str, Any]` to upsert active fingerprint windows and return `should_notify`.
- Produces `resolve_alert_fingerprint(component, message) -> dict[str, Any] | None`.

- [ ] Add failing tests for stable normalization, duplicate window aggregation, window expiry notification, and one-time recovery.
- [ ] Add nullable aggregation columns and partial active-fingerprint index in migration 0013.
- [ ] Implement DB upsert/resolution with row locking and occurrence counts.
- [ ] Change AlertManager to persist first, send only when `should_notify`, and mark notification result without recursive alerting.
- [ ] Update health/dashboard counts to count active fingerprints while exposing total occurrences.
- [ ] Run migration tests and focused alert/dashboard tests.

### Task 8: Dependency Reproducibility, Cleanup and End-to-End Verification

**Files:**
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Modify: `scripts/start_funasr_server.sh`
- Modify: `tests/test_experimental_features_retired.py` only if the assertion should ignore cache-only directories; prefer removing stale cache from the workspace without committing it.
- Modify: `docs/superpowers/reports/2026-08-15-priority-hardening-verification.md`

**Interfaces:**
- Declares Web/ASR runtime dependencies used by shipped scripts.
- Produces a verification report mapping every spec requirement to evidence.

- [ ] Add dependency declarations for FastAPI, Uvicorn and `python-multipart` with compatible minimum versions.
- [ ] Verify both project Python discovery and the configured `openclaw` environment; do not hard-code a new machine-specific path.
- [ ] Remove stale ignored `company_research` cache-only directories after confirming they contain no source or user data.
- [ ] Run `python -m compileall -q kenradar scripts` and full pytest in the project runtime.
- [ ] Run frontend lint, component tests and Vite build.
- [ ] Back up PostgreSQL, apply migrations through head, restart Web/worker with loopback default, and verify health/status/content endpoints.
- [ ] Measure bootstrap/dashboard/content APIs and record sizes/latencies.
- [ ] Audit every spec section against code, tests, database and runtime evidence; write the verification report.
