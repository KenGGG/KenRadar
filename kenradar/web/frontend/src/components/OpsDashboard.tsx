/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Eye,
  FileText,
  RefreshCw,
  RotateCw,
  Search,
  SlidersHorizontal,
} from 'lucide-react';
import { VideoContent } from '../types';

type WorkbenchTab = 'tasks' | 'retry';
type StageKey = 'download' | 'transcribe' | 'ai' | 'note' | 'push';
type StageState = 'success' | 'failed' | 'processing' | 'queued' | 'unknown';
type StatusFilter = 'active' | 'all' | VideoContent['status'];

interface OpsDashboardProps {
  videos: VideoContent[];
  retryStage: (id: string, stage?: 'download' | 'transcribe' | 'ai' | 'push') => void;
  bulkRetryFailed: (step?: 'download' | 'transcribe' | 'ai' | 'push') => void;
  triggerManualScan: () => void;
  navigateTo?: (page: string, id: string | null) => void;
  initialTab?: WorkbenchTab;
  hideHeader?: boolean;
  hideTabs?: boolean;
  hideStats?: boolean;
  retryMode?: boolean; /* when true: group failures by stage, simplify filters */
}

type PipelineStep = {
  key: StageKey;
  label: string;
  state: StageState;
};

const STAGE_LABELS: Record<StageKey, string> = {
  download: '下载',
  transcribe: '转录',
  ai: 'AI',
  note: '笔记',
  push: '推送',
};

const STATUS_LABELS: Record<VideoContent['status'], string> = {
  completed: '已完成',
  failed: '失败待处理',
  processing: '处理中',
  queued: '待处理',
};

const ACTION_LABELS: Record<string, string> = {
  push: '推送',
  skip: '跳过',
  review: '复核',
  research: '研究',
  archive: '归档',
};

function normalizeStepState(value?: string): StageState {
  const state = String(value || '').toLowerCase();
  if (['success', 'done', 'completed', 'ok'].includes(state)) return 'success';
  if (['failed', 'error', 'fail'].includes(state)) return 'failed';
  if (['processing', 'running', 'in_progress'].includes(state)) return 'processing';
  if (['queued', 'pending', 'waiting'].includes(state)) return 'queued';
  return 'unknown';
}

function stageFromFailedStep(step?: VideoContent['failed_at_step']): 'download' | 'transcribe' | 'ai' | 'push' | undefined {
  if (step === 'download' || step === 'transcribe' || step === 'ai' || step === 'push') return step;
  return undefined;
}

function pipelineFor(video: VideoContent): PipelineStep[] {
  if (video.pipeline_steps?.length) {
    return video.pipeline_steps.map(step => ({
      key: step.key,
      label: step.label || STAGE_LABELS[step.key],
      state: normalizeStepState(step.state),
    }));
  }

  const failedStage = video.failed_at_step;
  if (video.status === 'completed') {
    return [
      { key: 'download', label: '下载', state: 'success' },
      { key: 'transcribe', label: '转录', state: 'success' },
      { key: 'ai', label: 'AI', state: 'success' },
      { key: 'note', label: '笔记', state: video.summary_markdown ? 'success' : 'unknown' },
      { key: 'push', label: '推送', state: video.push_status === 'success' ? 'success' : normalizeStepState(video.push_status) },
    ];
  }

  const steps: PipelineStep[] = [
    { key: 'download', label: '下载', state: normalizeStepState(video.download_status) },
    { key: 'transcribe', label: '转录', state: normalizeStepState(video.transcript_status) },
    { key: 'ai', label: 'AI', state: normalizeStepState(video.summary_status) },
    { key: 'note', label: '笔记', state: video.summary_path ? 'success' : normalizeStepState(video.summary_status) },
    { key: 'push', label: '推送', state: normalizeStepState(video.push_status) },
  ];

  if (failedStage) {
    const key = failedStage === 'transcribe' ? 'transcribe' : failedStage;
    return steps.map(step => step.key === key ? { ...step, state: 'failed' } : step);
  }
  return steps;
}

function currentStage(video: VideoContent): string {
  const explicit = video.current_stage;
  if (explicit && STAGE_LABELS[explicit as StageKey]) return STAGE_LABELS[explicit as StageKey];
  const failed = stageFromFailedStep(video.failed_at_step);
  if (failed) return STAGE_LABELS[failed === 'transcribe' ? 'transcribe' : failed];
  const active = pipelineFor(video).find(step => step.state === 'processing' || step.state === 'failed' || step.state === 'queued');
  return active?.label || '完成';
}

function scoreText(video: VideoContent) {
  return video.rating > 0 ? video.rating.toFixed(1) : '-';
}

function isToday(value: string) {
  if (!value) return false;
  const date = new Date(value.replace(/-/g, '/'));
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
}

function sortVideos(a: VideoContent, b: VideoContent) {
  const priority: Record<VideoContent['status'], number> = { failed: 0, processing: 1, queued: 2, completed: 3 };
  const byStatus = priority[a.status] - priority[b.status];
  if (byStatus !== 0) return byStatus;
  return String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at));
}

function statusBadge(status: VideoContent['status']) {
  const classes = {
    completed: 'bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-700 dark:text-[var(--success)] border-emerald-100 dark:border-[var(--success-border)]',
    failed: 'bg-red-50 dark:bg-[var(--danger-bg)] text-red-700 dark:text-[var(--danger)] border-red-100 dark:border-[var(--danger-border)]',
    processing: 'bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)] border-blue-100 dark:border-[var(--info-border)]',
    queued: 'bg-zinc-50 dark:bg-[var(--surface)] text-zinc-600 dark:text-[var(--text-secondary)] border-zinc-200 dark:border-[var(--surface-border)]',
  }[status];
  return <span className={`inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium ${classes}`}>{STATUS_LABELS[status]}</span>;
}

function stepClass(state: StageState) {
  return {
    success: 'border-emerald-200 dark:border-[var(--success-border)] bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-700 dark:text-[var(--success)]',
    failed: 'border-red-200 dark:border-[var(--danger-border)] bg-red-50 dark:bg-[var(--danger-bg)] text-red-700 dark:text-[var(--danger)]',
    processing: 'border-blue-200 dark:border-[var(--info-border)] bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)]',
    queued: 'border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface)] text-zinc-500 dark:text-[var(--text-secondary)]',
    unknown: 'border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-zinc-400 dark:text-[var(--text-muted)]',
  }[state];
}

export default function OpsDashboard({
  videos,
  retryStage,
  bulkRetryFailed,
  triggerManualScan,
  navigateTo,
  initialTab = 'tasks',
  hideHeader = false,
  hideTabs = false,
  hideStats = false,
  retryMode = false,
}: OpsDashboardProps) {
  const [activeTab, setActiveTab] = useState<WorkbenchTab>(initialTab);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('active');
  const [stageFilter, setStageFilter] = useState<'all' | StageKey>('all');
  const [actionFilter, setActionFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [retryFrom, setRetryFrom] = useState<'auto' | 'download' | 'transcribe' | 'ai'>('auto');

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  const sources = useMemo(() => {
    return Array.from(new Set(videos.map(video => video.blogger).filter(Boolean))).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }, [videos]);

  const filteredVideos = useMemo(() => {
    const q = query.trim().toLowerCase();
    return videos
      .filter(video => statusFilter === 'all' || statusFilter === 'active' || video.status === statusFilter)
      .filter(video => statusFilter !== 'active' || video.status !== 'completed')
      .filter(video => sourceFilter === 'all' || video.blogger === sourceFilter)
      .filter(video => actionFilter === 'all' || video.recommend_action === actionFilter)
      .filter(video => stageFilter === 'all' || pipelineFor(video).some(step => step.key === stageFilter && step.state !== 'success'))
      .filter(video => {
        if (!q) return true;
        return [video.id, video.title, video.blogger, ...(video.tags || [])].join(' ').toLowerCase().includes(q);
      })
      .sort(sortVideos);
  }, [videos, statusFilter, sourceFilter, actionFilter, stageFilter, query]);

  const failedVideos = useMemo(() => filteredVideos.filter(video => video.status === 'failed'), [filteredVideos]);

  /* ── Stage-grouped failures for retryMode ── */
  const stageGroups = useMemo(() => {
    const groups: Record<string, { key: string; label: string; videos: VideoContent[]; errors: Map<string, number> }> = {};
    const STAGES = ['download', 'transcribe', 'ai', 'push'] as const;
    for (const stage of STAGES) {
      const stageVideos = failedVideos.filter(v => {
        const step = v.failed_at_step || v.failure_stage;
        return step === stage;
      });
      if (stageVideos.length === 0) continue;
      const errors = new Map<string, number>();
      stageVideos.forEach(v => {
        const msg = v.error_message || '未知错误';
        errors.set(msg, (errors.get(msg) || 0) + 1);
      });
      groups[stage] = { key: stage, label: STAGE_LABELS[stage], videos: stageVideos, errors };
    }
    // unclassified
    const unclassified = failedVideos.filter(v => {
      const step = v.failed_at_step || v.failure_stage;
      return !step || !(step in STAGES);
    });
    if (unclassified.length > 0) {
      const errors = new Map<string, number>();
      unclassified.forEach(v => {
        const msg = v.error_message || '未知错误';
        errors.set(msg, (errors.get(msg) || 0) + 1);
      });
      groups['other'] = { key: 'other', label: '其他', videos: unclassified, errors };
    }
    return groups;
  }, [failedVideos]);

  const stats = useMemo(() => ({
    processing: videos.filter(video => video.status === 'processing').length,
    completed: videos.filter(video => video.status === 'completed').length,
    failed: videos.filter(video => video.status === 'failed').length,
    today: videos.filter(video => isToday(video.created_at)).length,
  }), [videos]);

  const submitBulkRetry = () => {
    if (!failedVideos.length) return;
    if (retryFrom === 'auto') {
      bulkRetryFailed();
      return;
    }
    bulkRetryFailed(retryFrom);
  };

  const goDetail = (id: string) => {
    if (navigateTo) {
      navigateTo('detail', id);
      return;
    }
    window.history.pushState(null, '', `/content?platform=douyin&external_id=${encodeURIComponent(id)}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {!hideHeader && (
      <div className="border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">处理队列</h1>
          <p className="text-zinc-500 dark:text-[var(--text-secondary)] font-sans text-sm mt-1">按内容查看处理进度，集中处理下载、转录、AI 和笔记失败。</p>
        </div>
        <button
          onClick={triggerManualScan}
          className="flex items-center gap-1.5 px-3 py-2 border border-zinc-200 dark:border-[var(--surface-border)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] rounded text-xs font-sans font-medium text-zinc-700 transition cursor-pointer"
        >
          <RotateCw className="w-3.5 h-3.5" />
          <span>手动全量检测</span>
        </button>
      </div>
      )}

      {!hideStats && <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: '处理中', value: stats.processing, icon: Clock3 },
          { label: '已完成', value: stats.completed, icon: CheckCircle2 },
          { label: '失败待处理', value: stats.failed, icon: AlertTriangle },
          { label: '今日新增', value: stats.today, icon: FileText },
        ].map(item => {
          const Icon = item.icon;
          return (
            <div key={item.label} className="bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg p-4 shadow-2xs">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-medium">{item.label}</span>
                <Icon className="w-4 h-4 text-zinc-400 dark:text-[var(--text-muted)]" />
              </div>
              <div className="text-2xl font-semibold tabular-nums text-zinc-950 dark:text-[var(--text-primary)]">{item.value}</div>
            </div>
          );
        })}
      </div>}

      {!hideTabs && (
      <div className="flex border-b border-zinc-200 dark:border-[var(--surface-border)] gap-6">
        <button
          onClick={() => setActiveTab('tasks')}
          className={`pb-3 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
            activeTab === 'tasks' ? 'text-zinc-950 dark:text-[var(--text-primary)]' : 'text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-700 dark:hover:text-[var(--text-secondary)]'
          }`}
        >
          内容任务
          {activeTab === 'tasks' && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--accent)] rounded" />}
        </button>
        <button
          onClick={() => setActiveTab('retry')}
          className={`pb-3 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
            activeTab === 'retry' ? 'text-zinc-950 dark:text-[var(--text-primary)]' : 'text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-700 dark:hover:text-[var(--text-secondary)]'
          }`}
        >
          失败重试
          {stats.failed > 0 && <span className="ml-2 rounded-full bg-red-50 dark:bg-[var(--danger-bg)] px-1.5 py-0.5 text-[10px] text-red-700 dark:text-[var(--danger)]">{stats.failed}</span>}
          {activeTab === 'retry' && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--accent)] rounded" />}
        </button>
      </div>
      )}

      <div className="bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg p-4">
        <div className={`grid grid-cols-1 gap-3 ${retryMode ? 'md:grid-cols-4' : 'md:grid-cols-5'}`}>
          <label className="space-y-1">
            <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-medium">状态</span>
            <select value={statusFilter} onChange={event => setStatusFilter(event.target.value as StatusFilter)} className="w-full rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
              <option value="active">运行中 / 失败 / 待处理</option>
              <option value="all">全部状态</option>
              <option value="failed">失败待处理</option>
              <option value="processing">处理中</option>
              <option value="queued">待处理</option>
              <option value="completed">已完成</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-500 font-medium">阶段</span>
            <select value={stageFilter} onChange={event => setStageFilter(event.target.value as any)} className="w-full rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
              <option value="all">全部阶段</option>
              <option value="download">下载</option>
              <option value="transcribe">转录</option>
              <option value="ai">AI</option>
              <option value="note">笔记</option>
              <option value="push">推送</option>
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-xs text-zinc-500 font-medium">来源</span>
            <select value={sourceFilter} onChange={event => setSourceFilter(event.target.value)} className="w-full rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
              <option value="all">全部来源</option>
              {sources.map(source => <option key={source} value={source}>{source}</option>)}
            </select>
          </label>
          {!retryMode && (
          <label className="space-y-1">
            <span className="text-xs text-zinc-500 font-medium">推荐动作</span>
            <select value={actionFilter} onChange={event => setActionFilter(event.target.value)} className="w-full rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
              <option value="all">全部动作</option>
              {Object.entries(ACTION_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          )}
          <label className="space-y-1">
            <span className="text-xs text-zinc-500 font-medium">关键词</span>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 w-4 h-4 text-zinc-400 dark:text-[var(--text-muted)]" />
              <input
                value={query}
                onChange={event => setQuery(event.target.value)}
                placeholder="标题 / 博主 / ID"
                className="w-full rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] py-2 pl-8 pr-3 text-sm"
              />
            </div>
          </label>
        </div>
      </div>

      {activeTab === 'tasks' && (
        <div className="bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg overflow-hidden">
          {filteredVideos.length === 0 ? (
            <div className="p-12 text-center text-zinc-500 dark:text-[var(--text-secondary)]">
              <FileText className="w-9 h-9 mx-auto mb-3 text-zinc-300 dark:text-[var(--text-muted)]" />
              <p className="text-sm font-medium text-zinc-800 dark:text-[var(--text-primary)]">暂无匹配的内容任务</p>
              <p className="text-xs mt-1">调整筛选条件或发起一次手动检测。</p>
            </div>
          ) : (
            <div className="divide-zinc-100 dark:divide-[var(--surface-border)]">
              {filteredVideos.map(video => (
                <div key={video.id} className="p-4 hover:bg-zinc-50/60 dark:hover:bg-[var(--surface-muted)] transition">
                  <div className="flex flex-col xl:flex-row xl:items-center gap-4">
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        {statusBadge(video.status)}
                        <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-mono">ID {video.id}</span>
                        <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{video.blogger || '未知来源'}</span>
                        <span className="text-xs text-zinc-400">{video.created_at || '时间未知'}</span>
                      </div>
                      <h3 className="text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)] leading-snug">{video.title || '无标题'}</h3>
                      <div className="flex flex-wrap gap-2 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                        <span>评分 {scoreText(video)}</span>
                        <span>推荐 {ACTION_LABELS[video.recommend_action] || '待判断'}</span>
                        <span>当前阶段 {currentStage(video)}</span>
                        <span>更新 {video.updated_at || video.created_at || '-'}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5 xl:w-[360px]">
                      {pipelineFor(video).map(step => (
                        <span key={step.key} className={`inline-flex min-w-14 justify-center rounded border px-2 py-1 text-xs font-medium ${stepClass(step.state)}`}>
                          {step.label}
                        </span>
                      ))}
                    </div>
                    <div className="flex gap-2 shrink-0">
                      <button onClick={() => goDetail(video.id)} className="inline-flex items-center gap-1.5 rounded border border-zinc-200 dark:border-[var(--surface-border)] px-3 py-2 text-xs font-medium text-zinc-700 dark:text-[var(--text-secondary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] cursor-pointer">
                        <Eye className="w-3.5 h-3.5" />
                        查看详情
                      </button>
                      {video.status === 'failed' && (
                        <button onClick={() => retryStage(video.id, stageFromFailedStep(video.failed_at_step))} className="inline-flex items-center gap-1.5 rounded bg-zinc-950 dark:bg-[var(--surface-border)] px-3 py-2 text-xs font-medium text-white dark:text-zinc-200 hover:bg-zinc-800 dark:hover:bg-[var(--text-muted)] cursor-pointer">
                          <RefreshCw className="w-3.5 h-3.5" />
                          重试当前阶段
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'retry' && (
        <div className="space-y-4">
          <div className="bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm text-zinc-600 dark:text-[var(--text-secondary)]">
              <SlidersHorizontal className="w-4 h-4 text-zinc-400 dark:text-[var(--text-muted)]" />
              <span>当前筛选下有 {failedVideos.length} 条失败内容可处理</span>
            </div>
            <div className="flex flex-col sm:flex-row gap-2">
              <select value={retryFrom} onChange={event => setRetryFrom(event.target.value as any)} className="rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
                <option value="auto">智能重试</option>
                <option value="download">从下载开始</option>
                <option value="transcribe">从转录开始</option>
                <option value="ai">从 AI/笔记开始</option>
              </select>
              <button
                disabled={!failedVideos.length}
                onClick={submitBulkRetry}
                className="inline-flex items-center justify-center gap-1.5 rounded bg-zinc-950 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
              >
                <RefreshCw className="w-4 h-4" />
                批量重试当前筛选
              </button>
            </div>
          </div>

          {Object.keys(stageGroups).length === 0 ? (
            <div className="bg-white border border-zinc-200 rounded-lg p-12 text-center text-zinc-500 dark:text-[var(--text-secondary)]">
              <CheckCircle2 className="w-10 h-10 mx-auto text-emerald-500 dark:text-[var(--success)] mb-3" />
              <p className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">暂无匹配的失败任务</p>
              <p className="text-xs mt-1">当前筛选条件下没有需要重试的内容。</p>
            </div>
          ) : (
            <div className="space-y-4">
              {Object.entries(stageGroups).map(([stageKey, group]) => (
                <div key={stageKey} className="bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg overflow-hidden">
                  <div className="flex items-center justify-between gap-3 border-b border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-5 py-3">
                    <div className="flex items-center gap-2">
                      <span className={`rounded border px-2 py-0.5 text-xs font-medium ${
                        stageKey === 'download' ? 'border-red-100 dark:border-[var(--danger-border)] bg-red-50 dark:bg-[var(--danger-bg)] text-red-700 dark:text-[var(--danger)]' :
                        stageKey === 'transcribe' ? 'border-amber-100 dark:border-[var(--warning-border)] bg-amber-50 dark:bg-[var(--warning-bg)] text-amber-700 dark:text-[var(--warning)]' :
                        stageKey === 'ai' ? 'border-purple-100 dark:border-[var(--surface-border)] bg-purple-50 dark:bg-[var(--surface-muted)] text-purple-700 dark:text-[var(--text-secondary)]' :
                        stageKey === 'push' ? 'border-blue-100 dark:border-[var(--info-border)] bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)]' :
                        'border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface)] text-zinc-600 dark:text-[var(--text-secondary)]'
                      }`}>{stageKey === 'other' ? '其他' : `${group.label}失败`}</span>
                      <span className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">已加载 {group.videos.length} 条</span>
                    </div>
                    <button
                      onClick={() => {
                        if (stageKey === 'other') { bulkRetryFailed(); return; }
                        bulkRetryFailed(stageKey as any);
                      }}
                      className="inline-flex items-center gap-1.5 rounded bg-zinc-950 dark:bg-[var(--surface-border)] px-3 py-1.5 text-xs font-medium text-white dark:text-zinc-200 hover:bg-zinc-800 dark:hover:bg-[var(--text-muted)] cursor-pointer"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                      批量重试
                    </button>
                  </div>

                  {/* Error summary */}
                  {group.errors.size > 0 && (
                    <div className="border-b border-zinc-100 bg-amber-50/30 dark:bg-[var(--warning-bg)] px-5 py-2">
                      <div className="flex flex-wrap gap-2 text-xs text-zinc-600 dark:text-[var(--text-secondary)]">
                        {Array.from(group.errors.entries()).slice(0, 5).map(([err, count]) => (
                          <span key={err} className="rounded bg-white dark:bg-[var(--surface)] px-2 py-1 border border-zinc-150 dark:border-[var(--surface-border)]">
                            {count > 1 ? `${count}条：` : ''}{err.length > 60 ? err.slice(0, 60) + '...' : err}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="divide-zinc-100 dark:divide-[var(--surface-border)]">
                    {group.videos.slice(0, 10).map(video => {
                      const stage = stageFromFailedStep(video.failed_at_step);
                      return (
                        <div key={video.id} className="p-4">
                          <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-3">
                            <div className="min-w-0 space-y-1.5">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-mono">ID {video.id}</span>
                                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{video.blogger || '未知来源'}</span>
                                <span className="text-xs text-zinc-400">{video.failed_at || video.updated_at || ''}</span>
                              </div>
                              <h3 className="text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)]">{video.title || '无标题'}</h3>
                              <p className="max-w-4xl text-xs font-mono leading-6 text-zinc-500 dark:text-[var(--text-secondary)] break-all">
                                {video.error_message || '暂无错误摘要。'}
                              </p>
                            </div>
                            <div className="flex flex-wrap gap-2 shrink-0">
                              <button onClick={() => retryStage(video.id, stage)} className="inline-flex items-center gap-1.5 rounded bg-zinc-950 dark:bg-[var(--surface-border)] px-3 py-1.5 text-xs font-medium text-white dark:text-zinc-200 hover:bg-zinc-800 dark:hover:bg-[var(--text-muted)] cursor-pointer">
                                <RefreshCw className="w-3.5 h-3.5" />
                                重试当前
                              </button>
                              <button onClick={() => retryStage(video.id)} className="inline-flex items-center gap-1.5 rounded border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 cursor-pointer">
                                全流程重试
                              </button>
                              <button onClick={() => goDetail(video.id)} className="inline-flex items-center gap-1.5 rounded border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-50 cursor-pointer">
                                <Eye className="w-3.5 h-3.5" />
                                详情
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                    {group.videos.length > 10 && (
                      <div className="px-5 py-2 text-center text-xs text-zinc-400 dark:text-[var(--text-muted)] border-t border-zinc-100 dark:border-[var(--surface-border)]">
                        还有 {group.videos.length - 10} 条，调整筛选条件查看更多
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
