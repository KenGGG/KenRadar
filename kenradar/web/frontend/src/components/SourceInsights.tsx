/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { BarChart, Loader2, TrendingUp, Users } from 'lucide-react';
import { AsyncState } from './AsyncState';
import { useSourceInsights, useInsightsOverview } from '../hooks/useSourceInsights';
import { useSourceProfile } from '../hooks/useSourceProfile';
import type { SourceMetric } from '../types';

function MetricCard({ label, value, icon: Icon, accent }: {
  label: string; value: string | number; icon: React.ElementType; accent: string;
}) {
  return (
    <div className={`flex items-center gap-4 rounded-lg border p-4 ${accent}`}>
      <div className="shrink-0 rounded border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-3 text-zinc-700 dark:text-[var(--text-primary)]">
        <Icon className="h-5 w-5" />
      </div>
      <div>
        <span className="block text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{label}</span>
        <span className="mt-0.5 block text-xl font-extrabold text-zinc-900 dark:text-[var(--text-primary)]">{value}</span>
      </div>
    </div>
  );
}

function SourceRow({ source, isSelected, onClick }: {
  source: SourceMetric; isSelected: boolean; onClick: () => void;
}) {
  return (
    <tr
      onClick={onClick}
      className={`cursor-pointer text-sm transition hover:bg-zinc-50/60 dark:hover:bg-[var(--surface-muted)] ${
        isSelected ? 'bg-blue-50 dark:bg-[var(--info-bg)]' : ''
      }`}
    >
      <td className="p-3">
        <div className="font-semibold text-zinc-900 dark:text-[var(--text-primary)]">{source.display_name}</div>
        {source.category && (
          <span className="mt-0.5 inline-block rounded bg-zinc-100 dark:bg-[var(--surface-border)] px-1.5 py-0.5 text-[10px] text-zinc-500 dark:text-[var(--text-muted)]">
            {source.category}
          </span>
        )}
      </td>
      <td className="p-3 text-center font-mono text-zinc-600 dark:text-[var(--text-primary)]">{source.total_content}</td>
      <td className="p-3 text-center font-mono text-zinc-600 dark:text-[var(--text-primary)]">{source.rated_count}</td>
      <td className="p-3 text-center">
        <span className={`font-mono font-medium ${
          source.high_value_count > 0 ? 'text-emerald-600 dark:text-[var(--success)]' : 'text-zinc-400 dark:text-[var(--text-muted)]'
        }`}>
          {source.high_value_count}
        </span>
      </td>
      <td className="p-3 text-center font-mono text-zinc-600 dark:text-[var(--text-primary)]">{source.push_count}</td>
      <td className="p-3 text-center">
        <span className={`font-mono text-xs ${
          (source.avg_rating ?? 0) >= 7 ? 'text-emerald-600 dark:text-[var(--success)]' :
          (source.avg_rating ?? 0) > 0 ? 'text-amber-600 dark:text-[var(--warning)]' :
          'text-zinc-300 dark:text-[var(--text-muted)]'
        }`}>
          {source.avg_rating != null ? source.avg_rating.toFixed(1) : '-'}
        </span>
      </td>
    </tr>
  );
}

function ProfilePanel({ sourceId, days }: { sourceId: number; days: number }) {
  const { data, loading, error, refresh } = useSourceProfile(sourceId, days);

  return (
    <div className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">
          {data?.source.name || '来源详情'}
        </h3>
        <button
          onClick={refresh}
          className="rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-2.5 py-1 text-xs text-zinc-600 dark:text-[var(--text-secondary)] transition hover:bg-zinc-100 dark:hover:bg-[var(--surface-border)]"
        >
          刷新
        </button>
      </div>

      {/* Summary cards */}
      <AsyncState loading={loading} error={error} empty={false}>
        {data && (
          <div className="mb-4 grid grid-cols-3 gap-3">
            <div className="rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-3 text-center">
              <div className="text-xs text-zinc-500 dark:text-[var(--text-secondary)]">总内容</div>
              <div className="mt-1 text-lg font-bold text-zinc-900 dark:text-[var(--text-primary)]">{data.summary.total_content}</div>
            </div>
            <div className="rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-3 text-center">
              <div className="text-xs text-zinc-500 dark:text-[var(--text-secondary)]">已评分</div>
              <div className="mt-1 text-lg font-bold text-zinc-900 dark:text-[var(--text-primary)]">{data.summary.rated_count}</div>
            </div>
            <div className="rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-3 text-center">
              <div className="text-xs text-zinc-500 dark:text-[var(--text-secondary)]">高价值</div>
              <div className="mt-1 text-lg font-bold text-emerald-600 dark:text-[var(--success)]">{data.summary.high_value_count}</div>
            </div>
          </div>
        )}
      </AsyncState>

      {/* Mini bar chart */}
      <AsyncState loading={loading} error={error} empty={false}>
        {data && data.metrics.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-zinc-500 dark:text-[var(--text-secondary)] mb-2">每日内容量</div>
            <div className="flex h-24 items-end gap-px">
              {data.metrics.slice(-30).map((m, i) => {
                const maxVal = Math.max(...data.metrics.map(x => x.total_content), 1);
                const height = Math.max(2, (m.total_content / maxVal) * 100);
                const isHighValue = m.high_value_count > 0;
                return (
                  <div
                    key={i}
                    className={`flex-1 rounded-t transition-opacity hover:opacity-80 ${
                      isHighValue
                        ? 'bg-emerald-500 dark:bg-[var(--success)]'
                        : 'bg-zinc-300 dark:bg-[var(--surface-border)]'
                    }`}
                    style={{ height: `${height}%` }}
                    title={`${m.metric_date}: ${m.total_content} 条${isHighValue ? ` (${m.high_value_count} 高价值)` : ''}`}
                  />
                );
              })}
            </div>
            <div className="flex justify-between text-[10px] text-zinc-400 dark:text-[var(--text-muted)]">
              <span>{data.metrics[0]?.metric_date}</span>
              <span>{data.metrics[data.metrics.length - 1]?.metric_date}</span>
            </div>
            <div className="mt-1 flex items-center gap-3 text-[10px] text-zinc-400 dark:text-[var(--text-muted)]">
              <span className="flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-sm bg-zinc-300 dark:bg-[var(--surface-border)]" /> 普通
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block h-2 w-2 rounded-sm bg-emerald-500 dark:bg-[var(--success)]" /> 有高价值
              </span>
            </div>
          </div>
        )}
      </AsyncState>

      <AsyncState loading={loading} error={error} empty={false}>
        {data && data.metrics.length === 0 && (
          <div className="py-8 text-center text-xs text-zinc-400 dark:text-[var(--text-muted)]">
            暂无数据。请先运行分析扫描任务。
          </div>
        )}
      </AsyncState>

      {data && (data.topics?.length ?? 0) > 0 && (
        <div className="mt-5 border-t border-zinc-100 pt-4 dark:border-[var(--surface-border)]">
          <div className="mb-2 text-xs font-medium text-zinc-500 dark:text-[var(--text-secondary)]">主题分布（已有 AI 标签）</div>
          <div className="flex flex-wrap gap-2">
            {data.topics?.slice(0, 12).map((topic) => (
              <span key={topic.topic} className="rounded-full bg-blue-50 px-2.5 py-1 text-[11px] text-blue-700 dark:bg-[var(--info-bg)] dark:text-[var(--info)]">
                {topic.topic} · {Math.round(topic.content_ratio * 100)}%
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function SourceInsights() {
  const { items, loading, error, refresh } = useSourceInsights();
  const { data: overview, loading: overviewLoading } = useInsightsOverview(30);
  const [selectedSourceId, setSelectedSourceId] = useState<number | null>(null);
  const [days, setDays] = useState(30);

  return (
    <div className="space-y-8 animate-fade-in">
      <div className="flex flex-col items-start justify-between gap-4 border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4 sm:flex-row sm:items-center">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">来源洞察</h1>
          <p className="mt-1 text-sm text-zinc-500 dark:text-[var(--text-secondary)]">
            追踪每个监控来源的内容产出、评分分布和高价值比例。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-2.5 py-1.5 text-xs text-zinc-700 dark:text-[var(--text-primary)] focus:outline-none"
          >
            <option value={7}>近 7 天</option>
            <option value={30}>近 30 天</option>
            <option value={90}>近 90 天</option>
          </select>
          <button
            onClick={refresh}
            className="rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 py-1.5 text-xs font-medium text-zinc-600 dark:text-[var(--text-secondary)] transition hover:bg-zinc-100 dark:hover:bg-[var(--surface-border)]"
          >
            刷新
          </button>
        </div>
      </div>

      {/* Overview cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <MetricCard
          label="活跃来源"
          value={overview?.active_sources ?? '-'}
          icon={Users}
          accent="border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)]"
        />
        <MetricCard
          label="总内容量"
          value={overview?.total_content ?? '-'}
          icon={BarChart}
          accent="border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)]"
        />
        <MetricCard
          label="高价值内容"
          value={overview?.high_value_count ?? '-'}
          icon={TrendingUp}
          accent="border-emerald-100 dark:border-[var(--success-border)] bg-emerald-50 dark:bg-[var(--success-bg)]"
        />
        <MetricCard
          label="失败内容"
          value={overview?.failed_count ?? '-'}
          icon={TrendingUp}
          accent="border-red-100 dark:border-[var(--danger-border)] bg-red-50 dark:bg-[var(--danger-bg)]"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Source list */}
        <div className="lg:col-span-1">
          <AsyncState
            loading={loading}
            error={error}
            empty={!items.length}
            emptyView={
              <div className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-10 text-center">
                <div className="text-sm font-medium text-zinc-500 dark:text-[var(--text-secondary)]">暂无来源数据</div>
                <div className="mt-1 text-xs text-zinc-400 dark:text-[var(--text-muted)]">请先在来源管理中启用监控源，并运行分析扫描。</div>
              </div>
            }
            skeleton={
              <div className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-5">
                <div className="space-y-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-10 animate-pulse rounded bg-zinc-100 dark:bg-[var(--surface-muted)]" />
                  ))}
                </div>
              </div>
            }
          >
            <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-zinc-150 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                    <th className="p-3 font-semibold">来源</th>
                    <th className="p-3 text-center font-semibold">总量</th>
                    <th className="p-3 text-center font-semibold">已评</th>
                    <th className="p-3 text-center font-semibold">高价值</th>
                    <th className="p-3 text-center font-semibold">推送</th>
                    <th className="p-3 text-center font-semibold">均分</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {items.map((src) => (
                    <SourceRow
                      key={src.id}
                      source={src}
                      isSelected={selectedSourceId === src.id}
                      onClick={() => setSelectedSourceId(src.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </AsyncState>
        </div>

        {/* Profile panel */}
        <div className="lg:col-span-2">
          {selectedSourceId ? (
            <ProfilePanel sourceId={selectedSourceId} days={days} />
          ) : (
            <div className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-10 text-center">
              <div className="text-sm font-medium text-zinc-500 dark:text-[var(--text-secondary)]">选择一个来源查看详情</div>
              <div className="mt-1 text-xs text-zinc-400 dark:text-[var(--text-muted)]">点击左侧来源列表中的任一来源，查看其内容趋势和指标。</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
