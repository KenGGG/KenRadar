import { LockKeyhole, Terminal } from 'lucide-react';
import { normalizeRuntimeTimeline } from '../RunCenterModel';
import { ResearchTask, SystemInfo, SystemLog } from '../../types';

export default function TaskDiagnostics({ task, system, logs }: { task: ResearchTask; system: SystemInfo; logs: SystemLog[] }) {
  const timeline = normalizeRuntimeTimeline(system.runtime_timeline);
  const relevantLogs = logs
    .filter(log => !task.target || log.message.includes(task.target) || /任务|下载|转录|AI|笔记|发布|飞书/.test(log.message))
    .slice(0, 6);
  const counts = [
    ['总计', task.total_items],
    ['完成', task.completed_items],
    ['失败', task.failed_items],
    ['跳过', task.skipped_items],
  ];

  return (
    <div className="grid gap-4 border-t border-zinc-100 bg-zinc-50/60 p-4 dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.8fr)]">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {counts.map(([label, value]) => (
            <div key={label} className="rounded-md border border-zinc-200 bg-white px-3 py-2 dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
              <div className="text-[10px] text-zinc-500 dark:text-[var(--text-muted)]">{label}</div>
              <div className="mt-1 font-mono text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{value ?? '—'}</div>
            </div>
          ))}
        </div>

        {(timeline?.locks?.length || timeline?.lanes?.length) ? (
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-zinc-700 dark:text-[var(--text-secondary)]">
              <LockKeyhole className="h-3.5 w-3.5" />资源与队列
            </h4>
            <div className="grid gap-2 sm:grid-cols-2">
              {(timeline?.locks || []).map((lock: any) => (
                <div key={lock.key} className="rounded-md border border-zinc-200 bg-white px-3 py-2 text-xs dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
                  <div className="font-semibold text-zinc-800 dark:text-[var(--text-primary)]">{lock.label} · {lock.status === 'busy' ? '占用中' : lock.status === 'blocked' ? '等待' : '空闲'}</div>
                  <div className="mt-1 truncate text-zinc-500 dark:text-[var(--text-muted)]">{lock.holder || lock.detail || '无占用'}</div>
                </div>
              ))}
              {(timeline?.lanes || []).map((lane: any) => (
                <div key={lane.key} className="rounded-md border border-zinc-200 bg-white px-3 py-2 text-xs dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
                  <div className="font-semibold text-zinc-800 dark:text-[var(--text-primary)]">{lane.label}</div>
                  <div className="mt-1 text-zinc-500 dark:text-[var(--text-muted)]">运行 {lane.active || 0} · 等待 {lane.waiting || 0} · 容量 {lane.capacity || 1}</div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div>
        <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-zinc-700 dark:text-[var(--text-secondary)]">
          <Terminal className="h-3.5 w-3.5" />最近相关日志
        </h4>
        <div className="max-h-52 space-y-2 overflow-auto rounded-md border border-zinc-200 bg-zinc-950 p-3 font-mono text-[11px] leading-5 text-zinc-300 dark:border-[var(--surface-border)]">
          {relevantLogs.length === 0 ? <div className="text-zinc-500">暂无相关日志</div> : relevantLogs.map(log => (
            <div key={log.id}><span className="text-zinc-500">{log.timestamp}</span> <span className={log.level === 'error' ? 'text-red-400' : log.level === 'warn' ? 'text-amber-300' : 'text-zinc-300'}>{log.message}</span></div>
          ))}
        </div>
      </div>
    </div>
  );
}
