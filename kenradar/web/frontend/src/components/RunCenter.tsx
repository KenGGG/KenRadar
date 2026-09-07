import { useEffect, useMemo, useState } from 'react';
import { ArrowRight, ChevronDown, ChevronLeft, ChevronRight, Pause, Play, Plus, RefreshCw } from 'lucide-react';
import { AlertRecord, PushRecord, SystemInfo, SystemLog, VideoContent } from '../types';
import SystemMonitor, { SystemMonitorTab } from './SystemMonitor';
import { contentIssueKind, DurableTask, initialRunSection, RunCenterData, RunSection, SECTION_LABELS, SECTION_STATUSES, STATUS_LABELS, taskPresentation } from './RunCenterModel';

const panel = 'rounded-xl border border-[var(--surface-border)] bg-[var(--surface)]';
const button = 'inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-[var(--surface-border)] px-3 text-sm hover:bg-[var(--surface-muted)] disabled:opacity-40 disabled:cursor-not-allowed';
const muted = 'text-[var(--text-muted)]';
const PAGE_SIZE = 25;

function time(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { credentials: 'same-origin', ...init });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.message || `请求失败 (${response.status})`);
  return data;
}

function monitorTab(): SystemMonitorTab | undefined {
  const path = window.location.pathname;
  const params = new URLSearchParams(window.location.search);
  if (path.includes('push') || path.startsWith('/publish') || params.get('section') === 'publishing' || params.get('tab') === 'history') return 'push';
  if (path.includes('alerts')) return 'alerts';
  if (path.includes('runtime') || params.get('section') === 'logs') return 'logs';
  if (path.startsWith('/logs') || path.startsWith('/ops')) return 'status';
}

function TaskRow({ task, busy, onControl }: { task: DurableTask; busy: boolean; onControl: (task: DurableTask, action: 'pause' | 'resume') => void }) {
  const view = taskPresentation(task);
  const tone = task.display_status === 'running' ? 'text-blue-600 bg-blue-500/10'
    : ['failed', 'partial_failed', 'interrupted'].includes(task.display_status) ? 'text-amber-600 bg-amber-500/10'
    : task.display_status === 'success' ? 'text-emerald-600 bg-emerald-500/10' : 'text-[var(--text-secondary)] bg-[var(--surface-muted)]';
  return (
    <details className="group border-t border-[var(--surface-border)] first:border-t-0">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-4 hover:bg-[var(--surface-muted)] focus-visible:outline-blue-500">
        <ChevronRight className={`h-4 w-4 shrink-0 group-open:rotate-90 ${muted}`} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={muted}>#{task.id} · {task.task_label}</span>
            <span className={`rounded-full px-2 py-0.5 font-medium ${tone}`}>{view.label}</span>
          </div>
          <p className="mt-1 truncate text-sm font-medium" title={task.message}>{task.message || task.task_label}</p>
        </div>
        <span className={`hidden shrink-0 text-right text-xs sm:block ${muted}`}>
          {time(task.updated_at)}<br /><span className="leading-6">尝试 {task.attempt}/{task.max_attempts}</span>
        </span>
      </summary>
      <div className="space-y-4 bg-[var(--surface-muted)] px-5 pb-5 pt-3 sm:pl-11">
        <p className="text-sm leading-6">{view.hint}</p>
        {task.status !== task.display_status && <p className={`text-xs ${muted}`}>原始记录：{STATUS_LABELS[task.status] || task.status} · 当前分类依据执行结果、租约或功能退役情况。</p>}
        {task.last_error && ['failed', 'partial_failed', 'interrupted', 'retired'].includes(task.display_status) && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3">
            <p className="text-xs font-medium text-amber-600">上次错误{task.error_code ? ` · ${task.error_code}` : ''}</p>
            <p className="mt-2 whitespace-pre-wrap break-words text-sm">{task.last_error}</p>
          </div>
        )}
        <dl className="grid grid-cols-2 gap-3 text-xs lg:grid-cols-4">
          {([['创建时间', task.created_at], ['开始时间', task.started_at], ['最近心跳', task.heartbeat_at],
            [task.display_status === 'retry_wait' ? '下次尝试' : '结束时间', task.display_status === 'retry_wait' ? task.available_at : task.finished_at]] as const).map(([label, value]) => (
            <div key={label}><dt className={muted}>{label}</dt><dd className="mt-1">{time(value)}</dd></div>
          ))}
        </dl>
        {task.progress_json && Object.keys(task.progress_json).length > 0 && (
          <details className="text-xs"><summary className="cursor-pointer">步骤进度</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all">{JSON.stringify(task.progress_json, null, 2)}</pre></details>
        )}
        {view.action && <button className={button} disabled={busy} onClick={() => onControl(task, view.action!)}>
          {view.action === 'pause' ? <Pause size={14} /> : <Play size={14} />}{view.action === 'pause' ? '暂停任务' : '继续任务'}
        </button>}
      </div>
    </details>
  );
}

interface Props {
  videos: VideoContent[];
  pushRecords: PushRecord[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  rebootWebUI: () => void;
  triggerManualScan: () => void;
}

export default function RunCenter({ videos, pushRecords, logs, alerts, system, rebootWebUI, triggerManualScan }: Props) {
  const [section, setSection] = useState<RunSection>(() => initialRunSection(window.location.pathname, window.location.search));
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(0);
  const [revision, setRevision] = useState(0);
  const [snapshot, setSnapshot] = useState<{ key: string; data: RunCenterData; at: string }>();
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [initialMonitor] = useState(monitorTab);
  const [monitorOpen, setMonitorOpen] = useState(Boolean(initialMonitor));
  const [issueKind, setIssueKind] = useState('degraded');
  const [issuePage, setIssuePage] = useState(0);
  const query = new URLSearchParams({ section, status, limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) }).toString();
  const data = snapshot?.key === query ? snapshot.data : undefined;

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      setRefreshing(true);
      try {
        const result = await request<RunCenterData>(`/api/run-center?${query}`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]) });
        if (controller.signal.aborted) return;
        setSnapshot({ key: query, data: result, at: new Date().toLocaleTimeString('zh-CN') });
        setError('');
        if (page > 0 && page * PAGE_SIZE >= result.total) setPage(Math.max(0, Math.ceil(result.total / PAGE_SIZE) - 1));
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : '任务状态读取失败');
      } finally {
        if (!controller.signal.aborted) {
          setRefreshing(false);
          timer = setTimeout(refresh, 10000);
        }
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [query, revision, page]);

  function selectSection(next: RunSection) {
    setSection(next); setStatus(''); setPage(0); setNotice('');
    const url = new URL(window.location.href);
    url.searchParams.set('view', next);
    window.history.replaceState(null, '', url);
  }

  async function control(task: DurableTask, action: 'pause' | 'resume') {
    if (busy) return;
    setBusy(true); setNotice('');
    try {
      const result = await request<{ message: string }>(`/api/task-${action}?id=${task.id}`, { method: 'POST', signal: AbortSignal.timeout(15000) });
      setNotice(result.message);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : '操作未完成，请刷新后核实任务状态');
    } finally { setBusy(false); setRevision(n => n + 1); }
  }

  const contentIssues = useMemo(() => videos.filter(v => contentIssueKind(v) === issueKind), [videos, issueKind]);
  const descriptions: Record<RunSection, string> = {
    active: '按执行优先级排列。自动重试有独立状态；内容条目和研究批次不重复计数。',
    attention: '先看失败原因，再决定操作。已暂停和等待回收分别筛选，不算作正在执行。',
    history: '成功、取消和已退役功能分别留档。历史记录保留原始状态，便于追溯。',
  };

  return (
    <div className="space-y-5 text-[var(--text-primary)]">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div><h1 className="text-2xl font-semibold tracking-tight">处理中心</h1><p className={`mt-2 text-sm ${muted}`}>从排队到完成，按一次实际执行追踪任务。</p></div>
        <div className="flex gap-2"><a href="/research" className={button}>查看研究批次 <ArrowRight size={14} /></a><a href="/process" className={`${button} bg-[var(--surface-muted)]`}><Plus size={14} />处理新链接</a></div>
      </header>

      <div className={`flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-xs ${panel} ${muted}`}>
        <span>定时检测：{String(system.health?.schedule || '未知')} · 下次运行：{String(system.health?.next_run || '暂无')}</span>
        <span aria-live="polite">{error ? '连接异常，已有数据可能过期' : snapshot ? `更新于 ${snapshot.at} · 每 10 秒刷新` : '正在连接任务服务'}</span>
      </div>

      <nav aria-label="任务分组" className="grid grid-cols-3 gap-3">
        {(Object.keys(SECTION_LABELS) as RunSection[]).map(key => <button key={key} type="button" aria-pressed={section === key} onClick={() => selectSection(key)}
          className={`${panel} p-4 text-left transition ${section === key ? 'ring-2 ring-blue-500 border-transparent' : 'hover:bg-[var(--surface-muted)]'}`}>
          <span className={`text-xs sm:text-sm ${muted}`}>{SECTION_LABELS[key]}</span>
          <span className="mt-2 block text-2xl font-semibold tabular-nums">{snapshot?.data.counts[key] ?? '—'}</span>
        </button>)}
      </nav>

      <section className={panel} aria-label={SECTION_LABELS[section]} aria-busy={!data && refreshing}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4">
          <div><h2 className="text-base font-semibold">{SECTION_LABELS[section]}</h2><p className={`mt-1 text-xs leading-5 ${muted}`}>{descriptions[section]}</p></div>
          <div className="flex gap-2">
            <select aria-label="按任务状态筛选" value={status} onChange={e => { setStatus(e.target.value); setPage(0); }} className={`${button} bg-[var(--surface)]`}>
              <option value="">全部状态</option>{SECTION_STATUSES[section].map(value => <option key={value} value={value}>{STATUS_LABELS[value]}</option>)}
            </select>
            <button aria-label="刷新任务" className={button} disabled={refreshing} onClick={() => setRevision(n => n + 1)}><RefreshCw size={15} className={refreshing ? 'animate-spin' : ''} /></button>
          </div>
        </div>
        {error && <p role="alert" className="mx-4 mb-4 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-700">无法获取最新任务：{error}。将自动重连，也可点击刷新。</p>}
        {notice && <p role="status" className="mx-4 mb-4 rounded-lg bg-blue-500/10 p-3 text-sm">{notice}</p>}
        {!data ? <p className={`p-10 text-center text-sm ${muted}`}>{error ? '任务数据暂不可用' : '正在读取任务…'}</p>
          : data.items.length === 0 ? <div className={`p-12 text-center text-sm ${muted}`}>{status ? '没有符合筛选条件的任务。' : section === 'active' ? '队列空闲，等待新任务或下一次定时检测。' : section === 'attention' ? '暂无需要处理的执行任务。' : '暂无历史记录。'}</div>
          : <div>{data.items.map(task => <TaskRow key={task.id} task={task} busy={busy || Boolean(error)} onControl={control} />)}</div>}
        <footer className={`flex items-center justify-between border-t border-[var(--surface-border)] px-4 py-3 text-xs ${muted}`}>
          <span>共 {data?.total ?? '—'} 项 · 每页 {PAGE_SIZE} 项</span>
          <div className="flex items-center gap-2"><button aria-label="上一页" className={button} disabled={page === 0 || !data} onClick={() => setPage(p => p - 1)}><ChevronLeft size={14} /></button>
            <span>{page + 1} / {Math.max(1, Math.ceil((data?.total || 0) / PAGE_SIZE))}</span>
            <button aria-label="下一页" className={button} disabled={!data || (page + 1) * PAGE_SIZE >= data.total} onClick={() => setPage(p => p + 1)}><ChevronRight size={14} /></button></div>
        </footer>
      </section>

      {section === 'attention' && <details className={panel}>
        <summary className="flex cursor-pointer list-none items-center justify-between p-4 text-sm font-medium">内容质量与交付问题 <ChevronDown size={15} /></summary>
        <div className="space-y-3 border-t border-[var(--surface-border)] p-4">
          <p className={`text-xs leading-5 ${muted}`}>这是已载入内容的结果检查，不计入执行任务数量。降级笔记可阅读，但不代表 AI 整理成功；请在内容详情中检查后按需重试。</p>
          <select aria-label="内容问题分类" value={issueKind} onChange={e => { setIssueKind(e.target.value); setIssuePage(0); }} className={`${button} bg-[var(--surface)]`}>
            <option value="degraded">AI 降级笔记</option><option value="delivery">发布 / 推送失败</option><option value="failure">内容处理失败</option>
          </select>
          {contentIssues.slice(issuePage * 10, (issuePage + 1) * 10).map(video => <a key={`${video.platform}:${video.id}`} href={`/content?platform=${encodeURIComponent(video.platform || 'douyin')}&external_id=${encodeURIComponent(video.id)}`} className="flex items-center justify-between gap-3 rounded-lg bg-[var(--surface-muted)] p-3 text-sm hover:underline">
            <span className="min-w-0"><span className="block truncate">{video.title}</span><span className={`text-xs ${muted}`}>{video.blogger} · 查看内容详情</span></span><ArrowRight size={15} className="shrink-0" /></a>)}
          <div className={`flex items-center justify-between text-xs ${muted}`}><span>已载入内容中共 {contentIssues.length} 条</span><div className="flex gap-2"><button className={button} disabled={!issuePage} onClick={() => setIssuePage(p => p - 1)}>上一页</button><button className={button} disabled={(issuePage + 1) * 10 >= contentIssues.length} onClick={() => setIssuePage(p => p + 1)}>下一页</button></div></div>
        </div>
      </details>}

      <details className={panel} open={monitorOpen} onToggle={e => setMonitorOpen(e.currentTarget.open)}>
        <summary className="flex cursor-pointer list-none items-center justify-between p-4 text-sm font-medium">系统状态、通知与日志 <ChevronDown size={15} /></summary>
        {monitorOpen && <div className="border-t border-[var(--surface-border)] p-4"><SystemMonitor hideHeader initialTab={initialMonitor} pushRecords={pushRecords} logs={logs} alerts={alerts} system={system} rebootWebUI={rebootWebUI} triggerManualScan={triggerManualScan} /></div>}
      </details>
    </div>
  );
}
