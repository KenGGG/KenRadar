# Processing Publishing Dashboard Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn “处理与发布” into a single-page dashboard that prioritizes runtime progress and exposes a repair window only when failures need action.

**Architecture:** Add a small pure TypeScript model for dashboard state, counts, and failed-item grouping. Keep existing backend APIs and retry callbacks unchanged. Refactor `RunCenter.tsx` to consume the model and render one page with supporting details in compact disclosure panels.

**Tech Stack:** React 19, TypeScript, Vite, lucide-react, existing KenRadar Web APIs.

---

## File Structure

- Create `kenradar/web/frontend/src/components/RunCenterModel.ts`
  - Pure helpers for dashboard status, counts, stage labels, and failed-item grouping.
- Create `kenradar/web/frontend/src/components/RunCenterModel.test.ts`
  - Executable TypeScript tests using Node `assert` and `tsx`.
- Modify `kenradar/web/frontend/src/components/RunCenter.tsx`
  - Replace primary tabs with a single dashboard layout.
  - Add a compact repair window with automatic retry as the primary action.
  - Move publishing/logs/model details into supporting disclosure panels.
- Modify `docs/superpowers/specs/2026-07-10-processing-publishing-dashboard-design.md`
  - Already translated to Chinese per user request.

## Task 1: Dashboard Model

**Files:**
- Create: `kenradar/web/frontend/src/components/RunCenterModel.test.ts`
- Create: `kenradar/web/frontend/src/components/RunCenterModel.ts`

- [x] **Step 1: Write the failing model tests**

```ts
import assert from 'node:assert/strict';
import { buildRunCenterModel, failedStageLabel, groupFailuresByStage } from './RunCenterModel';
import { VideoContent, ResearchTask, SystemInfo } from '../types';

function video(overrides: Partial<VideoContent>): VideoContent {
  return {
    id: '1',
    title: '样例视频',
    blogger: '样例博主',
    rating: 0,
    recommend_action: '',
    status: 'completed',
    created_at: '2026-07-10 09:00:00',
    duration: '',
    original_url: '',
    tags: [],
    whisper_text: '',
    summary_markdown: '',
    ...overrides,
  };
}

const videos = [
  video({ id: 'failed-ai', status: 'failed', failed_at_step: 'ai', error_message: 'AI timeout' }),
  video({ id: 'failed-download', status: 'failed', failed_at_step: 'download', error_message: 'download 403' }),
  video({ id: 'processing', status: 'processing' }),
];
const tasks: ResearchTask[] = [
  { id: 'job-1', type: 'blogger', target: '研究博主', status: 'queued', created_at: '2026-07-10 09:10:00', pipeline_progress: 0 },
];
const system: SystemInfo = {
  port: 8765,
  gpu_label: 'GPU 调度',
  gpu_status: '空闲',
  gpu_percent: 0,
  whisper_model: 'large-v3-turbo',
  log_path: 'data/kenradar.log',
  health: { alert_attention: 1, next_run: '12:00', schedule: '启用' },
  background_task: { running: true, message: '手动检测运行中', queue: [{ task_id: 'queued-run' }] } as any,
};

const model = buildRunCenterModel({ videos, tasks, system, alerts: [] });
assert.equal(model.state, 'needs_repair');
assert.equal(model.counts.failed, 2);
assert.equal(model.counts.repair, 2);
assert.equal(model.counts.running, 2);
assert.equal(model.counts.waiting, 2);
assert.equal(model.nextRun, '12:00');
assert.equal(failedStageLabel('ai'), 'AI/笔记');
assert.deepEqual(groupFailuresByStage(videos).map(group => group.key), ['download', 'ai']);

const idleModel = buildRunCenterModel({ videos: [video({ id: 'done' })], tasks: [], system: { ...system, background_task: undefined, health: {} }, alerts: [] });
assert.equal(idleModel.state, 'idle');
assert.equal(idleModel.bannerTitle, '系统空闲');

console.log('RunCenterModel tests passed');
```

- [x] **Step 2: Run the test to verify it fails**

Run:

```bash
cd kenradar/web/frontend
npx tsx src/components/RunCenterModel.test.ts
```

Expected: FAIL because `RunCenterModel` does not exist yet.

- [x] **Step 3: Implement the model**

Create `RunCenterModel.ts` with exported helpers matching the test imports:

```ts
import { AlertRecord, ResearchTask, SystemInfo, VideoContent } from '../types';

export type RunCenterState = 'idle' | 'running' | 'needs_repair';
export type RetryStage = 'download' | 'transcribe' | 'ai' | 'push';

export const RETRY_STAGES: RetryStage[] = ['download', 'transcribe', 'ai', 'push'];

export function failedStage(video: VideoContent): RetryStage | undefined {
  const stage = video.failed_at_step || video.failure_stage;
  return RETRY_STAGES.includes(stage as RetryStage) ? stage as RetryStage : undefined;
}

export function failedStageLabel(stage?: RetryStage | 'other') {
  if (stage === 'download') return '下载';
  if (stage === 'transcribe') return '转录';
  if (stage === 'ai') return 'AI/笔记';
  if (stage === 'push') return '发布/推送';
  return '未识别阶段';
}

export function groupFailuresByStage(videos: VideoContent[]) {
  return [...RETRY_STAGES, 'other' as const]
    .map(stage => {
      const items = videos.filter(video => {
        if (video.status !== 'failed') return false;
        const current = failedStage(video);
        return stage === 'other' ? !current : current === stage;
      });
      return { key: stage, label: failedStageLabel(stage), items };
    })
    .filter(group => group.items.length > 0);
}

export function buildRunCenterModel({
  videos,
  tasks,
  system,
  alerts,
}: {
  videos: VideoContent[];
  tasks: ResearchTask[];
  system: SystemInfo;
  alerts: AlertRecord[];
}) {
  const failedVideos = videos.filter(video => video.status === 'failed');
  const runningTasks = tasks.filter(task => task.status === 'processing' || task.status === 'paused').length;
  const queuedTasks = tasks.filter(task => task.status === 'queued').length;
  const backgroundRunning = system.background_task?.running ? 1 : 0;
  const backgroundQueued = system.background_task?.queue?.length || 0;
  const alertAttention = Number(system.health?.alert_attention || 0);
  const repair = Math.max(failedVideos.length, alertAttention);
  const running = runningTasks + backgroundRunning + videos.filter(video => video.status === 'processing').length;
  const waiting = queuedTasks + backgroundQueued + videos.filter(video => video.status === 'queued').length;
  const state: RunCenterState = repair > 0 ? 'needs_repair' : running > 0 || waiting > 0 ? 'running' : 'idle';

  return {
    state,
    failedVideos,
    failureGroups: groupFailuresByStage(videos),
    nextRun: String(system.health?.next_run || '暂无'),
    schedule: String(system.health?.schedule || '未知'),
    counts: {
      running,
      waiting,
      failed: failedVideos.length,
      repair,
      alerts: alerts.length,
    },
    bannerTitle: state === 'needs_repair' ? '需要处理' : state === 'running' ? '系统运行中' : '系统空闲',
    bannerText: state === 'needs_repair'
      ? '有失败内容或告警需要修复，建议先处理修复窗口。'
      : state === 'running'
        ? '任务正在按流水线执行，无需人工干预。'
        : '当前没有处理中的任务，等待下一次定时检测。',
  };
}
```

- [x] **Step 4: Run the test to verify it passes**

Run:

```bash
cd kenradar/web/frontend
npx tsx src/components/RunCenterModel.test.ts
```

Expected: PASS and prints `RunCenterModel tests passed`.

## Task 2: Single-Page RunCenter UI

**Files:**
- Modify: `kenradar/web/frontend/src/components/RunCenter.tsx`

- [x] **Step 1: Refactor imports and consume the model**

Remove the primary tab state from `RunCenter`. Import `buildRunCenterModel`, `failedStage`, and `failedStageLabel`.

- [x] **Step 2: Add `RepairWindow`**

Render failed videos grouped by stage. The primary action must call `retryStage(video.id)` for automatic/full retry. The expanded advanced controls must call `retryStage(video.id, failedStage(video))` and `bulkRetryFailed(stage)`.

- [x] **Step 3: Render one dashboard page**

Render:

1. Header and state banner.
2. Runtime timeline.
3. Current work and queue.
4. Repair window when failures exist.
5. Supporting details using `<details>` for publishing/logs/alerts and model/GPU.

- [x] **Step 4: Keep existing URLs functional**

Do not remove route handling. `/run?tab=history` and `/publish` should still render the same dashboard because routing already maps them to `RunCenter`.

## Task 3: Verification

**Files:**
- Existing frontend and Python project files.

- [x] **Step 1: Run model tests**

```bash
cd kenradar/web/frontend
npx tsx src/components/RunCenterModel.test.ts
```

- [x] **Step 2: Run frontend type check**

```bash
cd kenradar/web/frontend
npm run lint
```

- [x] **Step 3: Run frontend build**

```bash
cd kenradar/web/frontend
npm run build
```

- [x] **Step 4: Run backend smoke checks if frontend changes touched shared API assumptions**

```bash
python -m compileall kenradar scripts
python -m pytest tests/test_config_and_publishing.py -q
```

## Self-Review

- The plan covers every spec section.
- There are no placeholders.
- Types and function names are consistent across tests and implementation.
