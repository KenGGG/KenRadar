/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Gauge,
  Github,
  ListChecks,
  RefreshCw,
  Send,
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
  const failedTasks = tasks.filter(task => task.status === 'failed').length;
  const waitingCount = queuedBackground.length + queuedTasks.length;
  const runningCount = activeTasks.length + (system.background_task?.running ? 1 : 0);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm">
        <span className="font-semibold text-zinc-900">批次队列</span>
        <span className="text-zinc-500">进行中 <strong className="tabular-nums text-zinc-900">{runningCount}</strong></span>
        <span className="text-zinc-500">等待 <strong className="tabular-nums text-zinc-900">{waitingCount}</strong></span>
        <span className={failedTasks > 0 ? 'text-red-700' : 'text-zinc-500'}>
          失败 <strong className="tabular-nums">{failedTasks}</strong>
        </span>
        <span className="ml-auto text-xs text-zinc-400">批次按进入顺序执行，作品转录完成后立即进入 AI 整理</span>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-lg border border-zinc-200 bg-white">
          <div className="border-b border-zinc-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-zinc-900">正在执行</h2>
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
    <div className="grid grid-cols-1 gap-4 animate-fade-in xl:grid-cols-[minmax(260px,0.75fr)_minmax(0,1.75fr)]">
      <section className="rounded-lg border border-zinc-200 bg-white p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">GPU 资源</h2>
            <p className="mt-1 text-xs text-zinc-500">{system.gpu_label || 'GPU 调度'}</p>
          </div>
          <span className="text-lg font-semibold tabular-nums text-zinc-950">{gpuPercent}%</span>
        </div>
        <div className="mt-5 h-2 overflow-hidden rounded-full bg-zinc-100">
          <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${gpuPercent}%` }} />
        </div>
        <div className="mt-4 flex items-center justify-between text-xs text-zinc-500">
          <span>调度状态</span>
          <span className="font-medium text-zinc-800">{system.gpu_status || '未知'}</span>
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-zinc-500">
          <span>Whisper</span>
          <span className="font-mono text-zinc-700">{system.whisper_model || config.whisper?.model || 'large-v3-turbo'} · {whisperDevice}</span>
        </div>
      </section>

      <section className="rounded-lg border border-zinc-200 bg-white">
        <div className="border-b border-zinc-100 px-5 py-4">
          <h2 className="text-sm font-semibold text-zinc-900">模型与服务</h2>
          <p className="mt-1 text-xs text-zinc-500">Agnes AI 为主整理引擎，Ollama 仅在主引擎不可用时后备。</p>
        </div>
        <div className="grid grid-cols-1 gap-px bg-zinc-100 md:grid-cols-2">
          {services.map(service => (
            <div key={service.name} className="bg-white px-5 py-4">
              <div className="flex items-center justify-between gap-3">
                <div className="font-semibold text-zinc-900">{service.name}</div>
                <span className={`rounded px-2 py-0.5 text-[10px] font-medium ${
                  service.tone === 'green' ? 'bg-emerald-50 text-emerald-700' :
                  service.tone === 'blue' ? 'bg-blue-50 text-blue-700' : 'bg-white text-zinc-600'
                }`}>{service.status}</span>
              </div>
              <div className="mt-2 break-all font-mono text-xs text-zinc-500">{service.value}</div>
            </div>
          ))}
        </div>
      </section>
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
  const runningVideos = videos.filter(video => video.status === 'processing');
  const failedVideos = videos.filter(video => video.status === 'failed');
  const activeResearch = tasks
    .filter(task => task.status === 'processing' || task.status === 'paused')
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
  const queuedTasks = system.background_task?.queue || [];
  const alertCount = Number(system.health?.alert_attention || 0);
  const activeRunCount = activeResearch.length + runningVideos.length + (system.background_task?.running ? 1 : 0);
  const waitingCount = queuedTasks.length + tasks.filter(task => task.status === 'queued').length;
  const tone = healthTone(failedVideos.length, alertCount, activeRunCount);
  const HealthIcon = tone.icon;
  const recentLog = logs[0];
  const recentAlert = alerts[0];
  const gpuPercent = system.gpu_percent ?? 0;
  const nextAction = failedVideos.length > 0
    ? { label: `处理 ${failedVideos.length} 条失败内容`, tab: 'retry' as RunTab }
    : alertCount > 0
      ? { label: `查看 ${alertCount} 条系统告警`, tab: 'alerts' as RunTab }
      : system.background_task?.running || runningVideos.length > 0 || queuedTasks.length > 0
        ? { label: '查看处理队列', tab: 'queue' as RunTab }
        : { label: '发起手动检测', tab: null };

  return (
    <div className="space-y-4 animate-fade-in">
      <section className={`rounded-lg border ${tone.className}`}>
        <div className="flex flex-col gap-4 p-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3">
            <HealthIcon className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <div className="text-sm font-semibold">系统{tone.label}</div>
              <p className="mt-1 text-xs leading-5 opacity-80">
                {failedVideos.length > 0 || alertCount > 0
                  ? '有需要处理的异常，建议先完成恢复操作。'
                  : activeRunCount > 0
                    ? '任务正在按流水线执行，无需人工干预。'
                    : waitingCount > 0
                      ? '任务已进入队列，将按顺序自动执行。'
                      : '当前空闲，等待下一次定时检测。'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => nextAction.tab ? switchTab(nextAction.tab) : triggerManualScan()}
            className="inline-flex min-h-10 items-center justify-center rounded-md border border-white/80 bg-white/80 px-3 text-xs font-semibold text-zinc-800 transition hover:bg-white"
          >
            {nextAction.label}
          </button>
        </div>
        <div className="grid grid-cols-2 border-t border-current/10 md:grid-cols-5">
          {[
            ['调度', system.health.schedule || '未知'],
            ['进行中', `${activeRunCount} 项`],
            ['等待', `${waitingCount} 项`],
            ['需处理', `${failedVideos.length + alertCount} 项`],
            ['下次运行', system.health.next_run || '暂无'],
          ].map(([label, value]) => (
            <div key={label} className="border-r border-current/10 px-4 py-3 last:border-r-0">
              <div className="text-[11px] opacity-60">{label}</div>
              <div className="mt-1 truncate text-sm font-semibold tabular-nums" title={String(value)}>{value}</div>
            </div>
          ))}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="rounded-lg border border-zinc-200 border-l-4 border-l-blue-500 bg-white">
          <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold text-zinc-900">当前运行</h2>
              <p className="mt-1 text-xs text-zinc-500">只显示当前批次和关键进度。</p>
            </div>
            <button onClick={() => switchTab('queue')} className="min-h-10 px-2 text-xs font-semibold text-blue-700 hover:text-blue-900">查看队列</button>
          </div>
          <div className="p-4">
            {system.background_task?.running ? (
              <div className="space-y-3">
                <div>
                  <div className="text-sm font-semibold text-zinc-900">{system.background_task.message}</div>
                  <div className="mt-1 text-xs text-zinc-500">开始于 {system.background_task.started_at || '刚刚'}</div>
                </div>
                {system.background_task.progress && (
                  <div className="space-y-1.5">
                    <div className="flex justify-between gap-4 text-xs text-zinc-500">
                      <span className="truncate">{system.background_task.progress.message}</span>
                      <span className="shrink-0 font-mono tabular-nums">{system.background_task.progress.current}/{system.background_task.progress.total}</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-zinc-100">
                      <div
                        className="h-full rounded-full bg-blue-600"
                        style={{ width: `${Math.round(system.background_task.progress.current / Math.max(1, system.background_task.progress.total) * 100)}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>
            ) : activeResearch.length > 0 ? (
              <div className="space-y-3">
                {activeResearch.slice(0, 2).map(task => (
                  <div key={task.id}>
                    <div className="flex items-center justify-between gap-3">
                      <div className="truncate text-sm font-semibold text-zinc-900">{task.target}</div>
                      <span className="shrink-0 text-xs text-blue-700">{taskStatusLabel(task.status)}</span>
                    </div>
                    <div className="mt-1 text-xs text-zinc-500">研究任务 #{task.id} · {task.completed_items || 0}/{task.total_items || 0}</div>
                    {task.pipeline_stages && <div className="mt-3"><TaskStageCounts stages={task.pipeline_stages} /></div>}
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-7 text-center">
                <CheckCircle2 className="mx-auto h-6 w-6 text-emerald-500" />
                <p className="mt-2 text-sm font-medium text-zinc-800">当前没有运行中的任务</p>
                <p className="mt-1 text-xs text-zinc-500">{waitingCount > 0 ? `${waitingCount} 项正在等待执行` : '系统将按定时计划自动检测'}</p>
              </div>
            )}
          </div>
        </section>

        <section className={`rounded-lg border bg-white ${failedVideos.length > 0 || alertCount > 0 ? 'border-amber-200' : 'border-zinc-200'}`}>
          <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold text-zinc-900">需要处理</h2>
              <p className="mt-1 text-xs text-zinc-500">这里只保留仍需人工关注的事项。</p>
            </div>
            {(failedVideos.length > 0 || alertCount > 0) && (
              <span className="rounded bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">{failedVideos.length + alertCount} 项</span>
            )}
          </div>
          <div className="p-4">
            {failedVideos.length === 0 && alertCount === 0 ? (
              <div className="py-7 text-center">
                <CheckCircle2 className="mx-auto h-6 w-6 text-emerald-500" />
                <p className="mt-2 text-sm font-medium text-zinc-800">没有待处理异常</p>
                <p className="mt-1 text-xs text-zinc-500">历史告警不会持续占用这里。</p>
              </div>
            ) : (
              <div className="space-y-2">
                {failedVideos.slice(0, 2).map(video => (
                  <button key={video.id} onClick={() => switchTab('retry')} className="w-full rounded border border-red-100 bg-red-50/50 px-3 py-2 text-left transition hover:bg-red-50">
                    <div className="text-xs font-medium text-red-700">{video.failed_at_step || video.failure_stage || '处理'}失败</div>
                    <div className="mt-1 truncate text-sm font-medium text-zinc-900">{video.title || video.id}</div>
                  </button>
                ))}
                {alertCount > 0 && (
                  <button onClick={() => switchTab('alerts')} className="w-full rounded border border-amber-100 bg-amber-50/60 px-3 py-2 text-left">
                    <div className="text-sm font-medium text-amber-900">{alertCount} 条告警需要查看</div>
                    <div className="mt-1 truncate text-xs text-amber-700">{recentAlert?.title || '进入系统告警查看详情'}</div>
                  </button>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      <section className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <button onClick={() => switchTab('models')} className="flex min-h-16 items-center gap-3 rounded border border-zinc-100 bg-zinc-50 px-3 text-left transition hover:bg-white">
            <Gauge className="h-4 w-4 shrink-0 text-zinc-500" />
            <div>
              <div className="text-sm font-medium text-zinc-900">模型与服务</div>
              <div className="mt-1 text-xs text-zinc-500">GPU {system.gpu_status || '未知'} · {gpuPercent}% · Agnes AI 主引擎</div>
            </div>
          </button>
          <button onClick={() => switchTab('logs')} className="flex min-h-16 items-center gap-3 rounded border border-zinc-100 bg-zinc-50 px-3 text-left transition hover:bg-white">
            <Terminal className="h-4 w-4 shrink-0 text-zinc-500" />
            <div className="min-w-0">
              <div className="text-sm font-medium text-zinc-900">最近运行</div>
              <div className="mt-1 truncate text-xs text-zinc-500">{recentLog ? `${recentLog.timestamp} · ${recentLog.message}` : '暂无运行记录'}</div>
            </div>
          </button>
          <div className="flex min-h-16 items-center gap-3 rounded border border-zinc-100 bg-zinc-50 px-3">
            <Github className="h-4 w-4 shrink-0 text-zinc-500" />
            <div className="min-w-0">
              <div className="text-sm font-medium text-zinc-900">GitHub 发布</div>
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
    <div className="space-y-6 animate-fade-in">
      <div className="border-b border-zinc-200 pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-2xl font-sans font-semibold text-zinc-900">运行中心</h1>
          <p className="text-zinc-500 font-sans text-sm mt-1">先确认系统状态，再处理队列与异常。</p>
        </div>
        {activeTab !== 'overview' && (
          <button
            onClick={() => {
              triggerManualScan();
              alert('手动检测任务已加入后台队列。');
            }}
            className="flex min-h-10 items-center gap-1.5 rounded border border-zinc-200 px-3 text-xs font-sans font-medium text-zinc-700 transition hover:bg-zinc-50 cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>手动全量检测</span>
          </button>
        )}
      </div>

      <div className="flex flex-wrap border-b border-zinc-200 gap-x-4 gap-y-2" role="tablist" aria-label="运行中心视图">
        {tabs.map((tab, index) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => switchTab(tab.id)}
              role="tab"
              aria-selected={active}
              className={`min-h-10 pb-3 inline-flex items-center gap-1.5 text-sm font-sans font-semibold transition relative outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 cursor-pointer ${
                index === 4 ? 'ml-0 border-l border-zinc-200 pl-4 md:ml-1' : ''
              } ${
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
              hideStats
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
          tasks={tasks}
          logs={logs}
          alerts={alerts}
          system={system}
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
