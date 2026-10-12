/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useMemo, useState } from 'react';
import {
  CheckCircle,
  Database,
  History,
  Link2,
  Loader2,
  Plus,
  Podcast,
  ScanSearch,
  Sparkles,
  Trash2,
  Tv,
} from 'lucide-react';
import { MonitorSource } from '../types';

interface SourceManagerProps {
  sources: MonitorSource[];
  sourceCategories: string[];
  addSource: (url: string, category: string, platform?: 'douyin' | 'xiaoyuzhou') => Promise<void>;
  previewSource: (url: string, platform: 'xiaoyuzhou') => Promise<Record<string, any>>;
  checkSourceNow: (id: string) => Promise<void>;
  updateSourceCategory: (id: string, category: string) => Promise<void>;
  updateSourceCategoryOption: (action: 'add' | 'delete', category: string) => Promise<void>;
  toggleSourceStatus: (id: string) => Promise<void>;
  deleteSource: (id: string) => void;
  runResearchTask: (type: 'single' | 'blogger', targetValue: string, forceRetry: boolean, limit?: number) => Promise<void>;
}

type SourceTableProps = {
  title: string;
  description: string;
  sources: MonitorSource[];
  categoryDrafts: Record<string, string>;
  savingCategoryId: string;
  togglingSourceId: string;
  researchingSourceId: string;
  checkingSourceId: string;
  scanningSourceId: string;
  onCategoryDraftChange: (id: string, value: string) => void;
  onCategorySave: (event: React.FormEvent, id: string, fallbackCategory: string) => void;
  onToggle: (id: string) => void;
  onDelete: (source: MonitorSource) => void;
  onResearchAll: (source: MonitorSource) => void;
  onCheckNow: (source: MonitorSource) => void;
  onScanHistory: (source: MonitorSource) => void;
  emptyText: string;
  compact?: boolean;
};

function sourceNeedsAttention(source: MonitorSource) {
  return source.status === 'disabled' || source.quality_score < 75 || source.parse_success_rate < 85;
}

function SourceTable({
  title,
  description,
  sources,
  categoryDrafts,
  savingCategoryId,
  togglingSourceId,
  researchingSourceId,
  checkingSourceId,
  scanningSourceId,
  onCategoryDraftChange,
  onCategorySave,
  onToggle,
  onDelete,
  onResearchAll,
  onCheckNow,
  onScanHistory,
  emptyText,
  compact = false,
}: SourceTableProps) {
  return (
    <section className="overflow-hidden rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
      <div className="flex flex-col gap-1 border-b border-zinc-150 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-4 py-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{title}</h2>
          <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-[var(--text-secondary)]">{description}</p>
        </div>
        <span className="text-xs font-mono text-zinc-400 dark:text-[var(--text-muted)]">{sources.length} 个</span>
      </div>
      {sources.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-zinc-400 dark:text-[var(--text-muted)]">{emptyText}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                <th className="p-4 font-semibold">来源</th>
                <th className="p-4 font-semibold">分类</th>
                <th className="p-4 font-semibold">来源</th>
                <th className="p-4 text-center font-semibold">收录</th>
                <th className="p-4 text-center font-semibold" title="成功生成正文的内容数 / 已收录内容数；失败和待处理项不算成功">正文成功率</th>
                <th className="p-4 text-center font-semibold">研究完成度</th>
                <th className="min-w-64 p-4 text-right font-semibold">动作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-150 dark:divide-[var(--surface-border)]">
              {sources.map((src) => {
                const isConfigSource = Boolean(src.in_config);
                const isPodcast = src.platform === 'xiaoyuzhou';
                const toggleLabel = togglingSourceId === src.id
                  ? '切换中...'
                  : src.status === 'enabled'
                    ? '正在监控'
                    : isConfigSource
                      ? '已暂停'
                      : '加入监控';
                return (
                  <tr key={src.id} className="text-sm transition hover:bg-zinc-50/60 dark:hover:bg-[var(--surface-muted)]">
                    <td className="p-4">
                      <div className="flex items-center gap-2">
                        <div className="font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{src.name}</div>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${isPodcast ? 'bg-emerald-50 text-emerald-700 dark:bg-[var(--success-bg)] dark:text-[var(--success)]' : 'bg-blue-50 text-blue-700 dark:bg-[var(--info-bg)] dark:text-[var(--info)]'}`}>
                          {isPodcast ? '小宇宙' : '抖音'}
                        </span>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${isConfigSource ? 'bg-blue-50 text-blue-700 dark:bg-[var(--info-bg)] dark:text-[var(--info)]' : 'bg-zinc-100 text-zinc-500 dark:bg-[var(--surface-border)] dark:text-[var(--text-muted)]'}`}>
                          {src.source_label || (isConfigSource ? '配置监控' : '资料库历史')}
                        </span>
                      </div>
                      <span className="mt-1 block text-[10px] font-mono text-zinc-400 dark:text-[var(--text-muted)]">
                        上次检测：{src.last_checked || '暂无'}
                      </span>
                    </td>

                    <td className="p-4">
                      {isConfigSource ? (
                        <form onSubmit={(event) => onCategorySave(event, src.id, src.category)} className="flex min-w-40 items-center gap-2">
                          <input
                            aria-label={`${src.name} 分类`}
                            list="source-category-options"
                            value={categoryDrafts[src.id] ?? src.category}
                            onChange={(event) => onCategoryDraftChange(src.id, event.target.value)}
                            placeholder="未分类"
                            className="w-24 rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-2 py-1 text-xs text-zinc-700 dark:text-[var(--text-primary)] focus:border-zinc-500 focus:bg-white dark:focus:bg-[var(--surface)] focus:outline-none"
                          />
                          <button
                            type="submit"
                            disabled={savingCategoryId === src.id || (categoryDrafts[src.id] ?? src.category).trim() === src.category}
                            className="rounded px-2 py-1 text-xs font-medium text-zinc-500 dark:text-[var(--text-secondary)] transition hover:bg-zinc-100 dark:hover:bg-[var(--surface-border)] hover:text-zinc-900 dark:hover:text-[var(--text-primary)] disabled:cursor-default disabled:text-zinc-300 dark:disabled:text-[var(--text-muted)] disabled:hover:bg-transparent dark:disabled:hover:bg-transparent"
                          >
                            {savingCategoryId === src.id ? '保存中' : '保存'}
                          </button>
                        </form>
                      ) : (
                        <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)]">{src.category || '未分类'}</span>
                      )}
                    </td>

                    <td className="max-w-xs p-4 font-mono text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                      <div className="flex items-center gap-1">
                        <Link2 className="h-3.5 w-3.5 shrink-0 text-zinc-300 dark:text-[var(--text-muted)]" />
                        <span className="truncate">{src.url || '暂无主页 URL'}</span>
                      </div>
                    </td>

                    <td className="p-4 text-center font-mono text-zinc-700 dark:text-[var(--text-primary)]">{src.total_captured} 条</td>

                    <td className="p-4 text-center">
                      <span className={`font-mono font-medium ${
                        src.parse_success_rate > 95 ? 'text-emerald-600 dark:text-[var(--success)]' :
                        src.parse_success_rate > 85 ? 'text-zinc-600 dark:text-[var(--text-secondary)]' : 'text-red-500 font-bold dark:text-[var(--danger)]'
                      }`}>
                        {src.parse_success_rate}%
                      </span>
                    </td>

                    <td className="p-4">
                      <div className="flex items-center justify-center gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]">
                          <div
                            className={`h-full rounded-full ${
                              src.quality_score > 90 ? 'bg-emerald-500 dark:bg-[var(--success)]' :
                              src.quality_score > 75 ? 'bg-amber-500 dark:bg-[var(--warning)]' : 'bg-red-500 dark:bg-[var(--danger)]'
                            }`}
                            style={{ width: `${Math.min(100, Math.max(0, src.quality_score))}%` }}
                          />
                        </div>
                        <span className="font-mono text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{src.quality_score}</span>
                      </div>
                    </td>

                    <td className="min-w-64 p-4 text-right">
                      <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                        {isPodcast && (
                          <button
                            type="button"
                            disabled={Boolean(checkingSourceId)}
                            onClick={() => onCheckNow(src)}
                            className="inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded border border-emerald-100 dark:border-[var(--success-border)] bg-emerald-50 dark:bg-[var(--success-bg)] px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:text-[var(--success)] transition hover:bg-emerald-100/70 dark:hover:bg-[var(--success)] focus:outline-none focus:ring-2 focus:ring-emerald-200 dark:focus:ring-[var(--success-border)] disabled:cursor-not-allowed disabled:opacity-60"
                            title="检查该小宇宙订阅源，默认不发布 Pages、不推送飞书"
                          >
                            {checkingSourceId === src.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <Podcast className="h-3.5 w-3.5" />
                            )}
                            <span>{checkingSourceId === src.id ? '提交中' : '立即检查'}</span>
                          </button>
                        )}

                        {isConfigSource && !isPodcast && (
                          <button
                            type="button"
                            disabled={Boolean(researchingSourceId)}
                            onClick={() => onResearchAll(src)}
                            className="inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded border border-blue-100 dark:border-[var(--info-border)] bg-blue-50 dark:bg-[var(--info-bg)] px-2.5 py-1 text-xs font-semibold text-blue-700 dark:text-[var(--info)] transition hover:bg-blue-100/70 dark:hover:bg-[var(--info)] focus:outline-none focus:ring-2 focus:ring-blue-200 dark:focus:ring-[var(--info-border)] disabled:cursor-not-allowed disabled:opacity-60"
                            title="抓取该博主全部历史视频；已完整处理的内容会自动跳过"
                          >
                            {researchingSourceId === src.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <ScanSearch className="h-3.5 w-3.5" />
                            )}
                            <span>{researchingSourceId === src.id ? '提交中' : '全量研究'}</span>
                          </button>
                        )}

                        <button
                          type="button"
                          aria-pressed={src.status === 'enabled'}
                          aria-label={`${src.name} 监控开关`}
                          title={isConfigSource ? (src.status === 'enabled' ? '点击暂停自动监控' : '点击恢复自动监控') : '加入 config.yaml 自动监控列表'}
                          disabled={!src.can_toggle || togglingSourceId === src.id}
                          onClick={() => onToggle(src.id)}
                          className={`inline-flex min-w-24 items-center justify-center rounded border px-2.5 py-1 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${
                            src.status === 'enabled'
                              ? 'border-emerald-100/60 dark:border-[var(--success-border)] bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-700 dark:text-[var(--success)] hover:bg-emerald-100/60 dark:hover:bg-[var(--success)]'
                              : isConfigSource
                                ? 'border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-100 dark:bg-[var(--surface-muted)] text-zinc-500 dark:text-[var(--text-muted)] hover:bg-zinc-200/70 dark:hover:bg-[var(--surface-border)]'
                                : 'border-blue-100 dark:border-[var(--info-border)] bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)] hover:bg-blue-100/70 dark:hover:bg-[var(--info)]'
                          }`}
                        >
                          {toggleLabel}
                        </button>

                        {!compact && isConfigSource && (
                          <button
                            onClick={() => onDelete(src)}
                            className="rounded p-1.5 text-zinc-400 dark:text-[var(--text-muted)] transition hover:bg-red-50 dark:hover:bg-[var(--danger-bg)] hover:text-red-600 dark:hover:text-[var(--danger)]"
                            title="从自动监控配置中移出"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}

                        <button
                          type="button"
                          disabled={Boolean(scanningSourceId)}
                          onClick={() => onScanHistory(src)}
                          className="inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded border border-amber-100 dark:border-[var(--warning-border)] bg-amber-50 dark:bg-[var(--warning-bg)] px-2.5 py-1 text-xs font-semibold text-amber-700 dark:text-[var(--warning)] transition hover:bg-amber-100/70 dark:hover:bg-[var(--warning)] focus:outline-none focus:ring-2 focus:ring-amber-200 dark:focus:ring-[var(--warning-border)] disabled:cursor-not-allowed disabled:opacity-60"
                          title="扫描该来源的历史内容并生成待确认作业（不直接处理）"
                        >
                          {scanningSourceId === src.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <History className="h-3.5 w-3.5" />
                          )}
                          <span>{scanningSourceId === src.id ? '扫描中' : '历史扫描'}</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default function SourceManager({
  sources,
  sourceCategories,
  addSource,
  previewSource,
  checkSourceNow,
  updateSourceCategory,
  updateSourceCategoryOption,
  toggleSourceStatus,
  deleteSource,
  runResearchTask,
}: SourceManagerProps) {
  const [bLink, setBLink] = useState('');
  const [category, setCategory] = useState('');
  const [newSourcePlatform, setNewSourcePlatform] = useState<'douyin' | 'xiaoyuzhou'>('douyin');
  const [platformFilter, setPlatformFilter] = useState<'all' | 'douyin' | 'xiaoyuzhou'>('all');
  const [sourcePreview, setSourcePreview] = useState<Record<string, any> | null>(null);
  const [previewingSource, setPreviewingSource] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [submittingSource, setSubmittingSource] = useState(false);
  const [sourceError, setSourceError] = useState('');
  const [categoryDrafts, setCategoryDrafts] = useState<Record<string, string>>({});
  const [savingCategoryId, setSavingCategoryId] = useState('');
  const [togglingSourceId, setTogglingSourceId] = useState('');
  const [researchingSourceId, setResearchingSourceId] = useState('');
  const [checkingSourceId, setCheckingSourceId] = useState('');
  const [scanningSourceId, setScanningSourceId] = useState('');
  const [researchNotice, setResearchNotice] = useState('');
  const [newCategory, setNewCategory] = useState('');
  const [editingCategoryOption, setEditingCategoryOption] = useState('');

  const visibleSources = useMemo(() => (
    platformFilter === 'all' ? sources : sources.filter(source => (source.platform || 'douyin') === platformFilter)
  ), [platformFilter, sources]);
  const configSources = useMemo(() => visibleSources.filter(source => source.in_config), [visibleSources]);
  const databaseSources = useMemo(() => visibleSources.filter(source => !source.in_config), [visibleSources]);
  const categoryOptions = Array.from(new Set([
    ...sourceCategories,
    ...configSources.map(source => source.category).filter(Boolean),
  ]));
  const categoryUsage = configSources.reduce<Record<string, number>>((usage, source) => {
    if (source.category) usage[source.category] = (usage[source.category] || 0) + 1;
    return usage;
  }, {});

  const activeCount = configSources.filter(source => source.status === 'enabled').length;
  const pausedConfigCount = configSources.filter(source => source.status === 'disabled').length;
  const historyOnlyCount = databaseSources.length;
  const needsAttentionCount = configSources.filter(sourceNeedsAttention).length;
  const averageQuality = configSources.length > 0
    ? (configSources.reduce((sum, source) => sum + source.quality_score, 0) / configSources.length).toFixed(0)
    : '0';

  const handleCreateSource = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!bLink.trim()) return;
    setSubmittingSource(true);
    setSourceError('');
    try {
      await addSource(bLink.trim(), category.trim(), newSourcePlatform);
      setBLink('');
      setCategory('');
      setSourcePreview(null);
      setShowAddForm(false);
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '来源登记失败');
    } finally {
      setSubmittingSource(false);
    }
  };

  const handlePreviewSource = async () => {
    if (newSourcePlatform !== 'xiaoyuzhou' || !bLink.trim()) return;
    setPreviewingSource(true);
    setSourceError('');
    try {
      setSourcePreview(await previewSource(bLink.trim(), 'xiaoyuzhou'));
    } catch (error) {
      setSourcePreview(null);
      setSourceError(error instanceof Error ? error.message : '来源预览失败');
    } finally {
      setPreviewingSource(false);
    }
  };

  const handleCategorySave = async (event: React.FormEvent, id: string, fallbackCategory: string) => {
    event.preventDefault();
    setSavingCategoryId(id);
    try {
      await updateSourceCategory(id, (categoryDrafts[id] ?? fallbackCategory).trim());
      setSourceError('');
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '分类保存失败');
    } finally {
      setSavingCategoryId('');
    }
  };

  const handleSourceToggle = async (id: string) => {
    setTogglingSourceId(id);
    try {
      await toggleSourceStatus(id);
      setSourceError('');
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '监控状态切换失败');
    } finally {
      setTogglingSourceId('');
    }
  };

  const handleCategoryOptionAdd = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = newCategory.trim();
    if (!value) return;
    setEditingCategoryOption(value);
    try {
      await updateSourceCategoryOption('add', value);
      setNewCategory('');
      setSourceError('');
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '分类新增失败');
    } finally {
      setEditingCategoryOption('');
    }
  };

  const handleCategoryOptionDelete = async (value: string) => {
    setEditingCategoryOption(value);
    try {
      await updateSourceCategoryOption('delete', value);
      setSourceError('');
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '分类删除失败');
    } finally {
      setEditingCategoryOption('');
    }
  };

  const handleDeleteSource = (source: MonitorSource) => {
    const label = source.platform === 'xiaoyuzhou' ? '订阅源' : '自动监控配置';
    if (window.confirm(`确定将 [${source.name}] 从${label}中移出吗？\n历史内容仍会保留在内容归档和数据库中。`)) {
      deleteSource(source.id);
    }
  };

  const handleResearchAll = async (source: MonitorSource) => {
    const confirmed = window.confirm(
      `确定对 [${source.name}] 发起全量视频研究吗？\n\n`
      + '系统会抓取该博主全部历史视频，已完整处理的内容会自动跳过。'
      + '研究后该博主会保持监控状态，后续更新生成笔记时会同步发布 HTML 目录。'
    );
    if (!confirmed) return;

    setResearchingSourceId(source.id);
    setResearchNotice('');
    setSourceError('');
    try {
      await runResearchTask('blogger', source.url || source.name, false, 0);
      setResearchNotice(`已提交 ${source.name} 的全量视频研究；识别成功后将自动加入持续监控。`);
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '全量研究任务提交失败');
    } finally {
      setResearchingSourceId('');
    }
  };

  const handleCheckNow = async (source: MonitorSource) => {
    setCheckingSourceId(source.id);
    setSourceError('');
    setResearchNotice('');
    try {
      await checkSourceNow(source.id);
      setResearchNotice(`已提交 ${source.name} 的小宇宙订阅检查；默认不会发布 Pages 或推送飞书。`);
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '来源检查任务提交失败');
    } finally {
      setCheckingSourceId('');
    }
  };

  // M6: scan subscription history into a reviewable research job (no auto-execute).
  const handleScanHistory = async (source: MonitorSource) => {
    const confirmed = window.confirm(
      `对 [${source.name}] 发起历史扫描吗？\n\n`
      + '系统会列出该来源的历史内容并生成一份待确认作业，不会立即处理。'
      + '你可以在「归档研究 / 研究任务」中逐项批准后再执行。'
    );
    if (!confirmed) return;
    setScanningSourceId(source.id);
    setSourceError('');
    setResearchNotice('');
    try {
      const resp = await fetch('/api/source-subscriptions/scan-history', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subscription_id: Number(source.id.replace(/^sub:/, '')) || 0,
          scope: 'full',
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.message || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const stats = data?.stats || {};
      setResearchNotice(
        `历史扫描完成：${source.name} 发现 ${stats.discovered ?? 0} 条新内容、`
        + `已有 ${stats.already_known ?? 0} 条；作业 #${stats.job_id ?? '?'} 待确认。`
      );
    } catch (error) {
      setSourceError(error instanceof Error ? error.message : '历史扫描提交失败');
    } finally {
      setScanningSourceId('');
    }
  };

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col items-start justify-between gap-4 border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">来源管理</h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-[var(--text-secondary)]">集中维护抖音博主和小宇宙订阅源，明确哪些来源会被持续监控。</p>
        </div>

        <button
          onClick={() => {
            setShowAddForm(!showAddForm);
            setSourcePreview(null);
            setSourceError('');
          }}
          className="flex shrink-0 items-center gap-1.5 rounded-md bg-zinc-900 dark:bg-[var(--surface-border)] px-4 py-2 text-sm font-medium text-zinc-100 dark:text-zinc-200 transition hover:bg-zinc-850 dark:hover:bg-[var(--text-muted)]"
        >
          <Plus className="h-4 w-4" />
          <span>{showAddForm ? '收起配置' : '登记新监控源'}</span>
        </button>
      </div>

      {showAddForm && (
        <form onSubmit={handleCreateSource} className="max-w-2xl space-y-4 rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50/70 dark:bg-[var(--surface-muted)] p-6">
          <div>
            <h3 className="text-sm font-bold text-zinc-900 dark:text-[var(--text-primary)]">登记新的监控来源</h3>
            <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-[var(--text-secondary)]">抖音来源继续写入 config.yaml；小宇宙节目、RSS 或单集会登记为数据库订阅源。</p>
          </div>

          <div className="inline-flex rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-1">
            {[
              { key: 'douyin', label: '抖音' },
              { key: 'xiaoyuzhou', label: '小宇宙' },
            ].map(option => (
              <button
                key={option.key}
                type="button"
                onClick={() => {
                  setNewSourcePlatform(option.key as 'douyin' | 'xiaoyuzhou');
                  setSourcePreview(null);
                  setSourceError('');
                }}
                className={`rounded px-3 py-1.5 text-xs font-semibold transition ${
                  newSourcePlatform === option.key ? 'bg-zinc-900 dark:bg-[var(--surface-border)] text-white dark:text-zinc-200' : 'text-zinc-500 hover:bg-zinc-100 dark:hover:bg-[var(--surface-border)] hover:text-zinc-900 dark:hover:text-[var(--text-primary)]'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="text-xs text-zinc-600 dark:text-[var(--text-secondary)]">{newSourcePlatform === 'xiaoyuzhou' ? '小宇宙节目 / 单集 / RSS URL' : '抖音博主主页 URL'}</label>
              <input
                type="url"
                required
                placeholder={newSourcePlatform === 'xiaoyuzhou' ? 'https://.../rss 或 https://www.xiaoyuzhoufm.com/...' : 'https://www.douyin.com/user/MS...'}
                value={bLink}
                onChange={(event) => {
                  setBLink(event.target.value);
                  setSourcePreview(null);
                }}
                className="w-full rounded border border-zinc-250 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm focus:border-zinc-900 dark:focus:border-[var(--text-primary)] focus:outline-none"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-600 dark:text-[var(--text-secondary)]">来源分类</label>
              <input
                type="text"
                list="source-category-options"
                placeholder="例如：科技、财经"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="w-full rounded border border-zinc-250 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm focus:border-zinc-900 dark:focus:border-[var(--text-primary)] focus:outline-none"
              />
            </div>
          </div>

          {sourceError && (
            <p className="rounded border border-red-100 dark:border-[var(--danger-border)] bg-red-50 dark:bg-[var(--danger-bg)] px-3 py-2 text-xs text-red-700 dark:text-[var(--danger)]">{sourceError}</p>
          )}

          {newSourcePlatform === 'xiaoyuzhou' && (
            <div className="rounded border border-emerald-100 dark:border-[var(--success-border)] bg-emerald-50/60 dark:bg-[var(--success-bg)] px-3 py-3 text-xs text-emerald-900 dark:text-[var(--success)]">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <span>保存前可先解析公开信息，确认音频 URL 和最新单集可用。</span>
                <button
                  type="button"
                  disabled={!bLink.trim() || previewingSource}
                  onClick={handlePreviewSource}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded border border-emerald-200 dark:border-[var(--success-border)] bg-white dark:bg-[var(--surface)] px-3 font-semibold text-emerald-700 dark:text-[var(--success)] transition hover:bg-emerald-100 dark:hover:bg-[var(--success)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {previewingSource && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{previewingSource ? '解析中' : '预览来源'}</span>
                </button>
              </div>
              {sourcePreview && (
                <div className="mt-3 grid gap-1.5 border-t border-emerald-100 dark:border-[var(--success-border)] pt-3">
                  <div className="font-semibold">{sourcePreview.display_name || '小宇宙播客'}</div>
                  <div>类型：{sourcePreview.source_type === 'rss' ? 'RSS Feed' : sourcePreview.source_type === 'episode' ? '单集' : '节目主页'} · 可解析 {sourcePreview.episode_count || 0} 集</div>
                  <div className="truncate">最新：{sourcePreview.latest_episode_title || '暂无标题'}</div>
                  <div>音频：{sourcePreview.audio_available ? '可用' : '未解析到'}</div>
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setShowAddForm(false)}
              className="rounded border border-zinc-250 dark:border-[var(--surface-border)] px-3.5 py-1.5 text-xs font-medium text-zinc-600 dark:text-[var(--text-secondary)] transition hover:bg-zinc-100 dark:hover:bg-[var(--surface-border)]"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submittingSource}
              className="rounded bg-zinc-900 dark:bg-[var(--surface-border)] px-4 py-1.5 text-xs font-semibold text-zinc-100 dark:text-zinc-200 transition hover:bg-zinc-800 dark:hover:bg-[var(--text-muted)] disabled:bg-zinc-400 dark:disabled:bg-[var(--text-muted)]"
            >
              {submittingSource ? '解析登记中...' : '确认登记'}
            </button>
          </div>
        </form>
      )}

      <datalist id="source-category-options">
        {categoryOptions.map(option => <option key={option} value={option} />)}
      </datalist>
      {!showAddForm && sourceError && (
        <p className="rounded border border-red-100 dark:border-[var(--danger-border)] bg-red-50 dark:bg-[var(--danger-bg)] px-3 py-2 text-xs text-red-700 dark:text-[var(--danger)]">{sourceError}</p>
      )}
      {researchNotice && (
        <p className="rounded border border-blue-100 dark:border-[var(--info-border)] bg-blue-50 dark:bg-[var(--info-bg)] px-3 py-2 text-xs text-blue-800 dark:text-[var(--info)]" role="status">
          {researchNotice}
        </p>
      )}

      <div className="inline-flex rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-1">
        {[
          { key: 'all', label: '全部' },
          { key: 'douyin', label: '抖音' },
          { key: 'xiaoyuzhou', label: '小宇宙' },
        ].map(option => (
          <button
            key={option.key}
            type="button"
            onClick={() => setPlatformFilter(option.key as 'all' | 'douyin' | 'xiaoyuzhou')}
            className={`rounded px-3 py-1.5 text-xs font-semibold transition ${
              platformFilter === option.key ? 'bg-zinc-900 dark:bg-[var(--surface-border)] text-white dark:text-zinc-200' : 'text-zinc-500 hover:bg-zinc-100 dark:hover:bg-[var(--surface-border)] hover:text-zinc-900 dark:hover:text-[var(--text-primary)]'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <div className="flex items-center gap-4 rounded-lg border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-4">
          <div className="shrink-0 rounded border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-3 text-zinc-900 dark:text-[var(--text-primary)]">
            <Tv className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500 dark:text-[var(--text-secondary)]">自动监控来源</span>
            <span className="mt-0.5 block text-xl font-extrabold text-zinc-900 dark:text-[var(--text-primary)]">{configSources.length} 个</span>
            <span className="mt-0.5 block text-[10px] text-zinc-400 dark:text-[var(--text-muted)]">平均研究完成度 {averageQuality}%</span>
          </div>
        </div>

        <div className="flex items-center gap-4 rounded-lg border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-4">
          <div className="shrink-0 rounded border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-3 text-emerald-600 dark:text-[var(--success)]">
            <CheckCircle className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500 dark:text-[var(--text-secondary)]">当前启用</span>
            <span className="mt-0.5 block text-xl font-extrabold text-emerald-600 dark:text-[var(--success)]">{activeCount} 个</span>
          </div>
        </div>

        <div className={`flex items-center gap-4 rounded-lg border p-4 ${needsAttentionCount > 0 || pausedConfigCount > 0 ? 'border-amber-150 dark:border-[var(--warning-border)] bg-amber-50/60 dark:bg-[var(--warning-bg)]' : 'border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)]'}`}>
          <div className="shrink-0 rounded border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-3 text-amber-500 dark:text-[var(--warning)]">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500 dark:text-[var(--text-secondary)]">需要处理</span>
            <span className={`mt-0.5 block text-xl font-extrabold ${needsAttentionCount > 0 ? 'text-amber-700 dark:text-[var(--warning)]' : 'text-zinc-900 dark:text-[var(--text-primary)]'}`}>{needsAttentionCount} 个</span>
          </div>
        </div>

        <div className="flex items-center gap-4 rounded-lg border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-4">
          <div className="shrink-0 rounded border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-3 text-zinc-500 dark:text-[var(--text-muted)]">
            <Database className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500 dark:text-[var(--text-secondary)]">历史来源</span>
            <span className="mt-0.5 block text-xl font-extrabold text-zinc-900 dark:text-[var(--text-primary)]">{historyOnlyCount} 家</span>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-blue-100 dark:border-[var(--info-border)] bg-blue-50/60 dark:bg-[var(--info-bg)] px-4 py-3 text-xs leading-5 text-blue-900 dark:text-[var(--info)]">
        正文成功率与研究完成度按成功正文数 / 已收录内容数计算，失败、降级笔记和待处理项不算成功，不混入内容评分。Obsidian 文件数包含降级笔记，因此可能大于成功正文数。立即检查默认不发布 Pages、不推送飞书。
      </div>

      <section className="space-y-4 rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">来源分类</h2>
            <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-[var(--text-secondary)]">分类只作用于自动监控配置；资料库历史来源加入监控后才可分配分类。</p>
          </div>
          <form onSubmit={handleCategoryOptionAdd} className="flex w-full max-w-sm items-center gap-2">
            <label htmlFor="new-source-category" className="sr-only">新增来源分类</label>
            <input
              id="new-source-category"
              value={newCategory}
              onChange={(event) => setNewCategory(event.target.value)}
              placeholder="新增分类"
              className="h-9 min-w-0 flex-1 rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 text-sm text-zinc-800 dark:text-[var(--text-primary)] focus:border-zinc-500 dark:focus:border-[var(--text-primary)] focus:bg-white dark:focus:bg-[var(--surface)] focus:outline-none"
            />
            <button
              type="submit"
              disabled={!newCategory.trim() || editingCategoryOption === newCategory.trim()}
              className="inline-flex h-9 items-center gap-1.5 rounded bg-zinc-900 dark:bg-[var(--surface-border)] px-3 text-xs font-semibold text-zinc-100 dark:text-zinc-200 transition hover:bg-zinc-800 dark:hover:bg-[var(--text-muted)] disabled:cursor-not-allowed disabled:bg-zinc-400 dark:disabled:bg-[var(--text-muted)]"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>新增</span>
            </button>
          </form>
        </div>
        <div className="flex flex-wrap gap-2">
          {sourceCategories.map((option) => (
            <span key={option} className="inline-flex h-8 items-center gap-2 rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] pl-2.5 pr-1 text-xs font-medium text-zinc-700 dark:text-[var(--text-primary)]">
              <span>{option}</span>
              <span className="rounded bg-white dark:bg-[var(--surface)] px-1.5 py-0.5 text-[10px] text-zinc-400 dark:text-[var(--text-muted)]">{categoryUsage[option] || 0}</span>
              <button
                type="button"
                aria-label={`删除分类 ${option}`}
                title={categoryUsage[option] ? '先调整使用该分类的来源' : '删除分类'}
                disabled={Boolean(categoryUsage[option]) || editingCategoryOption === option}
                onClick={() => handleCategoryOptionDelete(option)}
                className="inline-flex h-6 w-6 items-center justify-center rounded text-zinc-400 dark:text-[var(--text-muted)] transition hover:bg-red-50 dark:hover:bg-[var(--danger-bg)] hover:text-red-600 dark:hover:text-[var(--danger)] disabled:cursor-not-allowed disabled:text-zinc-200 dark:disabled:text-[var(--text-muted)] disabled:hover:bg-transparent dark:disabled:hover:bg-transparent"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
          {sourceCategories.length === 0 && <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)]">暂无可选分类。</span>}
        </div>
      </section>

      <SourceTable
        title="自动监控来源"
        description="这些博主定义在 config.yaml 中，会被定时调度器和手动检测使用。"
        sources={configSources}
        categoryDrafts={categoryDrafts}
        savingCategoryId={savingCategoryId}
        togglingSourceId={togglingSourceId}
        researchingSourceId={researchingSourceId}
        checkingSourceId={checkingSourceId}
        scanningSourceId={scanningSourceId}
        onCategoryDraftChange={(id, value) => setCategoryDrafts(prev => ({ ...prev, [id]: value }))}
        onCategorySave={handleCategorySave}
        onToggle={handleSourceToggle}
        onDelete={handleDeleteSource}
        onResearchAll={handleResearchAll}
        onCheckNow={handleCheckNow}
        onScanHistory={handleScanHistory}
        emptyText="暂无自动监控来源，请登记一个抖音博主主页。"
      />

      <SourceTable
        title="资料库历史来源"
        description="这些博主来自数据库历史内容，不会自动轮询；需要继续关注时可加入自动监控。"
        sources={databaseSources}
        categoryDrafts={categoryDrafts}
        savingCategoryId={savingCategoryId}
        togglingSourceId={togglingSourceId}
        researchingSourceId={researchingSourceId}
        checkingSourceId={checkingSourceId}
        scanningSourceId={scanningSourceId}
        onCategoryDraftChange={(id, value) => setCategoryDrafts(prev => ({ ...prev, [id]: value }))}
        onCategorySave={handleCategorySave}
        onToggle={handleSourceToggle}
        onDelete={handleDeleteSource}
        onResearchAll={handleResearchAll}
        onCheckNow={handleCheckNow}
        onScanHistory={handleScanHistory}
        emptyText="暂无仅存在于数据库的历史来源。"
        compact
      />
    </div>
  );
}
