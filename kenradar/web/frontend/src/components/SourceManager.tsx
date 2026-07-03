/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useMemo, useState } from 'react';
import {
  CheckCircle,
  Database,
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
  onCategoryDraftChange: (id: string, value: string) => void;
  onCategorySave: (event: React.FormEvent, id: string, fallbackCategory: string) => void;
  onToggle: (id: string) => void;
  onDelete: (source: MonitorSource) => void;
  onResearchAll: (source: MonitorSource) => void;
  onCheckNow: (source: MonitorSource) => void;
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
  onCategoryDraftChange,
  onCategorySave,
  onToggle,
  onDelete,
  onResearchAll,
  onCheckNow,
  emptyText,
  compact = false,
}: SourceTableProps) {
  return (
    <section className="overflow-hidden rounded-lg border border-zinc-150 bg-white">
      <div className="flex flex-col gap-1 border-b border-zinc-150 bg-zinc-50 px-4 py-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-zinc-900">{title}</h2>
          <p className="mt-1 text-xs leading-5 text-zinc-500">{description}</p>
        </div>
        <span className="text-xs font-mono text-zinc-400">{sources.length} 个</span>
      </div>
      {sources.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-zinc-400">{emptyText}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-zinc-150 bg-white text-xs text-zinc-500">
                <th className="p-4 font-semibold">来源</th>
                <th className="p-4 font-semibold">分类</th>
                <th className="p-4 font-semibold">来源</th>
                <th className="p-4 text-center font-semibold">收录</th>
                <th className="p-4 text-center font-semibold">成功率</th>
                <th className="p-4 text-center font-semibold">健康</th>
                <th className="min-w-64 p-4 text-right font-semibold">动作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-150">
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
                  <tr key={src.id} className="text-sm transition hover:bg-zinc-50/60">
                    <td className="p-4">
                      <div className="flex items-center gap-2">
                        <div className="font-semibold text-zinc-900">{src.name}</div>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${isPodcast ? 'bg-emerald-50 text-emerald-700' : 'bg-blue-50 text-blue-700'}`}>
                          {isPodcast ? '小宇宙' : '抖音'}
                        </span>
                        <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${isConfigSource ? 'bg-blue-50 text-blue-700' : 'bg-zinc-100 text-zinc-500'}`}>
                          {src.source_label || (isConfigSource ? '配置监控' : '资料库历史')}
                        </span>
                      </div>
                      <span className="mt-1 block text-[10px] font-mono text-zinc-400">
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
                            className="w-24 rounded border border-zinc-200 bg-zinc-50 px-2 py-1 text-xs text-zinc-700 focus:border-zinc-500 focus:bg-white focus:outline-none"
                          />
                          <button
                            type="submit"
                            disabled={savingCategoryId === src.id || (categoryDrafts[src.id] ?? src.category).trim() === src.category}
                            className="rounded px-2 py-1 text-xs font-medium text-zinc-500 transition hover:bg-zinc-100 hover:text-zinc-900 disabled:cursor-default disabled:text-zinc-300 disabled:hover:bg-transparent"
                          >
                            {savingCategoryId === src.id ? '保存中' : '保存'}
                          </button>
                        </form>
                      ) : (
                        <span className="text-xs text-zinc-400">{src.category || '未分类'}</span>
                      )}
                    </td>

                    <td className="max-w-xs p-4 font-mono text-xs text-zinc-500">
                      <div className="flex items-center gap-1">
                        <Link2 className="h-3.5 w-3.5 shrink-0 text-zinc-300" />
                        <span className="truncate">{src.url || '暂无主页 URL'}</span>
                      </div>
                    </td>

                    <td className="p-4 text-center font-mono text-zinc-700">{src.total_captured} 条</td>

                    <td className="p-4 text-center">
                      <span className={`font-mono font-medium ${
                        src.parse_success_rate > 95 ? 'text-emerald-600' :
                        src.parse_success_rate > 85 ? 'text-zinc-600' : 'text-red-500 font-bold'
                      }`}>
                        {src.parse_success_rate}%
                      </span>
                    </td>

                    <td className="p-4">
                      <div className="flex items-center justify-center gap-2">
                        <div className="h-1.5 w-16 overflow-hidden rounded-full bg-zinc-100">
                          <div
                            className={`h-full rounded-full ${
                              src.quality_score > 90 ? 'bg-emerald-500' :
                              src.quality_score > 75 ? 'bg-amber-500' : 'bg-red-500'
                            }`}
                            style={{ width: `${Math.min(100, Math.max(0, src.quality_score))}%` }}
                          />
                        </div>
                        <span className="font-mono text-xs text-zinc-500">{src.quality_score}</span>
                      </div>
                    </td>

                    <td className="min-w-64 p-4 text-right">
                      <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                        {isPodcast && (
                          <button
                            type="button"
                            disabled={Boolean(checkingSourceId)}
                            onClick={() => onCheckNow(src)}
                            className="inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded border border-emerald-100 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-100/70 focus:outline-none focus:ring-2 focus:ring-emerald-200 disabled:cursor-not-allowed disabled:opacity-60"
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
                            className="inline-flex min-h-9 shrink-0 items-center justify-center gap-1.5 rounded border border-blue-100 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-700 transition hover:bg-blue-100/70 focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:cursor-not-allowed disabled:opacity-60"
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
                              ? 'border-emerald-100/60 bg-emerald-50 text-emerald-700 hover:bg-emerald-100/60'
                              : isConfigSource
                                ? 'border-zinc-200 bg-zinc-100 text-zinc-500 hover:bg-zinc-200/70'
                                : 'border-blue-100 bg-blue-50 text-blue-700 hover:bg-blue-100/70'
                          }`}
                        >
                          {toggleLabel}
                        </button>

                        {!compact && isConfigSource && (
                          <button
                            onClick={() => onDelete(src)}
                            className="rounded p-1.5 text-zinc-400 transition hover:bg-red-50 hover:text-red-600"
                            title="从自动监控配置中移出"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        )}
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

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col items-start justify-between gap-4 border-b border-zinc-200 pb-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900">来源管理</h1>
          <p className="mt-1 text-sm text-zinc-500">集中维护抖音博主和小宇宙订阅源，明确哪些来源会被持续监控。</p>
        </div>

        <button
          onClick={() => {
            setShowAddForm(!showAddForm);
            setSourcePreview(null);
            setSourceError('');
          }}
          className="flex shrink-0 items-center gap-1.5 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-zinc-100 transition hover:bg-zinc-850"
        >
          <Plus className="h-4 w-4" />
          <span>{showAddForm ? '收起配置' : '登记新监控源'}</span>
        </button>
      </div>

      {showAddForm && (
        <form onSubmit={handleCreateSource} className="max-w-2xl space-y-4 rounded-lg border border-zinc-200 bg-zinc-50/70 p-6">
          <div>
            <h3 className="text-sm font-bold text-zinc-900">登记新的监控来源</h3>
            <p className="mt-1 text-xs leading-5 text-zinc-500">抖音来源继续写入 config.yaml；小宇宙节目、RSS 或单集会登记为数据库订阅源。</p>
          </div>

          <div className="inline-flex rounded-md border border-zinc-200 bg-white p-1">
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
                  newSourcePlatform === option.key ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-1">
              <label className="text-xs text-zinc-600">{newSourcePlatform === 'xiaoyuzhou' ? '小宇宙节目 / 单集 / RSS URL' : '抖音博主主页 URL'}</label>
              <input
                type="url"
                required
                placeholder={newSourcePlatform === 'xiaoyuzhou' ? 'https://.../rss 或 https://www.xiaoyuzhoufm.com/...' : 'https://www.douyin.com/user/MS...'}
                value={bLink}
                onChange={(event) => {
                  setBLink(event.target.value);
                  setSourcePreview(null);
                }}
                className="w-full rounded border border-zinc-250 bg-white px-3 py-2 text-sm focus:border-zinc-900 focus:outline-none"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-zinc-600">来源分类</label>
              <input
                type="text"
                list="source-category-options"
                placeholder="例如：科技、财经"
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                className="w-full rounded border border-zinc-250 bg-white px-3 py-2 text-sm focus:border-zinc-900 focus:outline-none"
              />
            </div>
          </div>

          {sourceError && (
            <p className="rounded border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">{sourceError}</p>
          )}

          {newSourcePlatform === 'xiaoyuzhou' && (
            <div className="rounded border border-emerald-100 bg-emerald-50/60 px-3 py-3 text-xs text-emerald-900">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <span>保存前可先解析公开信息，确认音频 URL 和最新单集可用。</span>
                <button
                  type="button"
                  disabled={!bLink.trim() || previewingSource}
                  onClick={handlePreviewSource}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded border border-emerald-200 bg-white px-3 font-semibold text-emerald-700 transition hover:bg-emerald-100 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {previewingSource && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{previewingSource ? '解析中' : '预览来源'}</span>
                </button>
              </div>
              {sourcePreview && (
                <div className="mt-3 grid gap-1.5 border-t border-emerald-100 pt-3">
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
              className="rounded border border-zinc-250 px-3.5 py-1.5 text-xs font-medium text-zinc-600 transition hover:bg-zinc-100"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submittingSource}
              className="rounded bg-zinc-900 px-4 py-1.5 text-xs font-semibold text-zinc-100 transition hover:bg-zinc-800 disabled:bg-zinc-400"
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
        <p className="rounded border border-red-100 bg-red-50 px-3 py-2 text-xs text-red-700">{sourceError}</p>
      )}
      {researchNotice && (
        <p className="rounded border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-800" role="status">
          {researchNotice}
        </p>
      )}

      <div className="inline-flex rounded-md border border-zinc-200 bg-white p-1">
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
              platformFilter === option.key ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900'
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <div className="flex items-center gap-4 rounded-lg border border-zinc-100 bg-zinc-50 p-4">
          <div className="shrink-0 rounded border border-zinc-150 bg-white p-3 text-zinc-900">
            <Tv className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500">自动监控来源</span>
            <span className="mt-0.5 block text-xl font-extrabold text-zinc-900">{configSources.length} 个</span>
            <span className="mt-0.5 block text-[10px] text-zinc-400">平均健康 {averageQuality}%</span>
          </div>
        </div>

        <div className="flex items-center gap-4 rounded-lg border border-zinc-100 bg-zinc-50 p-4">
          <div className="shrink-0 rounded border border-zinc-150 bg-white p-3 text-emerald-600">
            <CheckCircle className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500">当前启用</span>
            <span className="mt-0.5 block text-xl font-extrabold text-emerald-600">{activeCount} 个</span>
          </div>
        </div>

        <div className={`flex items-center gap-4 rounded-lg border p-4 ${needsAttentionCount > 0 || pausedConfigCount > 0 ? 'border-amber-150 bg-amber-50/60' : 'border-zinc-100 bg-zinc-50'}`}>
          <div className="shrink-0 rounded border border-zinc-150 bg-white p-3 text-amber-500">
            <Sparkles className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500">需要处理</span>
            <span className={`mt-0.5 block text-xl font-extrabold ${needsAttentionCount > 0 ? 'text-amber-700' : 'text-zinc-900'}`}>{needsAttentionCount} 个</span>
          </div>
        </div>

        <div className="flex items-center gap-4 rounded-lg border border-zinc-100 bg-zinc-50 p-4">
          <div className="shrink-0 rounded border border-zinc-150 bg-white p-3 text-zinc-500">
            <Database className="h-5 w-5" />
          </div>
          <div>
            <span className="block text-xs text-zinc-500">历史来源</span>
            <span className="mt-0.5 block text-xl font-extrabold text-zinc-900">{historyOnlyCount} 家</span>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-blue-100 bg-blue-50/60 px-4 py-3 text-xs leading-5 text-blue-900">
        健康指数综合最近检测成功率、抓取成功率、最近失败次数和解析完整度计算。抖音配置监控来源来自 config.yaml；小宇宙订阅源来自数据库，立即检查默认不发布 Pages、不推送飞书。
      </div>

      <section className="space-y-4 rounded-lg border border-zinc-150 bg-white p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-zinc-900">来源分类</h2>
            <p className="mt-1 text-xs leading-5 text-zinc-500">分类只作用于自动监控配置；资料库历史来源加入监控后才可分配分类。</p>
          </div>
          <form onSubmit={handleCategoryOptionAdd} className="flex w-full max-w-sm items-center gap-2">
            <label htmlFor="new-source-category" className="sr-only">新增来源分类</label>
            <input
              id="new-source-category"
              value={newCategory}
              onChange={(event) => setNewCategory(event.target.value)}
              placeholder="新增分类"
              className="h-9 min-w-0 flex-1 rounded border border-zinc-200 bg-zinc-50 px-3 text-sm text-zinc-800 focus:border-zinc-500 focus:bg-white focus:outline-none"
            />
            <button
              type="submit"
              disabled={!newCategory.trim() || editingCategoryOption === newCategory.trim()}
              className="inline-flex h-9 items-center gap-1.5 rounded bg-zinc-900 px-3 text-xs font-semibold text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>新增</span>
            </button>
          </form>
        </div>
        <div className="flex flex-wrap gap-2">
          {sourceCategories.map((option) => (
            <span key={option} className="inline-flex h-8 items-center gap-2 rounded border border-zinc-200 bg-zinc-50 pl-2.5 pr-1 text-xs font-medium text-zinc-700">
              <span>{option}</span>
              <span className="rounded bg-white px-1.5 py-0.5 text-[10px] text-zinc-400">{categoryUsage[option] || 0}</span>
              <button
                type="button"
                aria-label={`删除分类 ${option}`}
                title={categoryUsage[option] ? '先调整使用该分类的来源' : '删除分类'}
                disabled={Boolean(categoryUsage[option]) || editingCategoryOption === option}
                onClick={() => handleCategoryOptionDelete(option)}
                className="inline-flex h-6 w-6 items-center justify-center rounded text-zinc-400 transition hover:bg-red-50 hover:text-red-600 disabled:cursor-not-allowed disabled:text-zinc-200 disabled:hover:bg-transparent"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </span>
          ))}
          {sourceCategories.length === 0 && <span className="text-xs text-zinc-400">暂无可选分类。</span>}
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
        onCategoryDraftChange={(id, value) => setCategoryDrafts(prev => ({ ...prev, [id]: value }))}
        onCategorySave={handleCategorySave}
        onToggle={handleSourceToggle}
        onDelete={handleDeleteSource}
        onResearchAll={handleResearchAll}
        onCheckNow={handleCheckNow}
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
        onCategoryDraftChange={(id, value) => setCategoryDrafts(prev => ({ ...prev, [id]: value }))}
        onCategorySave={handleCategorySave}
        onToggle={handleSourceToggle}
        onDelete={handleDeleteSource}
        onResearchAll={handleResearchAll}
        onCheckNow={handleCheckNow}
        emptyText="暂无仅存在于数据库的历史来源。"
        compact
      />
    </div>
  );
}
