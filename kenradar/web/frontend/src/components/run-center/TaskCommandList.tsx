import { useEffect, useState } from 'react';
import { RunTaskView } from '../RunCenterModel';
import { SystemInfo, SystemLog } from '../../types';
import { EmptyState } from '../UITokens';
import TaskCommandCard from './TaskCommandCard';

export default function TaskCommandList({ taskViews, system, logs, onRepair }: {
  taskViews: RunTaskView[];
  system: SystemInfo;
  logs: SystemLog[];
  onRepair: (taskId: string) => void;
}) {
  const preferred = taskViews.find(view => view.state === 'failed' || view.state === 'running')?.task.id || null;
  const [expandedId, setExpandedId] = useState<string | null>(preferred);
  const [showAllCompleted, setShowAllCompleted] = useState(false);
  const activeViews = taskViews.filter(view => view.state !== 'completed');
  const completedViews = taskViews.filter(view => view.state === 'completed');
  const visibleViews = [...activeViews, ...(showAllCompleted ? completedViews : completedViews.slice(0, 8))];

  useEffect(() => {
    if (expandedId && !taskViews.some(view => view.task.id === expandedId)) setExpandedId(preferred);
  }, [expandedId, preferred, taskViews]);

  if (taskViews.length === 0) return <EmptyState title="暂无后台任务" description="等待定时检测，或从首页启动一次手动检测。" />;

  return (
    <section>
      <div className="mb-3 flex items-end justify-between gap-3">
        <div><h2 className="text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)]">后台任务</h2><p className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">异常优先，其次显示运行中、排队和最近完成的任务。</p></div>
        <span className="text-xs font-mono text-zinc-400 dark:text-[var(--text-muted)]">{taskViews.length} 个批次</span>
      </div>
      <div className="space-y-3">
        {visibleViews.map(view => <TaskCommandCard key={view.task.id} view={view} expanded={expandedId === view.task.id} onToggle={() => setExpandedId(current => current === view.task.id ? null : view.task.id)} onRepair={() => onRepair(view.task.id)} system={system} logs={logs} />)}
        {completedViews.length > 8 && (
          <button type="button" onClick={() => setShowAllCompleted(value => !value)} className="w-full rounded-lg border border-dashed border-zinc-250 bg-zinc-50 px-4 py-3 text-xs font-medium text-zinc-600 hover:border-zinc-400 hover:bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] dark:text-[var(--text-secondary)] dark:hover:bg-[var(--surface)] cursor-pointer">
            {showAllCompleted ? '收起历史任务' : `展开其余 ${completedViews.length - 8} 个已完成任务`}
          </button>
        )}
      </div>
    </section>
  );
}
