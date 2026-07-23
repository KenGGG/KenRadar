# Unified Run Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge processing and publishing navigation into a task-first command center that exposes progress, blockers, diagnostics, and safe repair actions on one page.

**Architecture:** Keep `/run` and the existing backend APIs authoritative. Extend `RunCenterModel` to normalize and sort task-centric presentation data, split the oversized `RunCenter` UI into focused task command components, and preserve legacy URLs by mapping them to a selected diagnostics section inside the unified page.

**Tech Stack:** React 19, TypeScript 5.8, Tailwind CSS 4, Vite 6, existing KenRadar JSON APIs and SSE/ polling state.

## Global Constraints

- Do not change workflow ordering, database schema, task orchestration, Agnes rate limiting, or GPU coordination.
- Keep `/publish`, `/pushes`, `/logs`, and `/run?tab=history` compatible.
- High-impact actions require confirmation; ordinary single-item retry remains direct.
- Preserve dark mode, mobile usability, text fallback, and existing API contracts.
- Do not mix generated `docs/notes` or `docs/briefs` changes into feature commits.

---

### Task 1: Canonical Navigation and Legacy URL Intent

**Files:**
- Modify: `kenradar/web/frontend/src/components/Navigation.tsx`
- Modify: `kenradar/web/frontend/src/hooks/useAppState.ts`
- Modify: `kenradar/web/frontend/src/AppContent.tsx`

**Interfaces:**
- Produces: one page id, `run`, for every processing/publishing route.
- Produces: query parameter `section=publishing|logs` for legacy deep links.

- [ ] Remove the `publish` item from `Navigation.navItems` and rename `run` to `处理中心`.
- [ ] Change `pageFromPath()` so `/publish`, `/pushes`, `/logs`, `/ops`, `/operations`, and `/failures` all return `run`.
- [ ] In location handling, replace the special `setCurrentPage('publish')` branch with `setCurrentPage('run')` while retaining the URL query for section selection.
- [ ] Change `navigateTo('publish')` to write `/run?section=publishing`, and ensure state remains `run`.
- [ ] Render `RunCenter` only for `currentPage === 'run'` and pass initial section intent derived from location.
- [ ] Run `npm run lint`; expect zero TypeScript errors.

### Task 2: Task-Centric Presentation Model

**Files:**
- Modify: `kenradar/web/frontend/src/components/RunCenterModel.ts`
- Modify: `kenradar/web/frontend/src/components/RunCenterModel.test.ts`

**Interfaces:**
- Produces: `RunTaskView` with `task`, `state`, `stageLabel`, `progress`, `counts`, `sortRank`, and `updatedAt`.
- Produces: `buildTaskViews(tasks)` ordered failed/paused, processing, queued, then recent completed.
- Produces: `todayPushSuccess(pushRecords)` using successful push records.

- [ ] Add failing model tests covering deterministic task ordering, stage labels, progress bounds, and successful-push counting.
- [ ] Run `npx tsx --test src/components/RunCenterModel.test.ts`; expect the new assertions to fail.
- [ ] Implement normalized task state and ordering without mutating input arrays.
- [ ] Extend `buildRunCenterModel` to expose ordered task views while preserving existing fields used by current components.
- [ ] Run the model test again; expect all tests to pass.

### Task 3: Task Command Components and Layout

**Files:**
- Create: `kenradar/web/frontend/src/components/run-center/TaskCommandList.tsx`
- Create: `kenradar/web/frontend/src/components/run-center/TaskCommandCard.tsx`
- Create: `kenradar/web/frontend/src/components/run-center/TaskDiagnostics.tsx`
- Modify: `kenradar/web/frontend/src/components/RunCenter.tsx`

**Interfaces:**
- `TaskCommandList({ taskViews, system, logs, onLoadDetails, onRetryFailed })` owns the single expanded task id.
- `TaskCommandCard` renders the seven-stage chain and delegates expanded diagnostics.
- `TaskDiagnostics` renders task counts, lanes, locks, relevant logs, and repair controls.

- [ ] Build a compact summary grid for running, queued, repair attention, and today's successful publishing.
- [ ] Keep `RepairWindow` above the main list and add confirmation to bulk retry while keeping single-video retry direct.
- [ ] Render task cards in model order with one expanded card at a time.
- [ ] Render the stage chain `发现 → 下载 → 转录 → AI 整理 → 笔记 → Pages 发布 → 飞书通知`, using explicit success/running/waiting/failed/skipped styles.
- [ ] In expanded diagnostics, reuse runtime lanes and locks, show related recent logs, and expose task details or failed-item repair entry points available through existing callbacks.
- [ ] Move publishing, alerts, logs, and model/GPU content into one bottom diagnostics section; preserve existing content rather than duplicating it.
- [ ] Run `npm run lint`; expect zero TypeScript errors.

### Task 4: Route-Selected Diagnostics and Responsive Behavior

**Files:**
- Modify: `kenradar/web/frontend/src/components/RunCenter.tsx`
- Modify: `kenradar/web/frontend/src/hooks/useAppState.ts`
- Modify: `kenradar/web/frontend/src/index.css` only if existing utilities cannot express the responsive stage chain.

**Interfaces:**
- Consumes: `initialSection?: 'publishing' | 'logs' | null`.
- Produces: accessible tab and details controls with route-driven initial selection.

- [ ] Auto-open publishing history for `/publish`, `/pushes`, and `/run?tab=history`.
- [ ] Auto-open logs for `/logs` while keeping `/run` focused on the task list.
- [ ] Ensure task summaries and repair buttons remain usable at 375px width; stage chain may horizontally scroll.
- [ ] Ensure buttons have labels, details summaries are keyboard operable, and status is not encoded by color alone.
- [ ] Run `npm run lint` and `npm run build`; expect both to pass.

### Task 5: Verification and Documentation Alignment

**Files:**
- Modify: `README.md`
- Modify: `docs/goal.md` only where navigation names or compatibility paths are described.

**Interfaces:**
- No new runtime interface; documents the canonical processing center and legacy URL behavior.

- [ ] Update documentation to use “处理中心” and explain that publishing records live in its diagnostic history.
- [ ] Run `npx tsx --test src/components/RunCenterModel.test.ts`; expect all tests to pass.
- [ ] Run `npm run lint` and `npm run build`; expect both to pass.
- [ ] Run `python -m compileall kenradar scripts`; expect success.
- [ ] Run `python -m pytest tests/test_api_contract.py -q`; expect success.
- [ ] Verify `/run`, `/publish`, `/pushes`, `/logs`, and `/run?tab=history` against the running Web service and confirm they return the React application.
- [ ] Inspect the final diff and exclude generated content under `docs/notes`, `docs/briefs`, `docs/index.html`, `.playwright-mcp`, and `kenradar.egg-info`.
