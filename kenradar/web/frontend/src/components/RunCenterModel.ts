/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { AlertRecord, PushRecord, ResearchTask, SystemInfo, VideoContent } from '../types';

export type RunCenterState = 'idle' | 'running' | 'needs_repair';
export type RetryStage = 'download' | 'transcribe' | 'ai' | 'push';

export const RETRY_STAGES: RetryStage[] = ['download', 'transcribe', 'ai', 'push'];

export type RunTaskState = 'failed' | 'paused' | 'running' | 'queued' | 'completed';

export interface RunTaskView {
  task: ResearchTask;
  state: RunTaskState;
  stageLabel: string;
  progress: number;
  sortRank: number;
  updatedAt: string;
}

function taskState(task: ResearchTask): RunTaskState {
  if (task.status === 'failed') return 'failed';
  if (task.status === 'paused') return 'paused';
  if (task.status === 'processing') return 'running';
  if (task.status === 'queued') return 'queued';
  return 'completed';
}

export function buildTaskViews(tasks: ResearchTask[]): RunTaskView[] {
  const ranks: Record<RunTaskState, number> = { failed: 0, paused: 0, running: 1, queued: 2, completed: 3 };
  return tasks
    .map(task => {
      const state = taskState(task);
      return {
        task,
        state,
        stageLabel: runtimeStageLabel(task.pipeline_stage || task.status),
        progress: Math.max(0, Math.min(100, Number(task.pipeline_progress || 0))),
        sortRank: ranks[state],
        updatedAt: task.created_at,
      };
    })
    .sort((left, right) => left.sortRank - right.sortRank || right.updatedAt.localeCompare(left.updatedAt));
}

function localDateKey(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function todayPushSuccess(records: PushRecord[], now = new Date()) {
  const today = localDateKey(now);
  return records.filter(record => record.status === 'success' && String(record.sent_at || '').slice(0, 10) === today).length;
}

export function runCenterSectionFromLocation(pathname: string, search: string): 'push' | 'logs' | undefined {
  const params = new URLSearchParams(search);
  if (pathname.startsWith('/publish') || pathname === '/pushes' || pathname.startsWith('/logs/pushes') || params.get('section') === 'publishing' || params.get('tab') === 'history') return 'push';
  if (pathname.startsWith('/logs') || params.get('section') === 'logs') return 'logs';
  return undefined;
}

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

export function runtimeStageLabel(stage?: string) {
  const value = String(stage || '').toLowerCase();
  if (value === 'download' || value === 'downloading') return '下载';
  if (value === 'transcribe' || value === 'transcribing' || value === 'whisper') return '转录';
  if (value === 'ai' || value === 'summary' || value === 'summarizing' || value === 'organizer') return 'AI 整理';
  if (value === 'note' || value === 'noting' || value === 'publishing') return '笔记发布';
  if (value === 'push' || value === 'pushing' || value === 'feishu') return '飞书通知';
  if (value === 'completed' || value === 'success') return '全部完成';
  if (value === 'failed') return '执行失败';
  return stage || '运行中';
}

function laneKeyForStage(stage?: string) {
  const value = String(stage || '').toLowerCase();
  if (value === 'download' || value === 'downloading') return 'download';
  if (value === 'transcribe' || value === 'transcribing' || value === 'whisper') return 'transcribe';
  if (value === 'ai' || value === 'summary' || value === 'summarizing' || value === 'organizer') return 'ai';
  return value;
}

export function normalizeRuntimeTimeline(timeline?: any) {
  if (!timeline) return timeline;
  const entries = (timeline.entries || []).map((entry: any) => ({
    ...entry,
    stage: runtimeStageLabel(entry.stage),
  }));
  const activeStageKeys = new Set(
    (timeline.entries || [])
      .filter((entry: any) => String(entry.status || '') === 'running')
      .map((entry: any) => laneKeyForStage(entry.stage))
      .filter(Boolean)
  );
  const lanes = (timeline.lanes || []).map((lane: any) => {
    const key = String(lane.key || '');
    if (!activeStageKeys.has(key)) return lane;
    return {
      ...lane,
      active: Math.max(1, Number(lane.active || 0)),
      status: 'active',
    };
  });
  return {
    ...timeline,
    entries,
    lanes,
    stage_label: runtimeStageLabel(timeline.stage_label),
  };
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
  const repair = failedVideos.length;
  const running = runningTasks + backgroundRunning + videos.filter(video => video.status === 'processing').length;
  const waiting = queuedTasks + backgroundQueued + videos.filter(video => video.status === 'queued').length;
  const state: RunCenterState = repair > 0 ? 'needs_repair' : running > 0 || waiting > 0 ? 'running' : 'idle';

  return {
    state,
    taskViews: buildTaskViews(tasks),
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
