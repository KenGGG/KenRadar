/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect, useRef } from 'react';
import {
  RotateCw,
  ChevronRight,
  Sparkles,
  CheckCircle2,
  Inbox,
  ArrowRight,
  Search,
  X,
  SlidersHorizontal,
} from 'lucide-react';
import { VideoContent, ResearchTask, MonitorSource } from '../types';
import { AsyncState } from './AsyncState';
import { CardSkeleton } from './Skeleton';
import { useContentItems } from '../hooks/useContentItems';
import { useDashboardOverview } from '../hooks/useDashboardOverview';
import DailyTrendChart from './charts/DailyTrendChart';
import PipelineStatusChart from './charts/PipelineStatusChart';

interface RadarDashboardProps {
  videos: VideoContent[];
  tasks: ResearchTask[];
  sources: MonitorSource[];
  navigateTo: (page: string, id: string | null) => void;
  triggerManualScan: () => void;
  testLatest: () => void;
  loading: boolean;
  highValueThreshold?: number;
}

// Filter bar state
interface DashboardFilters {
  keyword: string;
  status: string;
  highValue: boolean | undefined;
  reviewed: boolean | undefined;
}

function conclusionFor(video: VideoContent) {
  if (video.one_sentence_conclusion) return video.one_sentence_conclusion;
  const lines = (video.summary_markdown || '').split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    if (/^>\s*\[!summary\]/i.test(lines[index].trim())) {
      const parts: string[] = [];
      const inline = lines[index].replace(/^>\s*\[!summary\]\s*/i, '').trim();
      if (inline) parts.push(inline);
      while (index + 1 < lines.length && lines[index + 1].trim().startsWith('>')) {
        index += 1;
        parts.push(lines[index].trim().replace(/^>\s?/, ''));
      }
      return parts.join(' ').trim();
    }
  }
  return '';
}

function summaryFor(video: VideoContent) {
  if (video.brief_summary) return video.brief_summary;
  return (video.summary_markdown || '')
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
    .replace(/^#+\s+/gm, '')
    .replace(/^>\s*\[![^\]]+\]\s*/gm, '')
    .replace(/^>\s?/gm, '')
    .trim()
    .slice(0, 180);
}

function relativeTime(value?: string) {
  if (!value) return '未检查';
  const date = new Date(String(value).replace(/-/g, '/'));
  if (Number.isNaN(date.getTime())) return String(value);
  const diff = Date.now() - date.getTime();
  if (diff < 60 * 1000) return '刚刚';
  const minutes = Math.floor(diff / (60 * 1000));
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function isToday(value?: string) {
  if (!value) return false;
  const date = new Date(String(value).replace(/-/g, '/'));
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
}

export default function RadarDashboard({
  videos: bootstrapVideos,
  tasks,
  sources,
  navigateTo,
  triggerManualScan,
  testLatest,
  loading: bootstrapLoading,
  highValueThreshold: bootstrapThreshold,
}: RadarDashboardProps) {
  const [filters, setFilters] = useState<DashboardFilters>({
    keyword: '',
    status: '',
    highValue: undefined,
    reviewed: undefined,
  });
  const [showFilters, setShowFilters] = useState(false);
  const filterResetRef = useRef<HTMLButtonElement>(null);

  // Sync filters with hook params
  const {
    items: serverItems,
    loading: serverLoading,
    error: serverError,
    hasMore,
    highValueThreshold,
    setKeyword,
    setFilter,
    loadMore,
    refresh,
  } = useContentItems({
    status: filters.status || undefined,
    high_value: filters.highValue,
    reviewed: filters.reviewed,
    sort: 'priority_desc',
  });

  // Debounced keyword sync
  useEffect(() => {
    setKeyword(filters.keyword || undefined);
  }, [filters.keyword, setKeyword]);

  // Status/high_value/reviewed filter sync
  useEffect(() => {
    if (filters.status) setFilter('status', filters.status);
    else setFilter('status', undefined);
  }, [filters.status, setFilter]);

  useEffect(() => {
    setFilter('high_value', filters.highValue);
  }, [filters.highValue, setFilter]);

  useEffect(() => {
    setFilter('reviewed', filters.reviewed);
  }, [filters.reviewed, setFilter]);

  // Dashboard overview for trend charts
  const {
    data: overview,
    loading: overviewLoading,
    error: overviewError,
  } = useDashboardOverview();

  // Use server items if available, fall back to bootstrap data
  const activeLoading = serverLoading || bootstrapLoading;
  const hasServerData = serverItems.length > 0 || serverLoading;
  const displayItems = hasServerData ? serverItems : bootstrapVideos;

  // Derived stats
  const todayVideos = displayItems.filter(v => isToday(v.created_at) || isToday(v.updated_at));
  const todayReadable = todayVideos.filter(v => v.status === 'completed').length;
  const failedCount = displayItems.filter(v => v.status === 'failed').length;

  const threshold = highValueThreshold ?? bootstrapThreshold ?? 7;
  const highPriorityVideos = displayItems
    .filter(v => v.status === 'completed' && (v.rating >= threshold || v.recommend_action === 'push' || v.recommend_action === 'research'))
    .slice(0, 8);
  const failedOverviewList = displayItems.filter(v => v.status === 'failed').slice(0, 3);
  const activeSources = sources.filter(s => s.status === 'enabled').length;

  const clearFilters = () => {
    setFilters({ keyword: '', status: '', highValue: undefined, reviewed: undefined });
    refresh();
  };

  const hasActiveFilters = filters.keyword || filters.status || filters.highValue || filters.reviewed;

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Upper Welcome Header banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-zinc-200 dark:border-[var(--surface-border)] pb-5 gap-4">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">监控首页</h1>
          <p className="text-zinc-500 dark:text-[var(--text-secondary)] font-sans text-sm mt-1">抖音与小宇宙来源的新增内容、重点笔记和待处理失败。</p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            id="test_latest_btn"
            onClick={testLatest}
            className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-lg font-sans text-sm font-semibold transition cursor-pointer shadow-xs"
          >
            <Sparkles className="w-4 h-4 text-white" />
            <span>测试最新</span>
          </button>
          <button
            id="manual_scan_btn"
            onClick={triggerManualScan}
            className="flex items-center space-x-2 px-4 py-2 border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] rounded-lg font-sans text-sm font-semibold text-zinc-700 dark:text-[var(--text-secondary)] transition cursor-pointer shadow-2xs"
          >
            <RotateCw className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />
            <span>手动检测</span>
          </button>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400" />
          <input
            type="text"
            placeholder="搜索标题、创作者、摘要..."
            value={filters.keyword}
            onChange={(e) => setFilters(prev => ({ ...prev, keyword: e.target.value }))}
            className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-zinc-900 dark:text-[var(--text-primary)] placeholder-zinc-400 dark:placeholder-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-blue-500 dark:focus:ring-[var(--accent)] transition"
          />
          {filters.keyword && (
            <button
              onClick={() => setFilters(prev => ({ ...prev, keyword: '' }))}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-[var(--text-primary)]"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
        <button
          onClick={() => setShowFilters(!showFilters)}
          className={`flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border transition ${
            showFilters || hasActiveFilters
              ? 'bg-blue-50 dark:bg-[var(--info-bg)] border-blue-200 dark:border-[var(--info-border)] text-blue-700 dark:text-[var(--info)]'
              : 'border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-zinc-600 dark:text-[var(--text-secondary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]'
          }`}
        >
          <SlidersHorizontal className="w-4 h-4" />
          <span>筛选</span>
          {hasActiveFilters && (
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 dark:bg-[var(--accent)]" />
          )}
        </button>
        {hasActiveFilters && (
          <button
            ref={filterResetRef}
            onClick={clearFilters}
            className="px-3 py-2 text-sm rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-zinc-500 dark:text-[var(--text-secondary)] hover:text-zinc-700 dark:hover:text-[var(--text-primary)] transition"
          >
            清除
          </button>
        )}
      </div>

      {/* Expanded filter options */}
      {showFilters && (
        <div className="flex flex-wrap items-center gap-3 p-3 rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50/50 dark:bg-[var(--surface)]">
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-zinc-500 dark:text-[var(--text-muted)]">处理状态</label>
            <select
              value={filters.status}
              onChange={(e) => setFilters(prev => ({ ...prev, status: e.target.value }))}
              className="text-sm rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-zinc-700 dark:text-[var(--text-primary)] px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">全部</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
              <option value="processing">处理中</option>
              <option value="queued">排队中</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-zinc-500 dark:text-[var(--text-muted)]">高价值</label>
            <select
              value={filters.highValue === undefined ? '' : String(filters.highValue)}
              onChange={(e) => setFilters(prev => ({ ...prev, highValue: e.target.value === '' ? undefined : e.target.value === 'true' }))}
              className="text-sm rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-zinc-700 dark:text-[var(--text-primary)] px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">全部</option>
              <option value="true">仅高价值</option>
            </select>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs font-medium text-zinc-500 dark:text-[var(--text-muted)]">审阅状态</label>
            <select
              value={filters.reviewed === undefined ? '' : String(filters.reviewed)}
              onChange={(e) => setFilters(prev => ({ ...prev, reviewed: e.target.value === '' ? undefined : e.target.value === 'false' }))}
              className="text-sm rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] text-zinc-700 dark:text-[var(--text-primary)] px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">全部</option>
              <option value="false">未审阅</option>
            </select>
          </div>
        </div>
      )}

      {/* Grid Layout conforming to Section 3.1 (Left Core, Right Controls) */}
      <AsyncState loading={activeLoading} error={serverError} empty={!hasServerData && !activeLoading && displayItems.length === 0} skeleton={<CardSkeleton count={3} />}>
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        
        {/* Left Hand Core Information: High Value Queue & Stats */}
        <div className="xl:col-span-2 space-y-8">
          
          {/* Internal Stats Counter widgets */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3 bg-white dark:bg-[var(--surface)] rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] shadow-2xs flex flex-col justify-between">
              <span className="text-zinc-500 dark:text-[var(--text-secondary)] text-xs font-sans">今日新增</span>
              <span className="text-xl font-semibold font-sans text-zinc-900 dark:text-[var(--text-primary)] mt-2">{todayVideos.length} 条</span>
            </div>
            <div className="p-3 bg-white dark:bg-[var(--surface)] rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] shadow-2xs flex flex-col justify-between">
              <span className="text-zinc-500 dark:text-[var(--text-secondary)] text-xs font-sans">今日可读</span>
              <span className="text-xl font-semibold font-sans text-emerald-600 mt-2">{todayReadable} 篇</span>
            </div>
            <div className={`p-3 rounded-lg border flex flex-col justify-between ${failedCount > 0 ? 'bg-red-50/40 dark:bg-[var(--danger-bg)] border-red-150 dark:border-[var(--danger-border)]' : 'bg-white dark:bg-[var(--surface)] border-zinc-150 dark:border-[var(--surface-border)] shadow-2xs'}`}>
              <span className={`text-xs font-sans ${failedCount > 0 ? 'text-red-700 dark:text-[var(--danger)]' : 'text-zinc-500 dark:text-[var(--text-secondary)]'}`}>必须处理</span>
              <span className={`text-xl font-semibold font-sans mt-2 ${failedCount > 0 ? 'text-red-600 dark:text-[var(--danger)]' : 'text-zinc-900 dark:text-[var(--text-primary)]'}`}>{failedCount} 处</span>
            </div>
            <div className="p-3 bg-white dark:bg-[var(--surface)] rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] shadow-2xs flex flex-col justify-between">
              <span className="text-zinc-500 dark:text-[var(--text-secondary)] text-xs font-sans">活跃监控博主</span>
              <span className="text-xl font-semibold font-sans text-zinc-900 dark:text-[var(--text-primary)] mt-2">{activeSources} 家</span>
            </div>
          </div>

          {/* Core high-value video highlight cards */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-sans font-medium text-zinc-900 dark:text-[var(--text-primary)] flex items-center space-x-2">
                <span className="w-1.5 h-6 bg-blue-600 rounded-sm inline-block"></span>
                <span>今日重点内容</span>
              </h2>
              <button
                onClick={() => navigateTo('archive', null)}
                className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] hover:text-zinc-950 dark:hover:text-[var(--text-primary)] flex items-center space-x-1 transition font-sans"
              >
                <span>进入内容归档</span>
                <ChevronRight className="w-3 h-3" />
              </button>
            </div>

            {highPriorityVideos.length === 0 ? (
              <div className="p-8 border border-dashed border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] rounded-xl text-center text-zinc-500 dark:text-[var(--text-secondary)] font-sans">
                <Inbox className="w-8 h-8 mx-auto text-zinc-300 dark:text-[var(--text-muted)] stroke-1 mb-2" />
                <p className="text-sm">暂无重点推荐推送，试下“测试最新”快速模拟！</p>
              </div>
            ) : (
              <div className="space-y-3.5">
                {highPriorityVideos.map((video) => {
                  const conclusion = conclusionFor(video);
                  const summary = summaryFor(video);
                  return (
                  <div
                    key={video.id}
                    id={`high_priority_card_${video.id}`}
                    onClick={() => navigateTo('detail', video.id)}
                    className="group border border-zinc-200 dark:border-[var(--surface-border)] p-5 rounded-xl bg-white dark:bg-[var(--surface)] hover:border-zinc-900 dark:hover:border-[var(--text-primary)] shadow-2xs hover:shadow-sm transition duration-200 cursor-pointer flex flex-col gap-4"
                  >
                    <div className="space-y-2 flex-1 animate-fade-in">
                      <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                        <span className="text-xs font-mono px-2 py-0.5 rounded-sm bg-zinc-100 dark:bg-[var(--surface-muted)] text-zinc-650 dark:text-[var(--text-secondary)] font-medium">
                          {video.blogger}
                        </span>
                        <span className="text-xs font-sans font-medium text-amber-700 dark:text-[var(--warning)] bg-amber-50 dark:bg-[var(--warning-bg)] px-2 py-0.5 rounded-sm flex items-center space-x-1">
                          <span>★</span>
                          <span>{video.rating.toFixed(1)}分</span>
                        </span>
                        <span className="text-xs font-mono text-zinc-400">
                          {video.duration}
                        </span>
                      </div>
                      <h3 className="text-base font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] group-hover:text-blue-600 dark:group-hover:text-[var(--accent)] transition leading-snug">
                        {video.title}
                      </h3>
                      {conclusion && (
                        <p className="rounded-lg border border-blue-100 dark:border-[var(--info-border)] bg-blue-50/70 dark:bg-[var(--info-bg)] px-3 py-2 text-sm leading-6 text-blue-950 dark:text-[var(--text-primary)] line-clamp-2">
                          {conclusion}
                        </p>
                      )}
                      {summary && (
                        <p className="text-sm leading-6 text-zinc-600 dark:text-[var(--text-secondary)] line-clamp-2">
                          {summary}
                        </p>
                      )}
                      <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                        {video.tags.slice(0, 8).map((tag, idx) => (
                          <span key={idx} className="text-[10px] font-sans px-1.5 py-0.5 bg-zinc-50 dark:bg-[var(--surface-muted)] text-zinc-500 dark:text-[var(--text-muted)] rounded-sm border border-zinc-100 dark:border-[var(--surface-border)]">
                            #{tag}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="flex items-center justify-end space-x-2 text-zinc-400 dark:text-[var(--text-secondary)] group-hover:text-zinc-900 dark:group-hover:text-[var(--text-primary)] transition shrink-0">
                      <span className="text-xs font-sans font-medium">查看 Obsidian 笔记</span>
                      <ArrowRight className="w-4 h-4 translate-x-0 group-hover:translate-x-1 transition-all" />
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
            {hasMore && (
              <button
                onClick={loadMore}
                disabled={serverLoading}
                className="w-full py-2 text-sm text-zinc-500 dark:text-[var(--text-secondary)] hover:text-zinc-700 dark:hover:text-[var(--text-primary)] transition font-sans"
              >
                {serverLoading ? '加载中...' : '加载更多'}
              </button>
            )}
          </div>

          {/* Pending errors warning layout block */}
          <div className="space-y-4">
            <h2 className="text-lg font-sans font-medium text-zinc-900 dark:text-[var(--text-primary)] flex items-center space-x-2">
              <span className="w-1.5 h-6 bg-red-600 rounded-sm inline-block"></span>
              <span>待处理失败任务概览</span>
            </h2>

            {failedOverviewList.length === 0 ? (
              <div className="p-5 bg-emerald-50/20 dark:bg-[var(--success-bg)] border border-emerald-150 dark:border-[var(--success-border)] rounded-xl flex items-center space-x-3 text-emerald-800 dark:text-[var(--success)] shadow-2xs">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-[var(--success)] shrink-0" />
                <span className="text-sm font-sans font-medium">一切正常！当前无积压失败或挂起中断的调度工序。</span>
              </div>
            ) : (
              <div className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl overflow-hidden bg-white dark:bg-[var(--surface)] shadow-2xs">
                <div className="divide-y divide-zinc-200 dark:divide-[var(--surface-border)]">
                  {failedOverviewList.map((video) => (
                    <div 
                      key={video.id}
                      onClick={() => navigateTo('run', null)}
                      className="p-4 hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] cursor-pointer transition flex items-start justify-between gap-4"
                    >
                      <div className="space-y-1 flex-1">
                        <div className="flex items-center space-x-2.5">
                          <span className="text-xs font-sans font-medium text-red-600 dark:text-[var(--danger)] bg-red-50 dark:bg-[var(--danger-bg)] px-2 py-0.5 rounded">
                            {video.failed_at_step === 'download' ? '下载阶段失败' :
                             video.failed_at_step === 'transcribe' ? 'Whisper 转写故障' :
                             video.failed_at_step === 'ai' ? 'AI 整理中断' : '飞书推送异常'}
                          </span>
                          <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-mono">ID: {video.id}</span>
                        </div>
                        <h4 className="text-sm font-sans font-medium text-zinc-850 dark:text-[var(--text-primary)] line-clamp-1">{video.title}</h4>
                        <p className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-mono bg-zinc-50 dark:bg-[var(--surface-muted)] px-2 py-1 rounded border border-zinc-100 dark:border-[var(--surface-border)] mt-1.5 line-clamp-1 break-all">
                          {video.error_message}
                        </p>
                      </div>
                      <button className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] hover:text-zinc-950 dark:hover:text-[var(--text-primary)] font-sans font-medium flex items-center shrink-0 pt-0.5 transition">
                        <span>去重试</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
                <div className="bg-zinc-50 dark:bg-[var(--surface-muted)] border-t border-zinc-100 dark:border-[var(--surface-border)] px-4 py-2.5 text-center">
                  <button
                    onClick={() => navigateTo('run', null)}
                    className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] hover:text-zinc-950 dark:hover:text-[var(--text-primary)] font-sans font-semibold flex items-center justify-center mx-auto space-x-1.5 transition"
                  >
                    <span>进入处理流水线</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>

        </div>

        {/* Right Hand Column: Quick Actions & Navigation Shortcuts */}
        <div className="space-y-6">
          
          {/* Quick Tasks Control board */}
          <div className="p-6 border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl bg-white dark:bg-[var(--surface)] shadow-2xs space-y-4">
            <h3 className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm tracking-tight uppercase text-zinc-400 dark:text-[var(--text-muted)] font-bold font-mono">快捷操作面板</h3>
            
            <div className="space-y-2.5 pt-1.5">
              <button
                id="quick_research_single_btn"
                onClick={() => navigateTo('research', null)}
                className="w-full flex items-center justify-between p-3.5 rounded-lg bg-neutral-50/50 dark:bg-[var(--surface-muted)] border border-zinc-200 dark:border-[var(--surface-border)] hover:border-zinc-950 dark:hover:border-[var(--text-primary)] transition duration-150 text-left cursor-pointer hover:shadow-2xs"
              >
                <div>
                  <span className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm block">单视频快速分析</span>
                  <span className="text-zinc-500 dark:text-[var(--text-secondary)] text-xs mt-0.5 block font-sans">输入短链或awemeID单线重跑</span>
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400 dark:text-[var(--text-secondary)]" />
              </button>

              <button
                id="quick_research_blogger_btn"
                onClick={() => navigateTo('research', null)}
                className="w-full flex items-center justify-between p-3.5 rounded-lg bg-neutral-50/50 dark:bg-[var(--surface-muted)] border border-zinc-200 dark:border-[var(--surface-border)] hover:border-zinc-950 dark:hover:border-[var(--text-primary)] transition duration-150 text-left cursor-pointer hover:shadow-2xs"
              >
                <div>
                  <span className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm block">批量博主作品分析</span>
                  <span className="text-zinc-500 dark:text-[var(--text-secondary)] text-xs mt-0.5 block font-sans">按博主提取历史50条精细总结</span>
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400 dark:text-[var(--text-secondary)]" />
              </button>

              <button
                id="quick_log_monitor_btn"
                onClick={() => navigateTo('run', null)}
                className="w-full flex items-center justify-between p-3.5 rounded-lg bg-neutral-50/50 dark:bg-[var(--surface-muted)] border border-zinc-200 dark:border-[var(--surface-border)] hover:border-zinc-950 dark:hover:border-[var(--text-primary)] transition duration-150 text-left cursor-pointer hover:shadow-2xs"
              >
                <div>
                  <span className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm block">处理流水线</span>
                  <span className="text-zinc-500 dark:text-[var(--text-secondary)] text-xs mt-0.5 block font-sans">查看队列、异常和模型状态</span>
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400 dark:text-[var(--text-secondary)]" />
              </button>
            </div>
          </div>

          {/* Quick Source Checklist panel */}
          <div className="p-6 border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl bg-white dark:bg-[var(--surface)] shadow-2xs space-y-4">
            <h3 className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm tracking-tight uppercase text-zinc-400 dark:text-[var(--text-muted)] font-bold font-mono">来源健康摘要</h3>
            
            <div className="space-y-3">
              {sources.slice(0, 3).map((src) => (
                <div key={src.id} className="flex items-center justify-between">
                  <div className="space-y-0.5 flex-1 min-w-0 pr-2">
                    <span className="font-sans font-medium text-zinc-800 dark:text-[var(--text-primary)] text-sm block truncate">{src.name}</span>
                    <span className="text-zinc-400 dark:text-[var(--text-muted)] text-xs font-mono block">已捕获 {src.total_captured} 内容 · {relativeTime(src.last_checked)}</span>
                  </div>
                  <span className={`text-[10px] font-sans px-2 py-0.5 rounded-full shrink-0 ${
                    src.status === 'enabled' 
                      ? 'bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-700 dark:text-[var(--success)] font-semibold md:px-2.5'
                      : 'bg-zinc-100 dark:bg-[var(--surface-muted)] text-zinc-400 dark:text-[var(--text-muted)] font-medium'
                  }`}>
                    {src.status === 'enabled' ? '监控中' : '已暂停'}
                  </span>
                </div>
              ))}
              
              <div className="border-t border-zinc-100 pt-3 text-center">
                <button 
                  onClick={() => navigateTo('sources', null)}
                  className="text-xs text-zinc-500 hover:text-zinc-900 font-sans font-semibold flex items-center justify-center mx-auto space-x-1 transition"
                >
                  <span>管理全部监控来源</span>
                  <ChevronRight className="w-3 h-3" />
                </button>
              </div>
            </div>
          </div>

        </div>
        </div>

        {/* Trend Insights — charts section */}
        <div className="space-y-6">
          <h2 className="text-lg font-sans font-medium text-zinc-900 dark:text-[var(--text-primary)] flex items-center space-x-2">
            <span className="w-1.5 h-6 bg-blue-600 rounded-sm inline-block"></span>
            <span>趋势洞察</span>
          </h2>
          <div className="space-y-6">
            <AsyncState loading={overviewLoading} error={overviewError} empty={!overviewLoading && overview === null}>
              {overview && (
                <>
                  <DailyTrendChart data={overview.dailyTrend} onOpenDetails={() => navigateTo('archive', null)} />
                  <PipelineStatusChart data={overview.pipeline} onOpenDetails={() => navigateTo('run', null)} />
                </>
              )}
            </AsyncState>
          </div>
        </div>
      </AsyncState>
    </div>
  );
}
