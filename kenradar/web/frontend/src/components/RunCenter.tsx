/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * RunCenter - Processing and publishing center
 * 4 tabs: Pipeline | Retry | Publishing | Models & GPU
 * Overview dynamically adapts to system state.
 */

import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Cpu,
  Copy,
  Eye,
  Gauge,
  Github,
  History,
  LockKeyhole,
  PauseCircle,
  Power,
  Radio,
  RefreshCw,
  RotateCw,
  Search,
  Send,
  Terminal,
} from 'lucide-react';
import { TaskProgressBar, TaskStageCounts, taskStatusClass, taskStatusLabel } from './TaskProgress';
import { buildRunCenterModel, failedStage, failedStageLabel, normalizeRuntimeTimeline, RetryStage, runCenterSectionFromLocation } from './RunCenterModel';
import { AlertRecord, PushRecord, ResearchTask, SystemConfig, SystemInfo, SystemLog, VideoContent } from '../types';
import { EmptyState } from './UITokens';
import TaskCommandList from './run-center/TaskCommandList';

/* ── Types ── */
type RunTab = 'overview' | 'retry' | 'history' | 'models';

interface RunCenterProps {
  videos: VideoContent[];
  tasks: ResearchTask[];
  retryStage: (id: string, stage?: 'download' | 'transcribe' | 'ai' | 'push') => void;
  bulkRetryFailed: (step?: 'download' | 'transcribe' | 'ai' | 'push') => void;
  retryResearchFailed: (taskId: string) => void;
  navigateTo: (page: string, id: string | null) => void;
  pushRecords: PushRecord[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  config: SystemConfig;
  rebootWebUI: () => void;
  triggerManualScan: () => void;
}

/* ── Helpers ── */
function healthTone(failedCount: number, alertCount: number, runningCount: number) {
  if (alertCount > 0 || failedCount > 0) return { label: '需要处理', className: 'border-amber-150 bg-amber-50/60 dark:bg-[var(--warning-bg)] dark:border-[var(--warning-border)] text-amber-900 dark:text-[var(--warning)]', icon: AlertTriangle };
  if (runningCount > 0) return { label: '运行中', className: 'border-blue-150 bg-blue-50/60 dark:bg-[var(--info-bg)] dark:border-[var(--info-border)] text-blue-900 dark:text-[var(--info)]', icon: Activity };
  return { label: '正常运行', className: 'border-emerald-150 bg-emerald-50/50 dark:bg-[var(--success-bg)] dark:border-[var(--success-border)] text-emerald-900 dark:text-[var(--success)]', icon: CheckCircle2 };
}

function runtimeStatusClass(status: string) {
  if (status === 'running') return 'border-blue-100 bg-blue-50 text-blue-700 dark:bg-[var(--info-bg)] dark:border-[var(--info-border)] dark:text-[var(--info)]';
  if (status === 'paused') return 'border-amber-100 bg-amber-50 text-amber-700 dark:bg-[var(--warning-bg)] dark:border-[var(--warning-border)] dark:text-[var(--warning)]';
  if (status === 'failed') return 'border-red-100 bg-red-50 text-red-700 dark:bg-[var(--danger-bg)] dark:border-[var(--danger-border)] dark:text-[var(--danger)]';
  return 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:bg-[var(--surface-muted)] dark:border-[var(--surface-border)] dark:text-[var(--text-secondary)]';
}

function runtimeLockClass(status: string) {
  if (status === 'busy') return 'border-blue-100 bg-blue-50 text-blue-800 dark:bg-[var(--info-bg)] dark:border-[var(--info-border)] dark:text-[var(--info)]';
  if (status === 'blocked') return 'border-amber-100 bg-amber-50 text-amber-800 dark:bg-[var(--warning-bg)] dark:border-[var(--warning-border)] dark:text-[var(--warning)]';
  return 'border-zinc-200 bg-white dark:bg-[var(--surface)] dark:border-[var(--surface-border)] text-zinc-600 dark:text-[var(--text-secondary)]';
}

function runtimeLockLabel(status: string) {
  if (status === 'busy') return '占用中';
  if (status === 'blocked') return '排队等待';
  return '空闲';
}

function RunTimelinePanel({ system, logs }: { system: SystemInfo; logs: SystemLog[] }) {
  const timeline = normalizeRuntimeTimeline(system.runtime_timeline);
  const entries = timeline?.entries || [];
  const locks = timeline?.locks || [];
  const lanes = timeline?.lanes || [];
  const recentLogs = logs
    .filter(log => /转录|AI|定时|暂缓|插队|研究任务|队列|下载|笔记/.test(log.message))
    .slice(0, Math.max(0, 5 - entries.length));
  const progress = Math.max(0, Math.min(100, Number(timeline?.progress_percent ?? 0)));
  const isIdle = entries.length === 0 && !system.background_task?.running;

  return (
    <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
      <div className="flex flex-col gap-3 border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">
            <Radio className="h-4 w-4 text-blue-600 dark:text-[var(--info)]" />
            流程时间线
          </h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
            {isIdle ? '当前没有处理中的内容。' : `${timeline?.stage_label || '运行中'} · ${progress}%`}
          </p>
        </div>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {locks.map(lock => (
            <div key={lock.key} className={`flex min-w-[190px] items-center gap-2 rounded-md border px-3 py-2 text-xs ${runtimeLockClass(lock.status)}`}>
              <LockKeyhole className="h-3.5 w-3.5 shrink-0 text-zinc-500 dark:text-[var(--text-secondary)]" />
              <div className="min-w-0">
                <div className="font-semibold">{lock.label} · {runtimeLockLabel(lock.status)}</div>
                <div className="mt-0.5 truncate opacity-75" title={lock.holder || lock.detail}>{lock.holder || lock.detail}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {lanes.length > 0 && (
        <div className="grid grid-cols-1 gap-px border-b border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-100 dark:bg-[var(--surface-border)] md:grid-cols-3">
          {lanes.map(lane => {
            const active = Number(lane.active || 0);
            const waiting = Number(lane.waiting || 0);
            const capacity = Math.max(1, Number(lane.capacity || 1));
            const laneTone = active > 0 ? 'text-blue-700' : waiting > 0 ? 'text-amber-700' : 'text-zinc-600';
            const fill = Math.max(0, Math.min(100, Math.round((active / capacity) * 100)));
            return (
              <div key={lane.key} className="bg-white dark:bg-[var(--surface)] px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{lane.label}</div>
                  <span className={`rounded border px-1.5 py-0.5 text-[10px] font-medium ${active > 0 ? 'border-blue-100 bg-blue-50 text-blue-700 dark:bg-[var(--info-bg)] dark:border-[var(--info-border)] dark:text-[var(--info)]' : waiting > 0 ? 'border-amber-100 bg-amber-50 text-amber-700 dark:bg-[var(--warning-bg)] dark:border-[var(--warning-border)] dark:text-[var(--warning)]' : 'border-zinc-200 bg-zinc-50 text-zinc-500 dark:bg-[var(--surface-muted)] dark:border-[var(--surface-border)] dark:text-[var(--text-muted)]'}`}>
                    {active > 0 ? '运行中' : waiting > 0 ? '等待中' : '空闲'}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <div className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)]">运行</div>
                    <div className={`mt-0.5 font-mono font-semibold tabular-nums ${laneTone} dark:text-[var(--text-primary)]`}>{active}/{capacity}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-zinc-400">等待</div>
                    <div className="mt-0.5 font-mono font-semibold tabular-nums text-zinc-800 dark:text-[var(--text-primary)]">{waiting}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-zinc-400">已过本段</div>
                    <div className="mt-0.5 font-mono font-semibold tabular-nums text-zinc-800 dark:text-[var(--text-primary)]">{lane.done}</div>
                  </div>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]">
                  <div className="h-full rounded-full bg-blue-500 transition-all" style={{ width: `${fill}%` }} />
                </div>
                <div className="mt-2 truncate text-[11px] text-zinc-500 dark:text-[var(--text-secondary)]" title={lane.detail}>{lane.detail}</div>
              </div>
            );
          })}
        </div>
      )}

      {!isIdle && (
        <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-3">
          <div className="flex justify-between text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
            <span>{entries[0]?.subtitle || system.background_task?.message || '后台任务'}</span>
            <span className="font-mono tabular-nums">{progress}%</span>
          </div>
          <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]">
            <div className="h-full rounded-full bg-blue-600 transition-all" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}

      <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
        {entries.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-zinc-400 dark:text-[var(--text-muted)]">等待下一次手动或定时任务。</div>
        ) : (
          entries.map((entry, index) => {
            const isPaused = entry.status === 'paused';
            const Icon = isPaused ? PauseCircle : (entry.status === 'running' ? Activity : Clock3);
            return (
              <div key={entry.id || index} className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] gap-3 px-4 py-3">
                <div className="relative pt-0.5">
                  <span className={`flex h-6 w-6 items-center justify-center rounded-full border ${runtimeStatusClass(entry.status)}`}>
                    <Icon className="h-3.5 w-3.5 dark:text-[var(--text-primary)]" />
                  </span>
                  {index < entries.length - 1 && <span className="absolute left-3 top-7 h-full w-px bg-zinc-100 dark:bg-[var(--surface-border)]" />}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{entry.title}</span>
                    <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${runtimeStatusClass(entry.status)}`}>{entry.stage}</span>
                  </div>
                  <div className="mt-1 truncate text-xs text-zinc-500 dark:text-[var(--text-secondary)]" title={entry.subtitle}>{entry.subtitle || entry.detail}</div>
                  {entry.detail && <div className="mt-1 truncate font-mono text-[11px] text-zinc-400 dark:text-[var(--text-muted)]">{entry.detail}</div>}
                </div>
                <div className="hidden text-right text-[11px] text-zinc-400 dark:text-[var(--text-muted)] sm:block">{entry.time || ''}</div>
              </div>
            );
          })
        )}
        {recentLogs.map(log => (
          <div key={log.id} className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] gap-3 px-4 py-3">
            <div className="pt-0.5">
              <span className="flex h-6 w-6 items-center justify-center rounded-full border border-zinc-200 bg-zinc-50 text-zinc-500 dark:bg-[var(--surface-muted)] dark:border-[var(--surface-border)] dark:text-[var(--text-secondary)]">
                <Terminal className="h-3.5 w-3.5 dark:text-[var(--text-secondary)]" />
              </span>
            </div>
            <div className="min-w-0">
              <div className="truncate text-xs font-medium text-zinc-700 dark:text-[var(--text-primary)]">{log.module}</div>
              <div className="mt-1 truncate text-xs text-zinc-500 dark:text-[var(--text-secondary)]" title={log.message}>{log.message}</div>
            </div>
            <div className="hidden text-right text-[11px] text-zinc-400 sm:block">{log.timestamp}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── RunTaskBoard (inline queue summary) ── */
function RunTaskBoard({ tasks, system }: { tasks: ResearchTask[]; system: SystemInfo }) {
  const queuedBackground = system.background_task?.queue || [];
  const activeTasks = tasks
    .filter(task => task.status === 'processing' || task.status === 'paused')
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const queuedTasks = tasks
    .filter(task => task.status === 'queued')
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const failedTasks = tasks.filter(task => task.status === 'failed').length;
  const waitingCount = queuedBackground.length + queuedTasks.length;
  const runningCount = activeTasks.length + (system.background_task?.running ? 1 : 0);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-4 py-3 text-sm">
        <span className="font-semibold text-zinc-900 dark:text-[var(--text-primary)]">批次队列</span>
        <span className="text-zinc-500 dark:text-[var(--text-secondary)]">进行中 <strong className="tabular-nums text-zinc-900 dark:text-[var(--text-primary)]">{runningCount}</strong></span>
        <span className="text-zinc-500 dark:text-[var(--text-secondary)]">等待 <strong className="tabular-nums text-zinc-900 dark:text-[var(--text-primary)]">{waitingCount}</strong></span>
        <span className={failedTasks > 0 ? 'text-red-700 dark:text-[var(--danger)]' : 'text-zinc-500 dark:text-[var(--text-secondary)]'}>
          失败 <strong className="tabular-nums">{failedTasks}</strong>
        </span>
        <span className="ml-auto text-xs text-zinc-400 dark:text-[var(--text-muted)]">批次按进入顺序执行</span>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
          <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-3">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">正在执行</h2>
          </div>
          <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
            {activeTasks.length === 0 && !system.background_task?.running ? (
              <div className="px-4 py-10 text-center text-sm text-zinc-400 dark:text-[var(--text-muted)]">当前没有执行中的任务。</div>
            ) : (
              <>
                {system.background_task?.running && (
                  <div className="space-y-3 px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{system.background_task.message}</div>
                        <div className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">后台执行器 · {system.background_task.started_at || '刚刚开始'}</div>
                      </div>
                      <span className="shrink-0 rounded border border-blue-100 bg-blue-50 dark:bg-[var(--info-bg)] border-blue-100 dark:border-[var(--info-border)] px-2 py-1 text-xs font-medium text-blue-700 dark:text-[var(--info)]">进行中</span>
                    </div>
                    {system.background_task.progress && (
                      <div className="space-y-1.5">
                        <div className="flex justify-between text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                          <span className="truncate">{system.background_task.progress.message}</span>
                          <span className="font-mono tabular-nums">{system.background_task.progress.current}/{system.background_task.progress.total}</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]">
                          <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.round(system.background_task.progress.current / Math.max(1, system.background_task.progress.total) * 100)}%` }} />
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {activeTasks.map(task => (
                  <div key={task.id} className="space-y-3 px-4 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{task.target}</div>
                        <div className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">研究任务 #{task.id} · 已完成 {task.completed_items || 0}/{task.total_items || 0}</div>
                      </div>
                      <span className={`shrink-0 rounded border px-2 py-1 text-xs font-medium ${taskStatusClass(task.status)}`}>{taskStatusLabel(task.status)}</span>
                    </div>
                    {task.pipeline_stages ? <TaskStageCounts stages={task.pipeline_stages} /> : <TaskProgressBar task={task} />}
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
          <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-3">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">等待队列</h2>
          </div>
          <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
            {queuedBackground.length === 0 && queuedTasks.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-zinc-400 dark:text-[var(--text-muted)]">暂无排队任务，所有任务已处理完成。</div>
            ) : (
              <>
                {queuedBackground.map(task => (
                  <div key={`${task.position}-${task.task_id}`} className="flex items-center gap-3 px-4 py-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-zinc-200 bg-zinc-50 font-mono text-xs text-zinc-600 dark:bg-[var(--surface-muted)] dark:border-[var(--surface-border)] dark:text-[var(--text-secondary)]">{task.position}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-zinc-900 dark:text-[var(--text-primary)]">{task.message || task.task_id}</div>
                      <div className="mt-1 text-xs text-zinc-400 dark:text-[var(--text-muted)]">{task.queued_at || '等待执行'}</div>
                    </div>
                    <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)]">排队中</span>
                  </div>
                ))}
                {queuedTasks.map((task, index) => (
                  <div key={task.id} className="flex items-center gap-3 px-4 py-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-zinc-200 bg-zinc-50 font-mono text-xs text-zinc-600 dark:bg-[var(--surface-muted)] dark:border-[var(--surface-border)] dark:text-[var(--text-secondary)]">{queuedBackground.length + index + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-zinc-900 dark:text-[var(--text-primary)]">{task.target}</div>
                      <div className="mt-1 text-xs text-zinc-400 dark:text-[var(--text-muted)]">研究任务 #{task.id} · {task.created_at}</div>
                    </div>
                    <span className={`text-xs ${taskStatusClass(task.status).split(' ').at(-1)}`}>{taskStatusLabel(task.status)}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

/* ── Model & GPU Panel ── */
function ModelGpuPanel({ system, config }: { system: SystemInfo; config: SystemConfig }) {
  const gpuPercent = Math.max(0, Math.min(100, Number(system.gpu_percent ?? 0)));
  const whisperDevice = config.whisper?.device || (config.whisper?.use_gpu ? 'cuda' : 'cpu');
  const aiModel = config.ai?.model || 'agnes-2.5-flash';
  const aiEndpoint = config.ai?.endpoint || '未配置 endpoint';
  const fallbackEnabled = config.ai?.fallback_enabled ?? true;
  const fallbackEndpoint = config.ai?.fallback_endpoint || 'http://127.0.0.1:11434/v1';
  const services = [
    { name: 'FunASR', value: '优先转录服务', status: '配置启用', tone: 'green' },
    { name: 'Whisper', value: `${system.whisper_model || config.whisper?.model || 'large-v3-turbo'} · ${whisperDevice}`, status: '转录后备', tone: 'zinc' },
    { name: 'Agnes AI', value: aiModel, status: aiEndpoint, tone: 'green' },
    { name: 'Ollama', value: '本地 AI 整理后备', status: fallbackEnabled ? fallbackEndpoint : '后备未启用', tone: 'blue' },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 animate-fade-in xl:grid-cols-[minmax(260px,0.75fr)_minmax(0,1.75fr)]">
      <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">GPU 资源</h2>
            <p className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{system.gpu_label || 'GPU 调度'}</p>
          </div>
          <span className="text-lg font-semibold tabular-nums text-zinc-950">{gpuPercent}%</span>
        </div>
        <div className="mt-5 h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]">
          <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${gpuPercent}%` }} />
        </div>
        <div className="mt-4 flex items-center justify-between text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
          <span>调度状态</span>
          <span className="font-medium text-zinc-800">{system.gpu_status || '未知'}</span>
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
          <span>Whisper</span>
          <span className="font-mono text-zinc-700">{system.whisper_model || config.whisper?.model || 'large-v3-turbo'} · {whisperDevice}</span>
        </div>
      </section>

      <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
        <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-5 py-4">
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">模型与服务</h2>
          <p className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">Agnes AI 为主整理引擎，Ollama 仅在主引擎不可用时后备。</p>
        </div>
        <div className="grid grid-cols-1 gap-px bg-zinc-100 dark:bg-[var(--surface-border)] md:grid-cols-2">
          {services.map(service => (
            <div key={service.name} className="bg-white dark:bg-[var(--surface)] px-5 py-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{service.name}</div>
                <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                  service.tone === 'green' ? 'bg-emerald-50 text-emerald-700' :
                  service.tone === 'blue' ? 'bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)]' : 'bg-white dark:bg-[var(--surface)] text-zinc-600 dark:text-[var(--text-secondary)]'
                }`}>{service.status}</span>
              </div>
              <div className="mt-2 break-all font-mono text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{service.value}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

/* ── Overview Panel (dynamic by system state) ── */
function RunOverviewPanel({
  videos,
  tasks,
  logs,
  alerts,
  system,
  triggerManualScan,
  switchTab,
}: {
  videos: VideoContent[];
  tasks: ResearchTask[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  triggerManualScan: () => void;
  switchTab: (tab: RunTab) => void;
}) {
  const failedVideos = videos.filter(video => video.status === 'failed');
  const activeResearch = tasks.filter(task => task.status === 'processing' || task.status === 'paused').sort((a, b) => b.created_at.localeCompare(a.created_at));
  const queuedTasks = system.background_task?.queue || [];
  const alertCount = Number(system.health?.alert_attention || 0);
  const attentionCount = failedVideos.length;
  const extraAlertCount = Math.max(0, alertCount - failedVideos.length);
  const runningTaskCount = activeResearch.length + (system.background_task?.running ? 1 : 0);
  const waitingCount = queuedTasks.length + tasks.filter(task => task.status === 'queued').length;
  const tone = healthTone(failedVideos.length, extraAlertCount, runningTaskCount);
  const HealthIcon = tone.icon;
  const recentLog = logs[0];

  const isIdle = runningTaskCount === 0 && waitingCount === 0 && attentionCount === 0;
  const isRunning = runningTaskCount > 0 || waitingCount > 0;
  const hasErrors = attentionCount > 0;

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Status banner */}
      <section className={`rounded-lg border ${tone.className}`}>
        <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <HealthIcon className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
            <div className="text-sm font-semibold">系统{tone.label}</div>
            <p className="mt-1 text-xs leading-5 opacity-80">
                {hasErrors ? '有需要处理的异常，建议先完成恢复操作。' :
                 isRunning ? '任务正在按流水线执行，无需人工干预。' :
                 '系统空闲，等待下一次定时检测。'}
            </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={triggerManualScan}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-white/80 dark:border-[var(--surface-border)]/50 bg-white/80 dark:bg-[var(--surface)]/80 px-3 text-xs font-medium text-zinc-800 dark:text-[var(--text-primary)] hover:bg-white dark:hover:bg-[var(--surface-muted)]"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              手动检测
            </button>
            {hasErrors && (
              <button
                type="button"
                onClick={() => switchTab('retry')}
                className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 dark:bg-[var(--warning-bg)] px-3 text-xs font-medium text-amber-800 dark:text-[var(--warning)] hover:bg-amber-100 dark:hover:bg-[var(--warning-bg)]"
              >
                <AlertTriangle className="h-3.5 w-3.5" />
                查看失败
              </button>
            )}
          </div>
        </div>
        <div className="grid grid-cols-2 border-t border-current/10 md:grid-cols-5">
          {[
            ['调度', system.health.schedule || '未知'],
            ['进行中', `${runningTaskCount} 项`],
            ['等待', `${waitingCount} 项`],
            ['需处理', `${attentionCount} 项`],
            ['下次运行', system.health.next_run || '暂无'],
          ].map(([label, value]) => (
            <div key={label} className="border-r border-current/10 px-4 py-3 last:border-r-0">
              <div className="text-[11px] opacity-60">{label}</div>
              <div className="mt-1 truncate text-sm font-semibold tabular-nums" title={String(value)}>{value}</div>
            </div>
          ))}
        </div>
      </section>

      <RunTimelinePanel system={system} logs={logs} />

      {/* ── IDLE state: last-run summary + quick actions ── */}
      {isIdle && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-4">
            <h2 className="text-sm font-semibold text-zinc-900 mb-3">系统状态</h2>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: 'GPU', value: `${system.gpu_status || '-'} · ${system.gpu_percent ?? '-'}%` },
                { label: '推送成功率', value: system.health.push_rate || '暂无推送' },
                { label: '调度状态', value: (system.health.schedule as string) || '未知' },
                { label: '磁盘', value: system.health.disk_free || '未知' },
              ].map(item => (
                <div key={item.label} className="border border-zinc-100 dark:border-[var(--surface-border)] rounded-lg p-3">
                  <div className="text-[10px] text-zinc-400 font-mono uppercase">{item.label}</div>
                  <div className="mt-1 text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{item.value}</div>
                </div>
              ))}
            </div>
          </section>
          <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-4">
            <h2 className="text-sm font-semibold text-zinc-900 mb-3">快捷操作</h2>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={triggerManualScan} className="flex items-center gap-2 rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 py-3 text-left text-xs font-medium text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-white dark:hover:bg-[var(--surface)] transition">
                <RefreshCw className="h-4 w-4 shrink-0 text-zinc-500 dark:text-[var(--text-muted)]" />
                发起全量检测
              </button>
              <button onClick={() => switchTab('models')} className="flex items-center gap-2 rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 py-3 text-left text-xs font-medium text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-white dark:hover:bg-[var(--surface)] transition">
                <Cpu className="h-4 w-4 shrink-0 text-zinc-500 dark:text-[var(--text-muted)]" />
                查看模型状态
              </button>
              <button onClick={() => switchTab('history')} className="flex items-center gap-2 rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 py-3 text-left text-xs font-medium text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-white dark:hover:bg-[var(--surface)] transition">
                <History className="h-4 w-4 shrink-0 text-zinc-500 dark:text-[var(--text-muted)]" />
                运行日志
              </button>
              <div className="flex items-center gap-2 rounded border border-zinc-100 bg-zinc-50 px-3 py-3 text-xs text-zinc-500">
                <Github className="h-4 w-4 shrink-0 text-zinc-400 dark:text-[var(--text-muted)]" />
                <span className="truncate">{system.publishing?.latest_html_published_at ? `最近发布 ${system.publishing.latest_html_published_at}` : '暂无发布'}</span>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* ── RUNNING state: progress + queue ── */}
      {isRunning && !hasErrors && (
        <>
          <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] border-l-4 border-l-blue-500 bg-white dark:bg-[var(--surface)]">
            <div className="flex items-center justify-between border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-3">
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">当前运行</h2>
            </div>
            <div className="p-4">
              {system.background_task?.running ? (
                <div className="space-y-3">
                  <div className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{system.background_task.message}</div>
                  <div className="text-xs text-zinc-500 dark:text-[var(--text-secondary)]">开始于 {system.background_task.started_at || '刚刚'}</div>
                  {system.background_task.progress && (
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-xs text-zinc-500">
                        <span>{system.background_task.progress.message}</span>
                        <span className="font-mono">{system.background_task.progress.current}/{system.background_task.progress.total}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]">
                        <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.round(system.background_task.progress.current / Math.max(1, system.background_task.progress.total) * 100)}%` }} />
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-3">
                  {activeResearch.slice(0, 2).map(task => (
                    <div key={task.id}>
                      <div className="flex items-center justify-between">
                        <div className="truncate text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{task.target}</div>
                        <span className="shrink-0 text-xs text-blue-700 dark:text-[var(--info)]">{taskStatusLabel(task.status)}</span>
                      </div>
                      <div className="text-xs text-zinc-500 mt-1">研究任务 #{task.id} · {task.completed_items || 0}/{task.total_items || 0}</div>
                      {task.pipeline_stages && <div className="mt-2"><TaskStageCounts stages={task.pipeline_stages} /></div>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          {waitingCount > 0 && (
            <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-600 dark:text-[var(--text-secondary)]">
                  <Clock3 className="mr-1.5 inline h-4 w-4 text-zinc-400" />
                  {waitingCount} 项任务在等待队列中
                </span>
                <span className="text-xs text-zinc-500 dark:text-[var(--text-muted)]">系统将在当前任务完成后自动执行</span>
              </div>
            </section>
          )}
        </>
      )}

      {/* ── ERROR state: failures + alerts ── */}
          {hasErrors && (
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
              {failedVideos.length > 0 && (
            <section className="rounded-lg border border-red-200 dark:border-[var(--danger-border)] bg-white dark:bg-[var(--surface)]">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">待处理失败</h2>
                <span className="rounded bg-red-50 dark:bg-[var(--danger-bg)] px-2 py-1 text-xs font-medium text-red-700 dark:text-[var(--danger)]">{failedVideos.length} 条</span>
              </div>
              <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                {failedVideos.slice(0, 5).map(video => (
                  <div key={video.id} className="px-4 py-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-zinc-900 dark:text-[var(--text-primary)]">{video.title || video.id}</div>
                        <div className="mt-0.5 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{video.blogger} · {video.failed_at_step || video.failure_stage || '未知'}阶段失败</div>
                      </div>
                      <button onClick={() => switchTab('retry')} className="shrink-0 text-xs font-medium text-blue-700 dark:text-[var(--info)] hover:text-blue-900 dark:hover:text-[var(--accent-hover)]">
                        处理
                      </button>
                    </div>
                  </div>
                ))}
                {failedVideos.length > 5 && (
                  <div className="px-4 py-2 text-xs text-zinc-400 dark:text-[var(--text-muted)] text-center">还有 {failedVideos.length - 5} 条</div>
                )}
                <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] px-4 py-2">
                  <button onClick={() => switchTab('retry')} className="text-xs font-medium text-blue-700 dark:text-[var(--info)] hover:text-blue-900 dark:hover:text-[var(--accent-hover)]">
                    查看全部失败 &rarr;
                  </button>
                </div>
              </div>
                </section>
              )}

              {extraAlertCount > 0 && (
                <section className="rounded-lg border border-amber-200 dark:border-[var(--warning-border)] bg-white dark:bg-[var(--surface)]">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">系统告警</h2>
                <span className="rounded bg-amber-50 dark:bg-[var(--warning-bg)] px-2 py-1 text-xs font-medium text-amber-700 dark:text-[var(--warning)]">{extraAlertCount} 条</span>
              </div>
              <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                {alerts.slice(0, 4).map((alert, idx) => (
                  <div key={alert.id || idx} className="px-4 py-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${alert.level === 'critical' ? 'text-red-600' : 'text-amber-500'}`} />
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-zinc-900 dark:text-[var(--text-primary)]">{alert.title}</div>
                        <div className="mt-0.5 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{alert.time}</div>
                      </div>
                    </div>
                  </div>
                ))}
                <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] px-4 py-2">
                  <button onClick={() => switchTab('history')} className="text-xs font-medium text-blue-700 dark:text-[var(--info)] hover:text-blue-900 dark:hover:text-[var(--accent-hover)]">
                    查看全部告警 &rarr;
                  </button>
                </div>
              </div>
            </section>
          )}

          {isRunning && (
            <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-4 py-3">
              <span className="text-sm text-zinc-600 dark:text-[var(--text-secondary)]">
                <Activity className="mr-1.5 inline h-4 w-4 text-blue-500" />
                {runningTaskCount} 个任务仍在运行中
              </span>
            </section>
          )}
        </div>
      )}

      {/* Bottom shortcuts (always visible) */}
      <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <button onClick={() => switchTab('models')} className="flex min-h-14 items-center gap-3 rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 text-left transition hover:bg-white dark:hover:bg-[var(--surface)]">
            <Gauge className="h-4 w-4 shrink-0 text-zinc-500 dark:text-[var(--text-muted)]" />
            <div>
              <div className="text-sm font-medium text-zinc-900 dark:text-[var(--text-primary)]">模型与服务</div>
              <div className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">GPU {system.gpu_status || '未知'} · {system.gpu_percent ?? '-'}%</div>
            </div>
          </button>
          <button onClick={() => switchTab('history')} className="flex min-h-14 items-center gap-3 rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 text-left transition hover:bg-white dark:hover:bg-[var(--surface)]">
            <Terminal className="h-4 w-4 shrink-0 text-zinc-500 dark:text-[var(--text-muted)]" />
            <div className="min-w-0">
              <div className="text-sm font-medium text-zinc-900 dark:text-[var(--text-primary)]">历史记录</div>
              <div className="mt-1 truncate text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{recentLog ? `${recentLog.timestamp} · ${recentLog.message}` : '暂无运行记录'}</div>
            </div>
          </button>
          <div className="flex min-h-14 items-center gap-3 rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3">
            <Github className="h-4 w-4 shrink-0 text-zinc-500 dark:text-[var(--text-muted)]" />
            <div className="min-w-0">
              <div className="text-sm font-medium text-zinc-900 dark:text-[var(--text-primary)]">GitHub 发布</div>
              <div className="mt-1 truncate text-xs text-zinc-500">
                {system.publishing?.latest_html_published_at ? `最近发布 ${system.publishing.latest_html_published_at}` : '暂无发布记录'}
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

/* ── History subtabs ── */
type HistorySubtabs = 'push' | 'alerts' | 'logs';

function HistoryPanel({
  pushRecords,
  logs,
  alerts,
  system,
  rebootWebUI,
  initialSubtab = 'push',
}: {
  pushRecords: PushRecord[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  rebootWebUI: () => void;
  initialSubtab?: HistorySubtabs;
}) {
  const [subtab, setSubtab] = useState<HistorySubtabs>(initialSubtab);
  const [inspectedPushId, setInspectedPushId] = useState<string | null>(null);
  const [logLevelFilter, setLogLevelFilter] = useState<'all' | 'info' | 'warn' | 'error' | 'debug'>('all');
  const [logSearchQuery, setLogSearchQuery] = useState('');

  const filteredLogs = useMemo(() => {
    return logs.filter(l => {
      const matchLevel = logLevelFilter === 'all' || l.level === logLevelFilter;
      const matchSearch = l.message.toLowerCase().includes(logSearchQuery.toLowerCase()) ||
                          l.module.toLowerCase().includes(logSearchQuery.toLowerCase());
      return matchLevel && matchSearch;
    });
  }, [logs, logLevelFilter, logSearchQuery]);

  const runReboot = () => {
    if (window.confirm("确定安全重新运行 Web 端口服务吗？（连接缓存将被短暂冲刷）")) {
      rebootWebUI();
    }
  };

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Subtab navigation */}
      <div className="flex items-center justify-between border-b border-zinc-200 dark:border-[var(--surface-border)]">
        <div className="flex gap-6">
          {[
            { id: 'push' as const, label: '推送记录', icon: Send },
            { id: 'alerts' as const, label: '系统告警', icon: AlertTriangle },
            { id: 'logs' as const, label: '运行日志', icon: Terminal },
          ].map(tab => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setSubtab(tab.id)}
                className={`pb-3 text-sm font-semibold transition relative outline-none cursor-pointer ${
                  subtab === tab.id ? 'text-zinc-950 dark:text-[var(--text-primary)]' : 'text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-700 dark:hover:text-[var(--text-primary)]'
                }`}
              >
                <Icon className="mr-1.5 inline h-3.5 w-3.5" />
                {tab.label}
                {subtab === tab.id && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--text-primary)] rounded" />}
              </button>
            );
          })}
        </div>
        <button
          onClick={runReboot}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 dark:bg-[var(--danger-bg)] text-red-600 dark:text-[var(--danger)] border border-red-100/60 dark:border-[var(--danger-border)] hover:bg-red-100 dark:hover:bg-[var(--danger-bg)] rounded text-xs font-medium transition cursor-pointer"
        >
          <Power className="w-3.5 h-3.5" />
          Web 重启
        </button>
      </div>

      {/* Push records */}
      {subtab === 'push' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-[var(--text-secondary)]">飞书推送日志</h3>
            <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)]">共 {pushRecords.length} 条记录</span>
          </div>
          {pushRecords.length === 0 ? (
            <EmptyState icon={Send} title="暂未保存任何飞书自动推送记录" />
          ) : (
            <div className="border border-zinc-150 dark:border-[var(--surface-border)] rounded-lg overflow-hidden bg-white dark:bg-[var(--surface)]">
              <div className="divide-y divide-zinc-150 dark:divide-[var(--surface-border)]">
                {pushRecords.map(rec => {
                  const isInspected = inspectedPushId === rec.id;
                  return (
                    <div key={rec.id} className="p-4 hover:bg-zinc-50/20 dark:hover:bg-[var(--surface-muted)] transition space-y-3">
                      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
                        <div className="space-y-0.5">
                          <div className="flex items-center space-x-2 flex-wrap">
                            <span className="text-xs font-medium text-purple-600 dark:text-[var(--info)] bg-purple-50 dark:bg-[var(--info-bg)] px-2 py-0.5 rounded">
                              {rec.push_type.toUpperCase()}
                            </span>
                            <span className="text-xs text-zinc-400 font-mono">ID: {rec.id}</span>
                          </div>
                          <h4 className="text-sm font-bold text-zinc-900 leading-snug pt-1">{rec.title}</h4>
                        </div>
                        <div className="flex items-center space-x-3.5 shrink-0">
                          <span className="text-xs text-zinc-400 font-mono">{rec.sent_at}</span>
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                            rec.status === 'success' ? 'text-emerald-600 dark:text-[var(--success)] bg-emerald-50 dark:bg-[var(--success-bg)]' : 'text-red-650 dark:text-[var(--danger)] bg-red-50 dark:bg-[var(--danger-bg)]'
                          }`}>
                            {rec.status === 'success' ? '发送完成' : '发送失败'}
                          </span>
                          <button
                            onClick={() => setInspectedPushId(isInspected ? null : rec.id)}
                            className="p-1 text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-900 dark:hover:text-[var(--text-primary)] transition flex items-center space-x-1 text-xs"
                          >
                            <Eye className="w-3.5 h-3.5" />
                            <span>{isInspected ? '隐藏' : '检视'}</span>
                          </button>
                        </div>
                      </div>
                      {isInspected && (
                        <div className="bg-zinc-950 rounded-md p-4 border border-zinc-800 font-mono text-zinc-350 dark:text-zinc-200 text-[11px] leading-relaxed relative overflow-x-auto whitespace-pre-wrap animate-fade-in max-h-60">
                          <button
                            onClick={() => { navigator.clipboard.writeText(rec.payload); alert("Payload 已复制。"); }}
                            className="absolute right-3 top-3 p-1.5 bg-zinc-900 hover:bg-zinc-850 dark:bg-zinc-900 dark:hover:bg-zinc-850 border border-zinc-800 dark:border-zinc-700 text-zinc-400 dark:text-zinc-300 hover:text-white dark:hover:text-zinc-100 rounded"
                            title="复制 Payload"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                          {rec.payload}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Alerts */}
      {subtab === 'alerts' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-[var(--text-secondary)]">系统告警</h3>
            <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)]">抓取、转录、飞书推送相关故障</span>
          </div>
          {alerts.length === 0 ? (
            <EmptyState icon={CheckCircle2} title="暂无系统告警" description="当前没有需要处理的系统告警记录。" />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {alerts.map((alt, index) => (
                <div key={index} className={`p-5 rounded-lg border flex items-start space-x-4 ${
                  alt.level === 'critical' ? 'bg-red-50/30 dark:bg-[var(--danger-bg)] border-red-150 dark:border-[var(--danger-border)] text-red-950 dark:text-[var(--danger)]' : 'bg-amber-50/20 dark:bg-[var(--warning-bg)] border-amber-150 dark:border-[var(--warning-border)] text-amber-950 dark:text-[var(--warning)]'
                }`}>
                  <AlertTriangle className={`w-5 h-5 mt-0.5 shrink-0 ${alt.level === 'critical' ? 'text-red-600' : 'text-amber-500'}`} />
                  <div className="space-y-1.5">
                    <div className="flex items-center space-x-2.5">
                      <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-black uppercase ${
                        alt.level === 'critical' ? 'bg-red-100 dark:bg-[var(--danger-bg)] text-red-700 dark:text-[var(--danger)]' : 'bg-amber-100 dark:bg-[var(--warning-bg)] text-amber-700 dark:text-[var(--warning)]'
                      }`}>
                        {alt.level === 'critical' ? '严重' : '警告'}
                      </span>
                      <span className="text-xs text-zinc-400 font-mono">模块：[{alt.module}]</span>
                    </div>
                    <h4 className="font-semibold text-sm text-zinc-900 leading-snug">{alt.title}</h4>
                    <p className="text-xs text-zinc-500 font-medium leading-relaxed">{alt.desc}</p>
                    <span className="text-[10px] text-zinc-400 font-mono block">{alt.time}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Logs */}
      {subtab === 'logs' && (
        <div className="space-y-4">
          <div className="p-4 bg-zinc-50 dark:bg-[var(--surface-muted)] border border-zinc-150 dark:border-[var(--surface-border)] rounded-lg flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center space-x-2">
              <span className="text-xs font-mono text-zinc-400 dark:text-[var(--text-muted)]">日志等级:</span>
              <div className="flex border border-zinc-205 dark:border-[var(--surface-border)] p-0.5 rounded bg-white dark:bg-[var(--surface)]">
                {['all', 'info', 'warn', 'error'].map(l => (
                  <button
                    key={l}
                    onClick={() => setLogLevelFilter(l as any)}
                    className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded-sm transition cursor-pointer ${
                      logLevelFilter === l ? 'bg-zinc-900 dark:bg-[var(--text-primary)] dark:text-zinc-950' : 'text-zinc-500 dark:text-[var(--text-muted)] hover:text-zinc-905 dark:hover:text-[var(--text-primary)]'
                    }`}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-zinc-400 dark:text-[var(--text-muted)]" />
              <input
                type="text"
                placeholder="检索日志..."
                value={logSearchQuery}
                onChange={e => setLogSearchQuery(e.target.value)}
                className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-250 dark:border-[var(--surface-border)] rounded pl-8 pr-3 py-1.5 text-xs font-mono focus:outline-none focus:border-zinc-900 dark:focus:border-[var(--text-primary)]"
              />
            </div>
          </div>

          <div className="p-5 rounded-lg bg-zinc-950 dark:bg-[var(--surface)] border border-zinc-850 dark:border-[var(--surface-border)] shadow-inner h-[500px] overflow-y-auto flex flex-col-reverse justify-end font-mono text-xs text-zinc-300 dark:text-zinc-300 leading-relaxed select-text">
            {filteredLogs.length === 0 ? (
              <div className="py-20 text-center font-zinc-500 dark:text-zinc-500 font-mono space-y-1 select-none">
                <Terminal className="w-8 h-8 mx-auto text-zinc-700 dark:text-zinc-600 stroke-1 mb-2" />
                <p>--- 未匹配到日志 ---</p>
                <p className="text-[10px]">调整筛选条件或触发全量检测</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                {filteredLogs.map(log => (
                  <div key={log.id} className="hover:bg-zinc-900/40 dark:hover:bg-[var(--surface-muted)] p-1 rounded font-mono flex items-start space-x-2 justify-between">
                    <div className="flex-1">
                      <span className="text-zinc-500 dark:text-zinc-500 mr-2.5">[{log.timestamp}]</span>
                      <span className={`font-bold mr-2 ${
                        log.level === 'info' ? 'text-emerald-400' :
                        log.level === 'warn' ? 'text-amber-400' : 'text-red-500'
                      }`}>
                        [{log.level.toUpperCase()}]
                      </span>
                      <span className="text-blue-400 dark:text-[var(--info)] mr-2">[{log.module}]</span>
                      <span className="text-zinc-200 dark:text-[var(--text-primary)]">{log.message}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] text-center font-mono">
            * 默认展示最近 300 条日志。完整日志路径：{system.log_path}
          </div>
        </div>
      )}
    </div>
  );
}

function stateBannerClass(state: ReturnType<typeof buildRunCenterModel>['state']) {
  if (state === 'needs_repair') return 'border-amber-200 dark:border-[var(--warning-border)] bg-amber-50/70 dark:bg-[var(--warning-bg)] text-amber-950 dark:text-[var(--warning)]';
  if (state === 'running') return 'border-blue-200 dark:border-[var(--info-border)] bg-blue-50/70 dark:bg-[var(--info-bg)] text-blue-950 dark:text-[var(--info)]';
  return 'border-emerald-200 dark:border-[var(--success-border)] bg-emerald-50/60 dark:bg-[var(--success-bg)] text-emerald-950 dark:text-[var(--success)]';
}

function StateIcon({ state }: { state: ReturnType<typeof buildRunCenterModel>['state'] }) {
  if (state === 'needs_repair') return <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600 dark:text-[var(--warning)]" />;
  if (state === 'running') return <Activity className="mt-0.5 h-5 w-5 shrink-0 text-blue-600 dark:text-[var(--info)]" />;
  return <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600 dark:text-[var(--success)]" />;
}

function StateBanner({
  model,
  triggerManualScan,
}: {
  model: ReturnType<typeof buildRunCenterModel>;
  triggerManualScan: () => void;
}) {
  return (
    <section className={`overflow-hidden rounded-lg border ${stateBannerClass(model.state)}`}>
      <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-start gap-3">
          <StateIcon state={model.state} />
          <div>
            <h2 className="text-sm font-semibold">{model.bannerTitle}</h2>
            <p className="mt-1 text-xs leading-5 opacity-80">{model.bannerText}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={triggerManualScan}
          className="inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-white/80 dark:border-[var(--surface-border)]/50 bg-white/80 dark:bg-[var(--surface)]/80 px-3 text-xs font-medium text-zinc-800 dark:text-[var(--text-primary)] transition hover:bg-white dark:hover:bg-[var(--surface-muted)] cursor-pointer"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          手动检测
        </button>
      </div>
      <div className="grid grid-cols-2 border-t border-current/10 md:grid-cols-5">
        {[
          ['进行中', `${model.counts.running} 项`],
          ['等待', `${model.counts.waiting} 项`],
          ['待修复', `${model.counts.repair} 项`],
          ['降级归档', `${model.counts.degraded} 条`],
          ['下次运行', model.nextRun],
        ].map(([label, value]) => (
          <div key={label} className="border-r border-current/10 px-4 py-3 last:border-r-0">
            <div className="text-[11px] opacity-60">{label}</div>
            <div className="mt-1 truncate text-sm font-semibold tabular-nums" title={String(value)}>{value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function RepairWindow({
  model,
  alerts,
  retryStage,
  bulkRetryFailed,
  navigateTo,
}: {
  model: ReturnType<typeof buildRunCenterModel>;
  alerts: AlertRecord[];
  retryStage: (id: string, stage?: RetryStage) => void;
  bulkRetryFailed: (step?: RetryStage) => void;
  navigateTo: (page: string, id: string | null) => void;
}) {
  if (model.failedVideos.length === 0) return null;

  return (
    <section className="rounded-lg border border-amber-200 dark:border-[var(--warning-border)] bg-white dark:bg-[var(--surface)]">
      <div className="flex flex-col gap-3 border-b border-amber-100 dark:border-[var(--warning-border)] bg-amber-50/60 dark:bg-[var(--warning-bg)] px-4 py-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold text-amber-950 dark:text-[var(--warning)]">
            <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-[var(--warning)]" />
            修复窗口
          </h2>
          <p className="mt-1 text-xs text-amber-800 dark:text-[var(--warning)]">
            默认使用自动修复，系统会按现有全流程重试逻辑判断恢复起点。
          </p>
        </div>
        {model.failedVideos.length > 0 && (
          <button
            type="button"
            onClick={() => window.confirm(`确认自动修复全部 ${model.failedVideos.length} 条失败内容？系统会从判断出的失败阶段重新执行。`) && bulkRetryFailed()}
            className="inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md bg-zinc-950 dark:bg-[var(--surface)] px-3 text-xs font-medium text-white dark:text-[var(--text-primary)] hover:bg-zinc-800 dark:hover:bg-[var(--surface-border)] cursor-pointer"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            自动修复全部失败
          </button>
        )}
      </div>

      {model.failureGroups.length > 0 && (
        <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
          {model.failureGroups.map(group => (
            <div key={group.key} className="px-4 py-4">
              <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-2">
                  <span className="rounded border border-amber-100 dark:border-[var(--warning-border)] bg-amber-50 dark:bg-[var(--warning-bg)] px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-[var(--warning)]">
                    {group.label}
                  </span>
                  <span className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{group.items.length} 条待修复</span>
                </div>
                {group.key !== 'other' && (
                  <details className="group">
                    <summary className="cursor-pointer list-none text-xs font-medium text-zinc-500 dark:text-[var(--text-muted)] hover:text-zinc-800 dark:hover:text-[var(--text-primary)]">
                      高级重试
                    </summary>
                    <div className="mt-2 flex justify-end">
                      <button
                        type="button"
                        onClick={() => window.confirm(`确认从${failedStageLabel(group.key)}阶段批量重试 ${group.items.length} 条内容？`) && bulkRetryFailed(group.key as RetryStage)}
                        className="inline-flex min-h-8 items-center gap-1.5 rounded border border-zinc-200 dark:border-[var(--surface-border)] px-2.5 text-xs font-medium text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] cursor-pointer"
                      >
                        <RotateCw className="h-3.5 w-3.5" />
                        从{failedStageLabel(group.key)}批量重试
                      </button>
                    </div>
                  </details>
                )}
              </div>
              <div className="space-y-2">
                {group.items.slice(0, 8).map(video => {
                  const stage = failedStage(video);
                  return (
                    <div key={video.id} className="rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-zinc-50/50 dark:bg-[var(--surface-muted)] p-3">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                            <span>{video.blogger || '未知来源'}</span>
                            <span className="font-mono">ID {video.id}</span>
                            <span>{video.failed_at || video.updated_at || video.created_at || ''}</span>
                          </div>
                          <h3 className="mt-1 truncate text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)]" title={video.title}>
                            {video.title || '无标题'}
                          </h3>
                          <p className="mt-1 line-clamp-2 break-all font-mono text-[11px] leading-5 text-zinc-500 dark:text-[var(--text-secondary)]">
                            {video.error_message || '暂无错误摘要。'}
                          </p>
                        </div>
                        <div className="flex shrink-0 flex-wrap gap-2">
                          <button
                            type="button"
                            onClick={() => retryStage(video.id)}
                            className="inline-flex min-h-9 items-center gap-1.5 rounded bg-zinc-950 dark:bg-[var(--surface)] px-3 text-xs font-medium text-white dark:text-[var(--text-primary)] hover:bg-zinc-800 dark:hover:bg-[var(--surface-border)] cursor-pointer"
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                            自动修复
                          </button>
                          <details className="relative">
                            <summary className="inline-flex min-h-9 cursor-pointer list-none items-center gap-1.5 rounded border border-zinc-200 dark:border-[var(--surface-border)] px-3 text-xs font-medium text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-white dark:hover:bg-[var(--surface-muted)]">
                              高级
                            </summary>
                            <div className="absolute right-0 z-10 mt-2 w-44 rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-2 shadow-lg">
                              <button
                                type="button"
                                onClick={() => retryStage(video.id, stage)}
                                className="block w-full rounded px-2 py-2 text-left text-xs text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] disabled:cursor-not-allowed disabled:opacity-50"
                                disabled={!stage}
                              >
                                从失败阶段重试
                              </button>
                              <button
                                type="button"
                                onClick={() => retryStage(video.id, 'download')}
                                className="block w-full rounded px-2 py-2 text-left text-xs text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]"
                              >
                                从下载重试
                              </button>
                            </div>
                          </details>
                          <button
                            type="button"
                            onClick={() => navigateTo('detail', video.id)}
                            className="inline-flex min-h-9 items-center gap-1.5 rounded border border-zinc-200 dark:border-[var(--surface-border)] px-3 text-xs font-medium text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-white dark:hover:bg-[var(--surface-muted)] cursor-pointer"
                          >
                            <Eye className="h-3.5 w-3.5" />
                            详情
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
                {group.items.length > 8 && (
                  <div className="rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 py-2 text-center text-xs text-zinc-500 dark:text-[var(--text-muted)]">
                    还有 {group.items.length - 8} 条同阶段失败，建议先使用批量自动修复。
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

    </section>
  );
}

function SupportingDetails({
  pushRecords,
  logs,
  alerts,
  system,
  config,
  rebootWebUI,
  initialSubtab,
}: {
  pushRecords: PushRecord[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  config: SystemConfig;
  rebootWebUI: () => void;
  initialSubtab?: HistorySubtabs;
}) {
  return (
    <section className="space-y-3">
      <details open={Boolean(initialSubtab)} className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
        <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between px-4 text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">
          <span className="inline-flex items-center gap-2">
            <History className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />
            发布、告警与日志
          </span>
          <span className="text-xs font-normal text-zinc-500 dark:text-[var(--text-muted)]">辅助排查</span>
        </summary>
        <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] p-4">
          <HistoryPanel
            pushRecords={pushRecords}
            logs={logs}
            alerts={alerts}
            system={system}
            rebootWebUI={rebootWebUI}
            initialSubtab={initialSubtab}
          />
        </div>
      </details>

      <details className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
        <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between px-4 text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">
          <span className="inline-flex items-center gap-2">
            <Cpu className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />
            模型与 GPU
          </span>
          <span className="text-xs font-normal text-zinc-500 dark:text-[var(--text-muted)]">GPU {system.gpu_status || '未知'} · {system.gpu_percent ?? '-'}%</span>
        </summary>
        <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] p-4">
          <ModelGpuPanel system={system} config={config} />
        </div>
      </details>
    </section>
  );
}

/* ── Main RunCenter ── */
export default function RunCenter({
  videos,
  tasks,
  retryStage,
  bulkRetryFailed,
  retryResearchFailed,
  navigateTo,
  pushRecords,
  logs,
  alerts,
  system,
  config,
  rebootWebUI,
  triggerManualScan,
}: RunCenterProps) {
  const model = useMemo(() => buildRunCenterModel({ videos, tasks, system, alerts }), [videos, tasks, system, alerts]);
  const initialSubtab = useMemo<HistorySubtabs | undefined>(() => runCenterSectionFromLocation(window.location.pathname, window.location.search), []);

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900 dark:text-[var(--text-primary)]">处理中心</h1>
          <p className="text-zinc-500 text-sm mt-1">按任务查看后台进度，快速定位卡点并从失败阶段启动修复。</p>
        </div>
      </div>

      <StateBanner model={model} triggerManualScan={triggerManualScan} />
      {(system.background_task?.running || normalizeRuntimeTimeline(system.runtime_timeline)?.entries?.length > 0) && (
        <RunTimelinePanel system={system} logs={logs} />
      )}
      <RepairWindow
        model={model}
        alerts={alerts}
        retryStage={retryStage}
        bulkRetryFailed={bulkRetryFailed}
        navigateTo={navigateTo}
      />
      <TaskCommandList taskViews={model.taskViews} system={system} logs={logs} onRepair={taskId => window.confirm(`确认重试任务 #${taskId} 中的失败条目？`) && retryResearchFailed(taskId)} />
      <SupportingDetails
        pushRecords={pushRecords}
        logs={logs}
        alerts={alerts}
        system={system}
        config={config}
        rebootWebUI={rebootWebUI}
        initialSubtab={initialSubtab}
      />
    </div>
  );
}
