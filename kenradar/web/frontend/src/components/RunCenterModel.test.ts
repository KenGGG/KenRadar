/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import assert from 'node:assert/strict';
import { buildRunCenterModel, buildTaskViews, failedStageLabel, groupFailuresByStage, normalizeRuntimeTimeline, runCenterSectionFromLocation, todayPushSuccess } from './RunCenterModel';
import { PushRecord, ResearchTask, SystemInfo, VideoContent } from '../types';

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

const idleModel = buildRunCenterModel({
  videos: [video({ id: 'done' })],
  tasks: [],
  system: { ...system, background_task: undefined, health: {} },
  alerts: [],
});
assert.equal(idleModel.state, 'idle');
assert.equal(idleModel.bannerTitle, '系统空闲');

const normalizedTimeline = normalizeRuntimeTimeline({
  entries: [
    {
      id: 'active-194',
      status: 'running',
      stage: 'ai',
      title: '正在处理：正在Agnes AI 整理 (3/10)',
      subtitle: '正在Agnes AI 整理 (3/10)',
      progress: 30,
    },
  ],
  locks: [],
  lanes: [
    { key: 'download', label: '下载', active: 0, waiting: 0, done: 0, capacity: 5, status: 'idle', detail: '下载队列' },
    { key: 'transcribe', label: '转录', active: 0, waiting: 0, done: 0, capacity: 2, status: 'idle', detail: '转录队列' },
    { key: 'ai', label: 'AI 整理', active: 0, waiting: 0, done: 0, capacity: 1, status: 'idle', detail: 'AI 队列' },
  ],
  progress_percent: 30,
  stage_label: 'ai',
});
assert.equal(normalizedTimeline.stage_label, 'AI 整理');
assert.equal(normalizedTimeline.entries[0].stage, 'AI 整理');
assert.equal(normalizedTimeline.lanes.find(lane => lane.key === 'ai')?.active, 1);
assert.equal(normalizedTimeline.lanes.find(lane => lane.key === 'ai')?.status, 'active');

const orderedTasks: ResearchTask[] = [
  { id: 'done', type: 'single', target: '已完成', status: 'completed', created_at: '2026-07-10 08:00:00', pipeline_progress: 100 },
  { id: 'queued', type: 'blogger', target: '排队任务', status: 'queued', created_at: '2026-07-10 11:00:00', pipeline_progress: -10 },
  { id: 'running', type: 'blogger', target: '运行任务', status: 'processing', created_at: '2026-07-10 10:00:00', pipeline_stage: 'summarizing', pipeline_progress: 68 },
  { id: 'failed', type: 'single', target: '失败任务', status: 'failed', created_at: '2026-07-10 12:00:00', pipeline_stage: 'failed', pipeline_progress: 140, failed_items: 1 },
];
const taskViews = buildTaskViews(orderedTasks);
assert.deepEqual(taskViews.map(view => view.task.id), ['failed', 'running', 'queued', 'done']);
assert.equal(taskViews[0].state, 'failed');
assert.equal(taskViews[0].progress, 100);
assert.equal(taskViews[1].stageLabel, 'AI 整理');
assert.equal(taskViews[2].progress, 0);

const pushes: PushRecord[] = [
  { id: '1', aweme_id: 'a', title: 'A', blogger: '甲', push_type: 'card', sent_at: '2026-07-23 09:00:00', status: 'success', payload: '' },
  { id: '2', aweme_id: 'b', title: 'B', blogger: '乙', push_type: 'text', sent_at: '2026-07-23 10:00:00', status: 'failed', payload: '' },
  { id: '3', aweme_id: 'c', title: 'C', blogger: '丙', push_type: 'card', sent_at: '2026-07-22 23:59:59', status: 'success', payload: '' },
];
assert.equal(todayPushSuccess(pushes, new Date('2026-07-23T12:00:00+08:00')), 1);
assert.equal(runCenterSectionFromLocation('/logs/pushes', ''), 'push');
assert.equal(runCenterSectionFromLocation('/logs', ''), 'logs');
assert.equal(runCenterSectionFromLocation('/run', '?tab=history'), 'push');
assert.equal(runCenterSectionFromLocation('/run', ''), undefined);

console.log('RunCenterModel tests passed');
