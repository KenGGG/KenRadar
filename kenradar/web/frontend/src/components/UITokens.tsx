/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * Shared UI token components for KenRadar
 * Unified: ScoreBadge, ActionTag, BloggerLabel, RelativeTime, EmptyState
 */

import React from 'react';
import {
  BookOpen,
  CheckCircle2,
  Search,
  Sparkles,
  Star,
} from 'lucide-react';

/* ── ScoreBadge ── */
export function ScoreBadge({ rating, size = 'sm' }: { rating: number; size?: 'sm' | 'md' | 'lg' }) {
  const tone =
    rating >= 9.5 ? 'border-amber-200 bg-amber-50 text-amber-800' :
    rating >= 8.5 ? 'border-blue-100 bg-blue-50 text-blue-800' :
    rating >= 7   ? 'border-emerald-100 bg-emerald-50 text-emerald-700' :
                    'border-zinc-200 bg-zinc-50 text-zinc-600';
  const dims = size === 'sm' ? 'min-w-[2.5rem] text-xs' : size === 'md' ? 'min-w-[3rem] text-sm' : 'min-w-[3.5rem] text-base';
  return (
    <span className={`inline-flex items-center justify-center rounded-md border px-1.5 py-0.5 font-semibold tabular-nums leading-none ${tone} ${dims}`}>
      {rating > 0 ? rating.toFixed(1) : '-'}
    </span>
  );
}

/* ── ActionTag ── */
const ACTION_LABELS: Record<string, string> = {
  push: '推荐阅读',
  review: '待读内容',
  research: '建议研究',
  archive: '已归档',
  skip: '跳过',
};
function actionTone(action: string) {
  if (action === 'push') return 'bg-blue-50 text-blue-700 border-blue-100';
  if (action === 'review') return 'bg-amber-50 text-amber-700 border-amber-100';
  if (action === 'research') return 'bg-purple-50 text-purple-700 border-purple-100';
  if (action === 'archive') return 'bg-zinc-50 text-zinc-600 border-zinc-200';
  return 'bg-zinc-50 text-zinc-500 border-zinc-200';
}
export function ActionTag({ action }: { action: string }) {
  const label = ACTION_LABELS[action] || action || '未分流';
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-none ${actionTone(action)}`}>
      {label}
    </span>
  );
}

/* ── BloggerLabel ── */
export function BloggerLabel({ name }: { name: string }) {
  return <span className="font-medium text-zinc-700">{name || '未知来源'}</span>;
}

/* ── RelativeTime ── */
export function RelativeTime({ date }: { date?: string }) {
  if (!date) return <span className="text-zinc-400">-</span>;
  const d = new Date(String(date).replace(/-/g, '/'));
  if (Number.isNaN(d.getTime())) return <span className="text-zinc-400">{date}</span>;
  const now = new Date();
  const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);
  let text: string;
  if (diffSec < 60) text = '刚刚';
  else if (diffSec < 3600) text = `${Math.floor(diffSec / 60)}分钟前`;
  else if (diffSec < 86400) text = `${Math.floor(diffSec / 3600)}小时前`;
  else if (diffSec < 604800) text = `${Math.floor(diffSec / 86400)}天前`;
  else if (diffSec < 2592000) text = `${Math.floor(diffSec / 604800)}周前`;
  else text = d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' });
  return <span className="text-zinc-500" title={String(date).replace('T', ' ').slice(0, 16)}>{text}</span>;
}

/* ── DurationDisplay ── */
export function DurationDisplay({ duration }: { duration?: string }) {
  return duration ? <span className="font-mono text-zinc-500">{duration}</span> : null;
}

/* ── EmptyState ── */
interface EmptyStateProps {
  icon?: React.ElementType;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
}

const DEFAULT_ICONS: Record<string, React.ElementType> = {
  search: Search,
  empty: BookOpen,
  success: CheckCircle2,
  star: Star,
  sparkles: Sparkles,
};

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  const Comp = Icon || DEFAULT_ICONS.empty;
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-zinc-200 bg-white p-14 text-center">
      <Comp className="mx-auto mb-3 h-10 w-10 text-zinc-300" />
      <p className="text-sm font-semibold text-zinc-900">{title}</p>
      {description && <p className="mt-1 text-xs text-zinc-500">{description}</p>}
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-zinc-950 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-800"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}

/* ── FilterChip ── */
interface FilterChipProps {
  active?: boolean;
  children: React.ReactNode;
  onClick: () => void;
  count?: number;
}
export function FilterChip({ active, children, onClick, count }: FilterChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition ${
        active
          ? 'border-zinc-950 bg-zinc-950 text-white'
          : 'border-zinc-200 bg-white text-zinc-600 hover:border-zinc-300 hover:text-zinc-900'
      }`}
    >
      {children}
      {typeof count === 'number' && (
        <span className={`text-[10px] ${active ? 'text-zinc-300' : 'text-zinc-400'}`}>{count}</span>
      )}
    </button>
  );
}

/* ── InlineExpander ── */
interface InlineExpanderProps {
  expanded: boolean;
  children: React.ReactNode;
}
export function InlineExpander({ expanded, children }: InlineExpanderProps) {
  if (!expanded) return null;
  return (
    <div className="mt-3 animate-fade-in border-t border-blue-100 bg-blue-50/40 -mx-4 -mb-4 px-4 pb-4 pt-3 md:-mx-5 md:-mb-4 md:px-5">
      {children}
    </div>
  );
}
