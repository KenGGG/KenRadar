import { AlertTriangle, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import { RunTaskView } from '../RunCenterModel';
import { SystemInfo, SystemLog } from '../../types';
import TaskDiagnostics from './TaskDiagnostics';

const STAGES = ['发现', '下载', '转录', 'AI 整理', '笔记', 'Pages 发布', '飞书通知'];

function currentStageIndex(view: RunTaskView) {
  const stage = String(view.task.pipeline_stage || '').toLowerCase();
  if (stage.includes('download')) return 1;
  if (stage.includes('transcrib')) return 2;
  if (stage.includes('summar') || stage === 'ai') return 3;
  if (stage.includes('publish')) return 5;
  if (stage.includes('push')) return 6;
  if (view.state === 'completed') return 7;
  return view.state === 'queued' ? 0 : 1;
}

function stageState(view: RunTaskView, index: number) {
  const current = currentStageIndex(view);
  if (view.state === 'completed') return 'success';
  if (view.state === 'failed' && index === Math.max(0, Math.min(6, current))) return 'failed';
  if (index < current) return 'success';
  if (index === current && view.state === 'running') return 'running';
  if (index === current && view.state === 'paused') return 'paused';
  return 'waiting';
}

function tone(state: RunTaskView['state']) {
  if (state === 'failed') return 'border-red-200 bg-red-50 text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]';
  if (state === 'paused') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-[var(--warning-border)] dark:bg-[var(--warning-bg)] dark:text-[var(--warning)]';
  if (state === 'running') return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-[var(--info-border)] dark:bg-[var(--info-bg)] dark:text-[var(--info)]';
  if (state === 'queued') return 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] dark:text-[var(--text-secondary)]';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-[var(--success-border)] dark:bg-[var(--success-bg)] dark:text-[var(--success)]';
}

function stateLabel(state: RunTaskView['state']) {
  return { failed: '需要修复', paused: '已暂停', running: '运行中', queued: '排队中', completed: '已完成' }[state];
}

export default function TaskCommandCard({ view, expanded, onToggle, onRepair, system, logs }: {
  view: RunTaskView;
  expanded: boolean;
  onToggle: () => void;
  onRepair: () => void;
  system: SystemInfo;
  logs: SystemLog[];
}) {
  const task = view.task;
  return (
    <article className={`overflow-hidden rounded-lg border bg-white dark:bg-[var(--surface)] ${view.state === 'failed' ? 'border-red-200 dark:border-[var(--danger-border)]' : 'border-zinc-200 dark:border-[var(--surface-border)]'}`}>
      <div className="p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <button type="button" onClick={onToggle} className="min-w-0 flex-1 text-left cursor-pointer" aria-expanded={expanded}>
            <div className="flex flex-wrap items-center gap-2">
              <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold ${tone(view.state)}`}>{stateLabel(view.state)}</span>
              <span className="text-[11px] font-mono text-zinc-400 dark:text-[var(--text-muted)]">任务 #{task.id}</span>
              <span className="text-[11px] text-zinc-400 dark:text-[var(--text-muted)]">{task.type === 'blogger' ? '博主批量' : '单视频'} · {task.created_at}</span>
            </div>
            <div className="mt-2 flex items-center gap-2">
              {expanded ? <ChevronDown className="h-4 w-4 shrink-0 text-zinc-400" /> : <ChevronRight className="h-4 w-4 shrink-0 text-zinc-400" />}
              <h3 className="truncate text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)]">{task.target || '未命名任务'}</h3>
            </div>
          </button>
          <div className="flex shrink-0 items-center gap-2">
            <div className="text-right">
              <div className="text-xs font-semibold text-zinc-700 dark:text-[var(--text-secondary)]">{view.stageLabel} · {view.progress}%</div>
              <div className="mt-1 text-[10px] text-zinc-400 dark:text-[var(--text-muted)]">完成 {task.completed_items ?? 0} / {task.total_items ?? '—'} · 失败 {task.failed_items ?? 0}</div>
            </div>
            {view.state === 'failed' && (
              <button type="button" onClick={onRepair} className="inline-flex min-h-9 items-center gap-1.5 rounded-md bg-red-600 px-3 text-xs font-semibold text-white hover:bg-red-700 cursor-pointer">
                <RefreshCw className="h-3.5 w-3.5" />从卡点重试
              </button>
            )}
          </div>
        </div>

        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]"><div className={view.state === 'failed' ? 'h-full bg-red-500' : view.state === 'completed' ? 'h-full bg-emerald-500' : 'h-full bg-blue-500'} style={{ width: `${view.progress}%` }} /></div>

        <div className="mt-4 overflow-x-auto pb-1">
          <div className="flex min-w-[680px] items-center">
            {STAGES.map((stage, index) => {
              const state = stageState(view, index);
              return (
                <div key={stage} className="flex flex-1 items-center last:flex-none">
                  <div className="flex min-w-20 flex-col items-center gap-1.5">
                    <span className={`flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-bold ${state === 'success' ? 'border-emerald-500 bg-emerald-500 text-white' : state === 'running' ? 'border-blue-500 bg-blue-50 text-blue-700 dark:bg-[var(--info-bg)] dark:text-[var(--info)]' : state === 'failed' ? 'border-red-500 bg-red-50 text-red-700 dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]' : state === 'paused' ? 'border-amber-500 bg-amber-50 text-amber-700' : 'border-zinc-250 bg-white text-zinc-400 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-muted)]'}`}>
                      {state === 'success' ? '✓' : state === 'failed' ? <AlertTriangle className="h-3 w-3" /> : index + 1}
                    </span>
                    <span className="whitespace-nowrap text-[10px] font-medium text-zinc-500 dark:text-[var(--text-muted)]">{stage}</span>
                  </div>
                  {index < STAGES.length - 1 && <div className={`mb-5 h-px flex-1 ${index < currentStageIndex(view) ? 'bg-emerald-400' : 'bg-zinc-200 dark:bg-[var(--surface-border)]'}`} />}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {expanded && <TaskDiagnostics task={task} system={system} logs={logs} />}
    </article>
  );
}
