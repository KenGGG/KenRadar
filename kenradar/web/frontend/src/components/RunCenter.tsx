/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Cpu,
  Gauge,
  Github,
  ListChecks,
  RefreshCw,
  Send,
  Server,
  Terminal,
} from 'lucide-react';
import ContentWorkbench from './ContentWorkbench';
import SystemMonitor, { SystemMonitorTab } from './SystemMonitor';
import { TaskProgressBar, TaskStageCounts, taskStatusClass, taskStatusLabel } from './TaskProgress';
import { AlertRecord, PushRecord, ResearchTask, SystemConfig, SystemInfo, SystemLog, VideoContent } from '../types';

type RunTab = 'overview' | 'queue' | 'retry' | 'models' | 'push' | 'alerts' | 'logs';

interface RunCenterProps {
  videos: VideoContent[];
  tasks: ResearchTask[];
  retryStage: (id: string, stage?: 'download' | 'transcribe' | 'ai' | 'push') => void;
  bulkRetryFailed: (step?: 'download' | 'transcribe' | 'ai' | 'push') => void;
  navigateTo: (page: string, id: string | null) => void;
  pushRecords: PushRecord[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  config: SystemConfig;
  rebootWebUI: () => void;
  triggerManualScan: () => void;
}

function RunTaskBoard({
  tasks,
  system,
}: {
  tasks: ResearchTask[];
  system: SystemInfo;
}) {
  const queuedBackground = system.background_task?.queue || [];
  const activeTasks = tasks
    .filter(task => task.status === 'processing' || task.status === 'paused')
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const queuedTasks = tasks
    .filter(task => task.status === 'queued')
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
  const recentCompleted = tasks
    .filter(task => task.status === 'completed')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 5);

  return (
    <section className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ['后台排队', queuedBackground.length + queuedTasks.length, '等待取得执行资源'],
          ['进行中', activeTasks.length + (system.background_task?.running ? 1 : 0), '正在处理的批次'],
          ['失败待处理', tasks.filter(task => task.status === 'failed').length, '保留在失败重试'],
          ['最近完成', recentCompleted.length, '当前展示最近 5 项'],
        ].map(([label, value, detail]) => (
          <div key={String(label)} className="rounded-lg border border-zinc-200 bg-white p-4">
            <div className="text-xs text-zinc-500">{label}</div>
            <div className="mt-1 text-xl font-semibold tabular-nums text-zinc-950">{value}</div>
            <div className="mt-1 text-[11px] text-zinc-400">{detail}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-lg border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-zinc-900">当前执行</h2>
            <p className="mt-1 text-xs text-zinc-500">研究批次按作品逐条流转，转录成功后立即进入 AI 整理。</p>
          </div>
          <div className="divide-y divide-zinc-100">
            {activeTasks.length === 0 && !system.background_task?.running ? (
              <div className="px-4 py-10 text-center text-sm text-zinc-400">当前没有执行中的任务。</div>
            ) : (
              <>
                {system.background_task?.running && (
                  <div className="space-y-3 px-4 py-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-zinc-900">{system.background_task.message}</div>
                        <div className="mt-1 text-xs text-zinc-500">后台执行器 · {system.background_task.started_at || '刚刚开始'}</div>
                      </div>
                      <span className="shrink-0 rounded border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">进行中</span>
                    </div>
                    {system.background_task.progress && (
                      <div className="space-y-1.5">
                        <div className="flex justify-between text-xs text-zinc-500">
                          <span className="truncate">{system.background_task.progress.message}</span>
                          <span className="font-mono tabular-nums">{system.background_task.progress.current}/{system.background_task.progress.total}</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100">
                          <div
                            className="h-full rounded-full bg-blue-600"
                            style={{ width: `${Math.round(system.background_task.progress.current / Math.max(1, system.background_task.progress.total) * 100)}%` }}
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {activeTasks.map(task => (
                  <div key={task.id} className="space-y-3 px-4 py-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold text-zinc-900">{task.target}</div>
                        <div className="mt-1 text-xs text-zinc-500">研究任务 #{task.id} · 已完成 {task.completed_items || 0}/{task.total_items || 0}</div>
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

        <div className="rounded-lg border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-zinc-900">等待队列</h2>
            <p className="mt-1 text-xs text-zinc-500">按进入队列的先后顺序执行，同一时间只占用允许的资源。</p>
          </div>
          <div className="divide-y divide-zinc-100">
            {queuedBackground.length === 0 && queuedTasks.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-zinc-400">暂无排队任务。</div>
            ) : (
              <>
                {queuedBackground.map(task => (
                  <div key={`${task.position}-${task.task_id}`} className="flex items-center gap-3 px-4 py-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-zinc-200 bg-zinc-50 font-mono text-xs text-zinc-600">{task.position}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-zinc-900">{task.message || task.task_id}</div>
                      <div className="mt-1 text-xs text-zinc-400">{task.queued_at || '等待执行'}</div>
                    </div>
                    <span className="text-xs text-zinc-500">排队中</span>
                  </div>
                ))}
                {queuedTasks.map((task, index) => (
                  <div key={task.id} className="flex items-center gap-3 px-4 py-3">
                    <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-zinc-200 bg-zinc-50 font-mono text-xs text-zinc-600">{queuedBackground.length + index + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-zinc-900">{task.target}</div>
                      <div className="mt-1 text-xs text-zinc-400">研究任务 #{task.id} · {task.created_at}</div>
                    </div>
                    <span className={`text-xs ${taskStatusClass(task.status).split(' ').at(-1)}`}>{taskStatusLabel(task.status)}</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      </div>

      {recentCompleted.length > 0 && (
        <details className="rounded-lg border border-zinc-200 bg-white">
          <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-zinc-800">最近完成任务</summary>
          <div className="divide-y divide-zinc-100 border-t border-zinc-100">
            {recentCompleted.map(task => (
              <div key={task.id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-zinc-900">{task.target}</div>
                  <div className="mt-1 text-xs text-zinc-400">#{task.id} · 成功 {task.completed_items || 0} · 跳过 {task.skipped_items || 0}</div>
                </div>
                <span className="shrink-0 text-xs text-emerald-700">已完成</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

const RUN_TAB_PATHS: Record<RunTab, string> = {
  overview: '/run?tab=overview',
  queue: '/run?tab=queue',
  retry: '/run?tab=retry',
  models: '/run?tab=models',
  push: '/run?tab=push',
  alerts: '/run?tab=alerts',
  logs: '/run?tab=logs',
};

const SYSTEM_TAB_FOR_RUN_TAB: Partial<Record<RunTab, SystemMonitorTab>> = {
  push: 'push',
  alerts: 'alerts',
  logs: 'logs',
};

function runTabFromLocation(): RunTab {
  const pathname = window.location.pathname;
  const params = new URLSearchParams(window.location.search);
  const tab = params.get('tab');
  if (tab === 'queue' || tab === 'retry' || tab === 'models' || tab === 'push' || tab === 'alerts' || tab === 'logs') return tab;
  if (pathname === '/operations/retry' || pathname === '/failures') return 'retry';
  if (pathname.startsWith('/operations')) return 'queue';
  if (pathname === '/logs/pushes' || pathname === '/pushes') return 'push';
  if (pathname === '/logs/alerts') return 'alerts';
  if (pathname === '/logs/runtime') return 'logs';
  return 'overview';
}

function MetricCard({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: React.ReactNode;
  icon: React.ElementType;
}) {
  return (
    <div className="bg-white border border-zinc-200 rounded-lg p-4 shadow-2xs">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] text-zinc-400 font-mono uppercase">{label}</span>
        <Icon className="w-4 h-4 text-zinc-400" />
      </div>
      <div className="text-sm font-sans font-semibold text-zinc-900 break-words">{value}</div>
    </div>
  );
}

function ModelGpuPanel({ system, config }: { system: SystemInfo; config: SystemConfig }) {
  const gpuPercent = Math.max(0, Math.min(100, Number(system.gpu_percent ?? 0)));
  const whisperDevice = config.whisper?.device || (config.whisper?.use_gpu ? 'cuda' : 'cpu');
  const aiModel = config.ai?.model || 'agnes-2.0-flash';
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
    <div className="space-y-6 animate-fade-in">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <MetricCard label="GPU 状态" value={system.gpu_status || '未知'} icon={Activity} />
        <MetricCard label="GPU 占用" value={`${system.gpu_label || 'GPU'} · ${system.gpu_percent ?? '-'}%`} icon={Gauge} />
        <MetricCard label="转录模型" value={`${system.whisper_model || config.whisper?.model || 'large-v3-turbo'} · ${whisperDevice}`} icon={RefreshCw} />
        <MetricCard label="AI 模型" value={aiModel} icon={Cpu} />
      </div>

      <div className="bg-white border border-zinc-200 rounded-lg p-5 shadow-2xs space-y-5">
        <div>
          <h3 className="text-sm font-semibold text-zinc-900">模型与 GPU 调度</h3>
          <p className="text-xs text-zinc-500 mt-1">查看 FunASR、Whisper、Agnes AI 主引擎和 Ollama 后备引擎的关键配置。</p>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs font-mono text-zinc-500">
            <span>{system.gpu_label || 'GPU 调度'}</span>
            <span>{gpuPercent}%</span>
          </div>
          <div className="h-2 w-full bg-zinc-150 rounded-full overflow-hidden">
            <div className="h-full bg-green-500 rounded-full transition-all" style={{ width: `${gpuPercent}%` }} />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          {services.map(service => (
            <div key={service.name} className="rounded-lg border border-zinc-200 bg-zinc-50 p-4 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold text-zinc-900">{service.name}</div>
                <span className={`rounded px-2 py-0.5 text-[10px] font-semibold ${
                  service.tone === 'green' ? 'bg-emerald-50 text-emerald-700' :
                  service.tone === 'blue' ? 'bg-blue-50 text-blue-700' : 'bg-white text-zinc-600'
                }`}>{service.status}</span>
              </div>
              <div className="font-mono text-zinc-500 break-all">{service.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function healthTone(failedCount: number, alertCount: number, runningCount: number) {
  if (alertCount > 0 || failedCount > 0) return { label: '需要处理', className: 'border-amber-150 bg-amber-50/60 text-amber-900', icon: AlertTriangle };
  if (runningCount > 0) return { label: '运行中', className: 'border-blue-150 bg-blue-50/60 text-blue-900', icon: Activity };
  return { label: '正常', className: 'border-emerald-150 bg-emerald-50/50 text-emerald-900', icon: CheckCircle2 };
}

function RunOverviewPanel({
  videos,
  logs,
  alerts,
  system,
  config,
  triggerManualScan,
  switchTab,
}: {
  videos: VideoContent[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  config: SystemConfig;
  triggerManualScan: () => void;
  switchTab: (tab: RunTab) => void;
}) {
  const runningVideos = videos.filter(video => video.status === 'processing');
  const failedVideos = videos.filter(video => video.status === 'failed');
  const queuedTasks = system.background_task?.queue || [];
  const alertCount = Number(system.health?.alert_attention || 0);
  const runningMessage = system.background_task?.running ? system.background_task.message : (runningVideos[0]?.title || '暂无后台任务');
  const activeRunCount = runningVideos.length + queuedTasks.length + (system.background_task?.running ? 1 : 0);
  const tone = healthTone(failedVideos.length, alertCount, activeRunCount);
  const HealthIcon = tone.icon;
  const recentLog = logs[0];
  const gpuPercent = system.gpu_percent ?? '-';
  const primaryAiStatus = config.ai?.endpoint ? `${config.ai.model || 'Agnes AI'} · 已配置` : '未配置';
  const nextAction = failedVideos.length > 0
    ? { label: `处理 ${failedVideos.length} 条失败内容`, tab: 'retry' as RunTab }
    : alertCount > 0
      ? { label: `查看 ${alertCount} 条系统告警`, tab: 'alerts' as RunTab }
      : system.background_task?.running || runningVideos.length > 0 || queuedTasks.length > 0
        ? { label: '查看处理队列', tab: 'queue' as RunTab }
        : { label: '发起手动检测', tab: null };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className={`rounded-lg border p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3 ${tone.className}`}>
        <div className="flex items-start gap-3">
          <HealthIcon className="w-5 h-5 mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-semibold">系统现在：{tone.label}</div>
            <p className="mt-1 text-xs leading-5 opacity-80">
              {failedVideos.length > 0 || alertCount > 0
                ? '有异常需要先处理，建议从失败重试或系统告警进入。'
                : system.background_task?.running
                  ? '后台任务正在执行，先观察当前运行进度。'
                  : queuedTasks.length > 0
                    ? '后台队列中已有任务等待执行。'
                    : '当前没有正在执行或等待执行的后台任务，可以等待定时调度或手动检测。'}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => nextAction.tab ? switchTab(nextAction.tab) : triggerManualScan()}
          className="inline-flex items-center justify-center gap-1.5 rounded-md bg-white/80 px-3 py-2 text-xs font-semibold text-zinc-800 border border-white/80 hover:bg-white"
        >
          {nextAction.label}
        </button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-6 gap-3">
        <MetricCard label="调度状态" value={system.health.schedule || '未知'} icon={Activity} />
        <MetricCard label="当前任务" value={runningMessage} icon={ListChecks} />
        <MetricCard label="失败待处理" value={`${failedVideos.length} 条`} icon={AlertTriangle} />
        <MetricCard label="下次运行" value={system.health.next_run || '暂无'} icon={Clock3} />
        <MetricCard label="GPU 状态" value={`${system.gpu_status || '未知'} · ${gpuPercent}%`} icon={Gauge} />
        <MetricCard label="AI 主引擎" value={primaryAiStatus} icon={Server} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        <section className="rounded-lg border border-zinc-200 bg-white p-5 space-y-4 border-l-4 border-l-blue-500">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">当前运行</h2>
            <p className="text-xs text-zinc-500 mt-1">只展示正在执行或排队中的关键任务。</p>
          </div>
          {system.background_task?.running ? (
            <div className="rounded-lg bg-blue-50/70 border border-blue-100 p-4 space-y-2">
              <div className="text-sm font-semibold text-blue-950">{system.background_task.message}</div>
              <div className="text-xs font-mono text-blue-700">开始于 {system.background_task.started_at || '-'}</div>
              {system.background_task.progress && (
                <div className="space-y-1.5">
                  <div className="flex justify-between text-[11px] font-mono text-blue-700">
                    <span>{system.background_task.progress.message}</span>
                    <span>{system.background_task.progress.current}/{system.background_task.progress.total}</span>
                  </div>
                  <div className="h-2 rounded-full bg-blue-200 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-blue-600"
                      style={{ width: `${Math.round((system.background_task.progress.current / Math.max(1, system.background_task.progress.total)) * 100)}%` }}
                    />
                  </div>
                </div>
              )}
            </div>
          ) : queuedTasks.length > 0 ? (
            <div className="space-y-2">
              {queuedTasks.slice(0, 4).map(task => (
                <button key={`${task.position}-${task.task_id}`} onClick={() => switchTab('queue')} className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-left hover:bg-white">
                  <div className="line-clamp-1 text-sm font-medium text-zinc-900">{task.message || task.task_id}</div>
                  <div className="mt-1 text-xs text-zinc-500">队列第 {task.position} 位 · {task.queued_at || '等待执行'}</div>
                </button>
              ))}
            </div>
          ) : runningVideos.length > 0 ? (
            <div className="space-y-2">
              {runningVideos.slice(0, 4).map(video => (
                <button key={video.id} onClick={() => switchTab('queue')} className="w-full rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 text-left hover:bg-white">
                  <div className="line-clamp-1 text-sm font-medium text-zinc-900">{video.title || video.id}</div>
                  <div className="mt-1 text-xs text-zinc-500">处理中 · {video.blogger || '未知来源'}</div>
                </button>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-zinc-200 p-8 text-center text-sm text-zinc-500">暂无正在执行或等待执行的后台任务。</div>
          )}
        </section>

        <section className="rounded-lg border border-zinc-200 bg-white p-5 space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">待处理异常</h2>
            <p className="text-xs text-zinc-500 mt-1">失败内容和系统告警会优先出现在这里。</p>
          </div>
          {failedVideos.length === 0 && alertCount === 0 ? (
            <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-5 text-sm text-emerald-800 flex gap-2">
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
              <span>暂无待处理异常。</span>
            </div>
          ) : (
            <div className="space-y-2">
              {failedVideos.slice(0, 3).map(video => (
                <button key={video.id} onClick={() => switchTab('retry')} className="w-full rounded-lg border border-red-100 bg-red-50/50 px-3 py-2 text-left hover:bg-red-50">
                  <div className="text-xs font-semibold text-red-700">{video.failed_at_step || video.failure_stage || 'unknown'} 阶段失败</div>
                  <div className="mt-1 line-clamp-1 text-sm font-medium text-zinc-900">{video.title || video.id}</div>
                  <div className="mt-1 line-clamp-1 text-xs font-mono text-zinc-500">{video.error_message || '暂无错误摘要'}</div>
                </button>
              ))}
              {alertCount > 0 && (
                <button onClick={() => switchTab('alerts')} className="w-full rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2 text-left text-sm font-medium text-amber-900">
                  还有 {alertCount} 条系统告警需要查看
                </button>
              )}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-zinc-200 bg-white p-5 space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">模型与服务状态</h2>
            <p className="text-xs text-zinc-500 mt-1">概览转录、AI 和 GPU 服务是否处于可用配置。</p>
          </div>
          {[
            ['FunASR', '优先转录', '配置启用'],
            ['Whisper', system.whisper_model || config.whisper?.model || 'large-v3-turbo', `转录后备 · ${config.whisper?.device || 'cpu'}`],
            ['Agnes AI', config.ai?.model || 'agnes-2.0-flash', config.ai?.endpoint || '未配置 endpoint'],
            ['Ollama', '本地 AI 整理后备', (config.ai?.fallback_enabled ?? true) ? config.ai?.fallback_endpoint || 'http://127.0.0.1:11434/v1' : '未启用'],
            ['GPU', system.gpu_label || 'GPU 调度', `${system.gpu_status || '未知'} · ${gpuPercent}%`],
          ].map(([name, desc, status]) => (
            <div key={name} className="flex items-center justify-between gap-3 rounded border border-zinc-100 bg-zinc-50 px-3 py-2">
              <div>
                <div className="text-sm font-medium text-zinc-900">{name}</div>
                <div className="text-xs text-zinc-500">{desc}</div>
              </div>
              <div className="max-w-[12rem] truncate text-right text-xs font-mono text-zinc-600" title={status}>{status}</div>
            </div>
          ))}
          <button onClick={() => switchTab('models')} className="text-xs font-semibold text-blue-700 hover:text-blue-900">查看模型与 GPU 详情</button>
        </section>
      </div>

      <section className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">最近运行摘要</h2>
            <p className="mt-1 text-xs text-zinc-500">
              {recentLog ? `${recentLog.timestamp} · [${recentLog.level.toUpperCase()}] [${recentLog.module}] ${recentLog.message}` : '暂无运行记录。'}
            </p>
          </div>
          <button onClick={() => switchTab('logs')} className="text-xs font-semibold text-zinc-600 hover:text-zinc-950">查看运行日志</button>
        </div>
      </section>

      <section className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div className="flex items-start gap-3">
            <Github className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" />
            <div>
              <h2 className="text-sm font-semibold text-zinc-900">GitHub 发布状态</h2>
              <p className="mt-1 text-xs leading-5 text-zinc-500">
                {system.publishing?.latest_html_published_at
                  ? `最近 HTML 发布时间：${system.publishing.latest_html_published_at}`
                  : '暂无 HTML 发布记录。'}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            <span className={`rounded border px-2.5 py-1.5 ${system.publishing?.docs_exists ? 'border-emerald-100 bg-emerald-50 text-emerald-700' : 'border-zinc-200 bg-zinc-50 text-zinc-500'}`}>
              docs {system.publishing?.docs_exists ? '存在' : '未生成'}
            </span>
            <span className={`rounded border px-2.5 py-1.5 ${system.publishing?.github_pages_public_base_url_configured ? 'border-emerald-100 bg-emerald-50 text-emerald-700' : 'border-amber-100 bg-amber-50 text-amber-700'}`}>
              Pages URL {system.publishing?.github_pages_public_base_url_configured ? '已配置' : '未配置'}
            </span>
            <span className={`rounded border px-2.5 py-1.5 ${system.publishing?.github_sync_enabled ? 'border-blue-100 bg-blue-50 text-blue-700' : 'border-zinc-200 bg-zinc-50 text-zinc-500'}`}>
              Sync {system.publishing?.github_sync_enabled ? '启用' : '关闭'}
            </span>
            <span className="rounded border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 text-zinc-500">
              最近同步 {system.publishing?.last_sync?.synced_at || '暂无'}
            </span>
          </div>
        </div>
      </section>
    </div>
  );
}

export default function RunCenter({
  videos,
  tasks,
  retryStage,
  bulkRetryFailed,
  navigateTo,
  pushRecords,
  logs,
  alerts,
  system,
  config,
  rebootWebUI,
  triggerManualScan,
}: RunCenterProps) {
  const [activeTab, setActiveTab] = useState<RunTab>(() => runTabFromLocation());

  const failedCount = videos.filter(video => video.status === 'failed').length;
  const alertCount = Number(system.health?.alert_attention || 0);

  const tabs = useMemo(() => [
    { id: 'overview' as const, label: '运行概览', icon: Activity },
    { id: 'queue' as const, label: '处理队列', icon: ListChecks },
    { id: 'retry' as const, label: '失败重试', icon: AlertTriangle, count: failedCount },
    { id: 'models' as const, label: '模型与GPU', icon: Cpu },
    { id: 'push' as const, label: '推送记录', icon: Send },
    { id: 'alerts' as const, label: '系统告警', icon: AlertTriangle, count: alertCount },
    { id: 'logs' as const, label: '运行日志', icon: Terminal },
  ], [alertCount, failedCount]);

  const switchTab = (tab: RunTab) => {
    setActiveTab(tab);
    window.history.pushState(null, '', RUN_TAB_PATHS[tab]);
  };

  const systemTab = SYSTEM_TAB_FOR_RUN_TAB[activeTab];

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="border-b border-zinc-200 pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900">运行中心</h1>
          <p className="text-zinc-500 font-sans text-sm mt-1">集中查看处理队列、模型 GPU、推送记录、系统告警和运行日志。</p>
        </div>
        <button
          onClick={() => {
            triggerManualScan();
            alert('手动检测任务已加入后台队列。');
          }}
          className="flex items-center gap-1.5 px-3 py-2 border border-zinc-200 hover:bg-zinc-50 rounded text-xs font-sans font-medium text-zinc-700 transition cursor-pointer"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>手动全量检测</span>
        </button>
      </div>

      <div className="flex flex-wrap border-b border-zinc-200 gap-x-5 gap-y-2">
        {tabs.map(tab => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => switchTab(tab.id)}
              className={`pb-3 inline-flex items-center gap-1.5 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
                active ? 'text-zinc-950' : 'text-zinc-400 hover:text-zinc-700'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
              {Boolean(tab.count) && <span className="rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] text-red-700">{tab.count}</span>}
              {active && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 rounded" />}
            </button>
          );
        })}
      </div>

      {activeTab === 'queue' && (
        <div className="space-y-6">
          <RunTaskBoard tasks={tasks} system={system} />
          <div className="border-t border-zinc-200 pt-6">
            <ContentWorkbench
              videos={videos}
              retryStage={retryStage}
              bulkRetryFailed={bulkRetryFailed}
              triggerManualScan={triggerManualScan}
              navigateTo={navigateTo}
              initialTab="tasks"
              hideHeader
              hideTabs
            />
          </div>
        </div>
      )}

      {activeTab === 'retry' && (
        <ContentWorkbench
          videos={videos}
          retryStage={retryStage}
          bulkRetryFailed={bulkRetryFailed}
          triggerManualScan={triggerManualScan}
          navigateTo={navigateTo}
          initialTab="retry"
          hideHeader
          hideTabs
        />
      )}

      {activeTab === 'models' && <ModelGpuPanel system={system} config={config} />}

      {activeTab === 'overview' && (
        <RunOverviewPanel
          videos={videos}
          logs={logs}
          alerts={alerts}
          system={system}
          config={config}
          triggerManualScan={triggerManualScan}
          switchTab={switchTab}
        />
      )}

      {systemTab && (
        <SystemMonitor
          pushRecords={pushRecords}
          logs={logs}
          alerts={alerts}
          system={system}
          rebootWebUI={rebootWebUI}
          triggerManualScan={triggerManualScan}
          initialTab={systemTab}
          hideHeader
          hideTabs
        />
      )}
    </div>
  );
}
