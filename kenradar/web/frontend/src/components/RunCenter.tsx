/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * RunCenter - Operations center
 * 4 tabs: Overview | Failure Recovery | History | Models & GPU
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
  FileText,
  Gauge,
  Github,
  History,
  Power,
  RefreshCw,
  RotateCw,
  Search,
  Send,
  Terminal,
} from 'lucide-react';
import ContentWorkbench from './ContentWorkbench';
import { TaskProgressBar, TaskStageCounts, taskStatusClass, taskStatusLabel } from './TaskProgress';
import { AlertRecord, PushRecord, ResearchTask, SystemConfig, SystemInfo, SystemLog, VideoContent } from '../types';
import { ScoreBadge, EmptyState } from './UITokens';

/* ── Types ── */
type RunTab = 'overview' | 'retry' | 'history' | 'models';

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

/* ── Helpers ── */
function healthTone(failedCount: number, alertCount: number, runningCount: number) {
  if (alertCount > 0 || failedCount > 0) return { label: '需要处理', className: 'border-amber-150 bg-amber-50/60 text-amber-900', icon: AlertTriangle };
  if (runningCount > 0) return { label: '运行中', className: 'border-blue-150 bg-blue-50/60 text-blue-900', icon: Activity };
  return { label: '正常运行', className: 'border-emerald-150 bg-emerald-50/50 text-emerald-900', icon: CheckCircle2 };
}

function runTabFromLocation(): RunTab {
  const params = new URLSearchParams(window.location.search);
  const tab = params.get('tab');
  if (tab === 'retry' || tab === 'history' || tab === 'models') return tab;
  return 'overview';
}

const RUN_TAB_PATHS: Record<RunTab, string> = {
  overview: '/run?tab=overview',
  retry: '/run?tab=retry',
  history: '/run?tab=history',
  models: '/run?tab=models',
};

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
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm">
        <span className="font-semibold text-zinc-900">批次队列</span>
        <span className="text-zinc-500">进行中 <strong className="tabular-nums text-zinc-900">{runningCount}</strong></span>
        <span className="text-zinc-500">等待 <strong className="tabular-nums text-zinc-900">{waitingCount}</strong></span>
        <span className={failedTasks > 0 ? 'text-red-700' : 'text-zinc-500'}>
          失败 <strong className="tabular-nums">{failedTasks}</strong>
        </span>
        <span className="ml-auto text-xs text-zinc-400">批次按进入顺序执行</span>
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
              <div className="px-4 py-10 text-center text-sm text-zinc-400">暂无排队任务，所有任务已处理完成。</div>
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

/* ── Model & GPU Panel ── */
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
  const runningTaskCount = activeResearch.length + (system.background_task?.running ? 1 : 0);
  const waitingCount = queuedTasks.length + tasks.filter(task => task.status === 'queued').length;
  const tone = healthTone(failedVideos.length, alertCount, runningTaskCount);
  const HealthIcon = tone.icon;
  const recentLog = logs[0];

  const isIdle = runningTaskCount === 0 && waitingCount === 0 && failedVideos.length === 0 && alertCount === 0;
  const isRunning = runningTaskCount > 0 || waitingCount > 0;
  const hasErrors = failedVideos.length > 0 || alertCount > 0;

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
              className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-white/80 bg-white/80 px-3 text-xs font-medium text-zinc-800 hover:bg-white"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              手动检测
            </button>
            {hasErrors && (
              <button
                type="button"
                onClick={() => switchTab('retry')}
                className="inline-flex min-h-9 items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-3 text-xs font-medium text-amber-800 hover:bg-amber-100"
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

      {/* ── IDLE state: last-run summary + quick actions ── */}
      {isIdle && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <section className="rounded-lg border border-zinc-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-zinc-900 mb-3">系统状态</h2>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: 'GPU', value: `${system.gpu_status || '-'} · ${system.gpu_percent ?? '-'}%` },
                { label: '推送成功率', value: system.health.push_rate || '暂无推送' },
                { label: '调度状态', value: (system.health.schedule as string) || '未知' },
                { label: '磁盘', value: system.health.disk_free || '未知' },
              ].map(item => (
                <div key={item.label} className="border border-zinc-100 rounded-lg p-3">
                  <div className="text-[10px] text-zinc-400 font-mono uppercase">{item.label}</div>
                  <div className="mt-1 text-sm font-semibold text-zinc-900">{item.value}</div>
                </div>
              ))}
            </div>
          </section>
          <section className="rounded-lg border border-zinc-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-zinc-900 mb-3">快捷操作</h2>
            <div className="grid grid-cols-2 gap-3">
              <button onClick={triggerManualScan} className="flex items-center gap-2 rounded border border-zinc-100 bg-zinc-50 px-3 py-3 text-left text-xs font-medium text-zinc-700 hover:bg-white transition">
                <RefreshCw className="h-4 w-4 shrink-0 text-zinc-500" />
                发起全量检测
              </button>
              <button onClick={() => switchTab('models')} className="flex items-center gap-2 rounded border border-zinc-100 bg-zinc-50 px-3 py-3 text-left text-xs font-medium text-zinc-700 hover:bg-white transition">
                <Cpu className="h-4 w-4 shrink-0 text-zinc-500" />
                查看模型状态
              </button>
              <button onClick={() => switchTab('history')} className="flex items-center gap-2 rounded border border-zinc-100 bg-zinc-50 px-3 py-3 text-left text-xs font-medium text-zinc-700 hover:bg-white transition">
                <History className="h-4 w-4 shrink-0 text-zinc-500" />
                运行日志
              </button>
              <div className="flex items-center gap-2 rounded border border-zinc-100 bg-zinc-50 px-3 py-3 text-xs text-zinc-500">
                <Github className="h-4 w-4 shrink-0 text-zinc-400" />
                <span className="truncate">{system.publishing?.latest_html_published_at ? `最近发布 ${system.publishing.latest_html_published_at}` : '暂无发布'}</span>
              </div>
            </div>
          </section>
        </div>
      )}

      {/* ── RUNNING state: progress + queue ── */}
      {isRunning && !hasErrors && (
        <>
          <section className="rounded-lg border border-zinc-200 border-l-4 border-l-blue-500 bg-white">
            <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
              <h2 className="text-sm font-semibold text-zinc-900">当前运行</h2>
            </div>
            <div className="p-4">
              {system.background_task?.running ? (
                <div className="space-y-3">
                  <div className="text-sm font-semibold text-zinc-900">{system.background_task.message}</div>
                  <div className="text-xs text-zinc-500">开始于 {system.background_task.started_at || '刚刚'}</div>
                  {system.background_task.progress && (
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-xs text-zinc-500">
                        <span>{system.background_task.progress.message}</span>
                        <span className="font-mono">{system.background_task.progress.current}/{system.background_task.progress.total}</span>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-zinc-100">
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
                        <div className="truncate text-sm font-semibold text-zinc-900">{task.target}</div>
                        <span className="shrink-0 text-xs text-blue-700">{taskStatusLabel(task.status)}</span>
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
            <section className="rounded-lg border border-zinc-200 bg-white px-4 py-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-zinc-600">
                  <Clock3 className="mr-1.5 inline h-4 w-4 text-zinc-400" />
                  {waitingCount} 项任务在等待队列中
                </span>
                <span className="text-xs text-zinc-500">系统将在当前任务完成后自动执行</span>
              </div>
            </section>
          )}
        </>
      )}

      {/* ── ERROR state: failures + alerts ── */}
      {hasErrors && (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {failedVideos.length > 0 && (
            <section className="rounded-lg border border-red-200 bg-white">
              <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-900">待处理失败</h2>
                <span className="rounded bg-red-50 px-2 py-1 text-xs font-medium text-red-700">{failedVideos.length} 条</span>
              </div>
              <div className="divide-y divide-zinc-100">
                {failedVideos.slice(0, 5).map(video => (
                  <div key={video.id} className="px-4 py-3 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate font-medium text-zinc-900">{video.title || video.id}</div>
                        <div className="mt-0.5 text-xs text-zinc-500">{video.blogger} · {video.failed_at_step || video.failure_stage || '未知'}阶段失败</div>
                      </div>
                      <button onClick={() => switchTab('retry')} className="shrink-0 text-xs font-medium text-blue-700 hover:text-blue-900">
                        处理
                      </button>
                    </div>
                  </div>
                ))}
                {failedVideos.length > 5 && (
                  <div className="px-4 py-2 text-xs text-zinc-400 text-center">还有 {failedVideos.length - 5} 条</div>
                )}
                <div className="border-t border-zinc-100 px-4 py-2">
                  <button onClick={() => switchTab('retry')} className="text-xs font-medium text-blue-700 hover:text-blue-900">
                    查看全部失败 &rarr;
                  </button>
                </div>
              </div>
            </section>
          )}

          {alertCount > 0 && (
            <section className="rounded-lg border border-amber-200 bg-white">
              <div className="flex items-center justify-between border-b border-zinc-100 px-4 py-3">
                <h2 className="text-sm font-semibold text-zinc-900">系统告警</h2>
                <span className="rounded bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">{alertCount} 条</span>
              </div>
              <div className="divide-y divide-zinc-100">
                {alerts.slice(0, 4).map((alert, idx) => (
                  <div key={alert.id || idx} className="px-4 py-3">
                    <div className="flex items-start gap-2">
                      <AlertTriangle className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${alert.level === 'critical' ? 'text-red-600' : 'text-amber-500'}`} />
                      <div className="min-w-0">
                        <div className="text-sm font-medium text-zinc-900">{alert.title}</div>
                        <div className="mt-0.5 text-xs text-zinc-500">{alert.time}</div>
                      </div>
                    </div>
                  </div>
                ))}
                <div className="border-t border-zinc-100 px-4 py-2">
                  <button onClick={() => switchTab('history')} className="text-xs font-medium text-blue-700 hover:text-blue-900">
                    查看全部告警 &rarr;
                  </button>
                </div>
              </div>
            </section>
          )}

          {isRunning && (
            <section className="rounded-lg border border-zinc-200 bg-white px-4 py-3">
              <span className="text-sm text-zinc-600">
                <Activity className="mr-1.5 inline h-4 w-4 text-blue-500" />
                {runningTaskCount} 个任务仍在运行中
              </span>
            </section>
          )}
        </div>
      )}

      {/* Bottom shortcuts (always visible) */}
      <section className="rounded-lg border border-zinc-200 bg-white p-4">
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <button onClick={() => switchTab('models')} className="flex min-h-14 items-center gap-3 rounded border border-zinc-100 bg-zinc-50 px-3 text-left transition hover:bg-white">
            <Gauge className="h-4 w-4 shrink-0 text-zinc-500" />
            <div>
              <div className="text-sm font-medium text-zinc-900">模型与服务</div>
              <div className="mt-1 text-xs text-zinc-500">GPU {system.gpu_status || '未知'} · {system.gpu_percent ?? '-'}%</div>
            </div>
          </button>
          <button onClick={() => switchTab('history')} className="flex min-h-14 items-center gap-3 rounded border border-zinc-100 bg-zinc-50 px-3 text-left transition hover:bg-white">
            <Terminal className="h-4 w-4 shrink-0 text-zinc-500" />
            <div className="min-w-0">
              <div className="text-sm font-medium text-zinc-900">历史记录</div>
              <div className="mt-1 truncate text-xs text-zinc-500">{recentLog ? `${recentLog.timestamp} · ${recentLog.message}` : '暂无运行记录'}</div>
            </div>
          </button>
          <div className="flex min-h-14 items-center gap-3 rounded border border-zinc-100 bg-zinc-50 px-3">
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

/* ── History subtabs ── */
type HistorySubtabs = 'push' | 'alerts' | 'logs';

function HistoryPanel({
  pushRecords,
  logs,
  alerts,
  system,
  rebootWebUI,
}: {
  pushRecords: PushRecord[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  rebootWebUI: () => void;
}) {
  const [subtab, setSubtab] = useState<HistorySubtabs>('push');
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
      alert("服务进程重启指令已投递，正在同步端口缓存中。");
    }
  };

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Subtab navigation */}
      <div className="flex items-center justify-between border-b border-zinc-200">
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
                  subtab === tab.id ? 'text-zinc-950' : 'text-zinc-400 hover:text-zinc-700'
                }`}
              >
                <Icon className="mr-1.5 inline h-3.5 w-3.5" />
                {tab.label}
                {subtab === tab.id && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 rounded" />}
              </button>
            );
          })}
        </div>
        <button
          onClick={runReboot}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-red-50 text-red-600 border border-red-100/60 hover:bg-red-100 rounded text-xs font-medium transition cursor-pointer"
        >
          <Power className="w-3.5 h-3.5" />
          Web 重启
        </button>
      </div>

      {/* Push records */}
      {subtab === 'push' && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">飞书推送日志</h3>
            <span className="text-xs text-zinc-400">共 {pushRecords.length} 条记录</span>
          </div>
          {pushRecords.length === 0 ? (
            <EmptyState icon={Send} title="暂未保存任何飞书自动推送记录" />
          ) : (
            <div className="border border-zinc-150 rounded-lg overflow-hidden bg-white">
              <div className="divide-y divide-zinc-150">
                {pushRecords.map(rec => {
                  const isInspected = inspectedPushId === rec.id;
                  return (
                    <div key={rec.id} className="p-4 hover:bg-zinc-50/20 transition space-y-3">
                      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
                        <div className="space-y-0.5">
                          <div className="flex items-center space-x-2 flex-wrap">
                            <span className="text-xs font-medium text-purple-600 bg-purple-50 px-2 py-0.5 rounded">
                              {rec.push_type.toUpperCase()}
                            </span>
                            <span className="text-xs text-zinc-400 font-mono">ID: {rec.id}</span>
                          </div>
                          <h4 className="text-sm font-bold text-zinc-900 leading-snug pt-1">{rec.title}</h4>
                        </div>
                        <div className="flex items-center space-x-3.5 shrink-0">
                          <span className="text-xs text-zinc-400 font-mono">{rec.sent_at}</span>
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded ${
                            rec.status === 'success' ? 'text-emerald-600 bg-emerald-50' : 'text-red-650 bg-red-50'
                          }`}>
                            {rec.status === 'success' ? '发送完成' : '发送失败'}
                          </span>
                          <button
                            onClick={() => setInspectedPushId(isInspected ? null : rec.id)}
                            className="p-1 text-zinc-400 hover:text-zinc-900 transition flex items-center space-x-1 text-xs"
                          >
                            <Eye className="w-3.5 h-3.5" />
                            <span>{isInspected ? '隐藏' : '检视'}</span>
                          </button>
                        </div>
                      </div>
                      {isInspected && (
                        <div className="bg-zinc-950 rounded-md p-4 border border-zinc-800 font-mono text-zinc-350 text-[11px] leading-relaxed relative overflow-x-auto whitespace-pre-wrap animate-fade-in max-h-60">
                          <button
                            onClick={() => { navigator.clipboard.writeText(rec.payload); alert("Payload 已复制。"); }}
                            className="absolute right-3 top-3 p-1.5 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 text-zinc-400 hover:text-white rounded"
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
            <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">系统告警</h3>
            <span className="text-xs text-zinc-400">抓取、转录、飞书推送相关故障</span>
          </div>
          {alerts.length === 0 ? (
            <EmptyState icon={CheckCircle2} title="暂无系统告警" description="当前没有需要处理的系统告警记录。" />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {alerts.map((alt, index) => (
                <div key={index} className={`p-5 rounded-lg border flex items-start space-x-4 ${
                  alt.level === 'critical' ? 'bg-red-50/30 border-red-150 text-red-950' : 'bg-amber-50/20 border-amber-150 text-amber-950'
                }`}>
                  <AlertTriangle className={`w-5 h-5 mt-0.5 shrink-0 ${alt.level === 'critical' ? 'text-red-600' : 'text-amber-500'}`} />
                  <div className="space-y-1.5">
                    <div className="flex items-center space-x-2.5">
                      <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-black uppercase ${
                        alt.level === 'critical' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'
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
          <div className="p-4 bg-zinc-50 border border-zinc-150 rounded-lg flex flex-col sm:flex-row items-center justify-between gap-4">
            <div className="flex items-center space-x-2">
              <span className="text-xs font-mono text-zinc-400">日志等级:</span>
              <div className="flex border border-zinc-205 p-0.5 rounded bg-white">
                {['all', 'info', 'warn', 'error'].map(l => (
                  <button
                    key={l}
                    onClick={() => setLogLevelFilter(l as any)}
                    className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded-sm transition cursor-pointer ${
                      logLevelFilter === l ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:text-zinc-905'
                    }`}
                  >
                    {l.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-zinc-400" />
              <input
                type="text"
                placeholder="检索日志..."
                value={logSearchQuery}
                onChange={e => setLogSearchQuery(e.target.value)}
                className="w-full bg-white border border-zinc-250 rounded pl-8 pr-3 py-1.5 text-xs font-mono focus:outline-none focus:border-zinc-900"
              />
            </div>
          </div>

          <div className="p-5 rounded-lg bg-zinc-950 border border-zinc-850 shadow-inner h-[500px] overflow-y-auto flex flex-col-reverse justify-end font-mono text-xs text-zinc-300 leading-relaxed select-text">
            {filteredLogs.length === 0 ? (
              <div className="py-20 text-center text-zinc-500 font-mono space-y-1 select-none">
                <Terminal className="w-8 h-8 mx-auto text-zinc-700 stroke-1 mb-2" />
                <p>--- 未匹配到日志 ---</p>
                <p className="text-[10px]">调整筛选条件或触发全量检测</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                {filteredLogs.map(log => (
                  <div key={log.id} className="hover:bg-zinc-900/40 p-1 rounded font-mono flex items-start space-x-2 justify-between">
                    <div className="flex-1">
                      <span className="text-zinc-500 mr-2.5">[{log.timestamp}]</span>
                      <span className={`font-bold mr-2 ${
                        log.level === 'info' ? 'text-emerald-400' :
                        log.level === 'warn' ? 'text-amber-400' : 'text-red-500'
                      }`}>
                        [{log.level.toUpperCase()}]
                      </span>
                      <span className="text-blue-400 mr-2">[{log.module}]</span>
                      <span className="text-zinc-200">{log.message}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="text-[10px] text-zinc-400 text-center font-mono">
            * 默认展示最近 300 条日志。完整日志路径：{system.log_path}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Main RunCenter ── */
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
    { id: 'overview' as const, label: '概览', icon: Activity },
    { id: 'retry' as const, label: '失败恢复', icon: AlertTriangle, count: failedCount },
    { id: 'history' as const, label: '历史记录', icon: History, count: alertCount },
    { id: 'models' as const, label: '模型与服务', icon: Cpu },
  ], [failedCount, alertCount]);

  const switchTab = (tab: RunTab) => {
    setActiveTab(tab);
    window.history.pushState(null, '', RUN_TAB_PATHS[tab]);
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="border-b border-zinc-200 pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900">运行中心</h1>
          <p className="text-zinc-500 text-sm mt-1">先确认系统状态，再处理队列与异常。</p>
        </div>
        {activeTab !== 'overview' && (
          <button
            onClick={() => { triggerManualScan(); alert('手动检测任务已加入后台队列。'); }}
            className="flex min-h-10 items-center gap-1.5 rounded border border-zinc-200 px-3 text-xs font-medium text-zinc-700 transition hover:bg-zinc-50 cursor-pointer"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            手动全量检测
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap border-b border-zinc-200 gap-x-4 gap-y-2" role="tablist">
        {tabs.map(tab => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => switchTab(tab.id)}
              role="tab"
              aria-selected={active}
              className={`min-h-10 pb-3 inline-flex items-center gap-1.5 text-sm font-semibold transition relative outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 cursor-pointer ${
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

      {/* Tab content */}
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
          retryMode
        />
      )}

      {activeTab === 'history' && (
        <HistoryPanel
          pushRecords={pushRecords}
          logs={logs}
          alerts={alerts}
          system={system}
          rebootWebUI={rebootWebUI}
        />
      )}

      {activeTab === 'models' && (
        <ModelGpuPanel system={system} config={config} />
      )}
    </div>
  );
}
