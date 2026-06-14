/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useMemo, useState } from 'react';
import {
  ArrowUpDown,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileText,
  Filter,
  FolderOpen,
  Inbox,
  Library,
  Search,
  Sparkles,
  Star,
  Tags,
  UserRound,
} from 'lucide-react';
import { BriefFile, LibraryStats, NoteFile, VideoContent } from '../types';

interface ArchiveWorkspaceProps {
  videos: VideoContent[];
  libraryStats?: LibraryStats;
  navigateTo: (page: string, id: string | null) => void;
  pushToFeishuManually: (id: string) => void;
  generateWeeklyBrief: () => Promise<string>;
  notes: NoteFile[];
  briefs: BriefFile[];
}

type SortMode = 'recommended' | 'latest' | 'score' | 'duration' | 'recentRead';
type TimeFilter = 'all' | 'today' | 'week' | 'month';
type SmartView = 'recommended' | 'unread' | 'recent' | 'perfect' | 'long' | 'pushed';
type ArchiveMode = 'library' | 'notes' | 'briefs';

const ACTION_LABELS: Record<string, string> = {
  push: '推荐阅读',
  review: '待读内容',
  research: '建议研究',
  archive: '已归档',
  skip: '跳过',
};

const SMART_VIEWS: { id: SmartView; label: string; icon: React.ElementType }[] = [
  { id: 'recommended', label: '推荐阅读', icon: Sparkles },
  { id: 'unread', label: '待读内容', icon: Inbox },
  { id: 'recent', label: '最近归档', icon: Clock3 },
  { id: 'perfect', label: '10分内容', icon: Star },
  { id: 'long', label: '长视频精华', icon: BookOpen },
  { id: 'pushed', label: '已推送飞书', icon: CheckCircle2 },
];

function isReadable(video: VideoContent) {
  return video.status === 'completed' || Boolean(video.summary_markdown || video.summary_path);
}

function parseDate(value?: string) {
  if (!value) return null;
  const date = new Date(String(value).replace(/-/g, '/'));
  return Number.isNaN(date.getTime()) ? null : date;
}

function withinTime(value: string | undefined, filter: TimeFilter) {
  if (filter === 'all') return true;
  const date = parseDate(value);
  if (!date) return false;
  const now = new Date();
  const age = now.getTime() - date.getTime();
  if (filter === 'today') return date.toDateString() === now.toDateString();
  if (filter === 'week') return age <= 7 * 24 * 60 * 60 * 1000;
  if (filter === 'month') return age <= 30 * 24 * 60 * 60 * 1000;
  return true;
}

function durationMinutes(value?: string) {
  if (!value) return 0;
  const parts = String(value).match(/\d+/g)?.map(Number) || [];
  if (parts.length >= 3) return parts[0] * 60 + parts[1] + parts[2] / 60;
  if (parts.length === 2) return parts[0] + parts[1] / 60;
  if (parts.length === 1) return parts[0];
  return 0;
}

function recommendWeight(video: VideoContent) {
  const action = video.recommend_action || '';
  const actionWeight = action === 'push' ? 40 : action === 'review' ? 30 : action === 'research' ? 25 : action === 'archive' ? 10 : 0;
  return actionWeight + Number(video.rating || 0);
}

function sortArchive(a: VideoContent, b: VideoContent, mode: SortMode) {
  if (mode === 'score') return Number(b.rating || 0) - Number(a.rating || 0);
  if (mode === 'duration') return durationMinutes(b.duration) - durationMinutes(a.duration);
  if (mode === 'latest' || mode === 'recentRead') return String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at));
  const byRecommend = recommendWeight(b) - recommendWeight(a);
  if (byRecommend !== 0) return byRecommend;
  return String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at));
}

function summaryFor(video: VideoContent, length = 220) {
  if (video.brief_summary) return video.brief_summary;
  const cleaned = (video.summary_markdown || '')
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
    .replace(/^#+\s+/gm, '')
    .replace(/^>\s*\[![^\]]+\]\s*/gm, '')
    .replace(/^>\s?/gm, '')
    .replace(/\[\[([^\]]+)\]\]/g, '$1')
    .trim();
  return cleaned.slice(0, length);
}

function conclusionFor(video: VideoContent) {
  if (video.one_sentence_conclusion) return video.one_sentence_conclusion;
  const markdown = video.summary_markdown || '';
  const lines = markdown.split(/\r?\n/);
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

function actionLabel(value: string) {
  return ACTION_LABELS[value] || value || '未分流';
}

function readableDate(value?: string) {
  if (!value) return '-';
  return String(value).replace('T', ' ').slice(0, 16);
}

function publishedDate(video: VideoContent) {
  return readableDate(video.published_at || video.created_at);
}

function collectedDate(video: VideoContent) {
  return readableDate(video.collected_at || video.updated_at || video.created_at);
}

function scoreTone(rating: number) {
  if (rating >= 9.5) return 'border-amber-200 bg-amber-50 text-amber-800';
  if (rating >= 8.5) return 'border-blue-100 bg-blue-50 text-blue-800';
  if (rating >= 7) return 'border-emerald-100 bg-emerald-50 text-emerald-700';
  return 'border-zinc-200 bg-zinc-50 text-zinc-600';
}

function applySmartView(video: VideoContent, view: SmartView) {
  if (view === 'recommended') return ['push', 'research'].includes(video.recommend_action) || Number(video.rating || 0) >= 8.5;
  if (view === 'unread') return video.recommend_action === 'review' || (video.recommend_action !== 'skip' && video.push_status !== 'success');
  if (view === 'recent') return withinTime(video.updated_at || video.created_at, 'week');
  if (view === 'perfect') return Number(video.rating || 0) >= 9.5;
  if (view === 'long') return durationMinutes(video.duration) >= 20;
  if (view === 'pushed') return video.push_status === 'success' || video.recommend_action === 'push';
  return true;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="px-2 pt-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400">{children}</div>;
}

interface NavButtonProps {
  active: boolean;
  children: React.ReactNode;
  count?: number;
  icon: React.ElementType;
  onClick: () => void;
  key?: React.Key;
}

function NavButton({
  active,
  children,
  count,
  icon: Icon,
  onClick,
}: NavButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex min-h-10 w-full items-center justify-between gap-3 rounded-md px-2.5 py-2 text-left text-sm transition ${
        active ? 'bg-zinc-950 text-white' : 'text-zinc-650 hover:bg-white hover:text-zinc-950'
      }`}
    >
      <span className="flex min-w-0 items-center gap-2">
        <Icon className={`h-4 w-4 shrink-0 ${active ? 'text-white' : 'text-zinc-400'}`} />
        <span className="truncate">{children}</span>
      </span>
      {typeof count === 'number' && <span className={`font-mono text-[11px] ${active ? 'text-zinc-200' : 'text-zinc-400'}`}>{count}</span>}
    </button>
  );
}

interface ContentListItemProps {
  video: VideoContent;
  selected: boolean;
  onSelect: () => void;
  onRead: () => void;
  key?: React.Key;
}

function ContentListItem({
  video,
  selected,
  onSelect,
  onRead,
}: ContentListItemProps) {
  const conclusion = conclusionFor(video);
  const summary = summaryFor(video, 150);
  return (
    <article
      onClick={onSelect}
      className={`group cursor-pointer border-b border-zinc-100 px-4 py-4 transition md:px-5 ${
        selected ? 'bg-blue-50/70 shadow-[inset_3px_0_0_rgb(37,99,235)]' : 'bg-white hover:bg-zinc-50'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 flex h-10 w-12 shrink-0 items-center justify-center rounded-md border text-sm font-semibold tabular-nums ${scoreTone(video.rating)}`}>
          {video.rating > 0 ? video.rating.toFixed(1) : '-'}
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-500">
            <span className="font-medium text-zinc-700">{video.blogger || '未知来源'}</span>
            {video.duration && <span className="font-mono">{video.duration}</span>}
            <span>发表 {publishedDate(video)}</span>
            <span>收录 {collectedDate(video)}</span>
            {video.recommend_action && <span className="text-blue-700">{actionLabel(video.recommend_action)}</span>}
          </div>
          <button
            type="button"
            onClick={event => {
              event.stopPropagation();
              onRead();
            }}
            className="block w-full text-left text-[15px] font-semibold leading-6 text-zinc-950 hover:text-blue-700"
          >
            {video.title || '无标题'}
          </button>
          <p className="mt-1 text-sm leading-6 text-zinc-650 line-clamp-2">
            {conclusion ? <><span className="font-medium text-zinc-900">一句话：</span>{conclusion}</> : summary || '暂无摘要，点击进入详情查看完整笔记。'}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {(video.tags || []).slice(0, 6).map(tag => (
              <span key={tag} className="rounded bg-zinc-100 px-1.5 py-0.5 text-[11px] text-zinc-600">#{tag}</span>
            ))}
          </div>
        </div>
        <button
          type="button"
          onClick={event => {
            event.stopPropagation();
            onRead();
          }}
          className="hidden shrink-0 items-center gap-1 rounded-md border border-zinc-200 bg-white px-3 py-2 text-xs font-semibold text-zinc-700 hover:border-blue-200 hover:text-blue-700 group-hover:inline-flex md:inline-flex"
        >
          阅读
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </article>
  );
}

function PreviewPanel({ video, onRead }: { video: VideoContent | null; onRead: (id: string) => void }) {
  if (!video) {
    return (
      <aside className="rounded-lg border border-dashed border-zinc-200 bg-white p-8 text-center text-zinc-500 xl:sticky xl:top-4">
        <BookOpen className="mx-auto mb-3 h-9 w-9 text-zinc-300" />
        <p className="text-sm font-medium text-zinc-800">选择一篇内容，查看摘要、推荐理由和关联笔记。</p>
      </aside>
    );
  }

  const conclusion = conclusionFor(video);
  return (
    <aside className="rounded-lg border border-zinc-150 bg-white p-5 shadow-2xs xl:sticky xl:top-4 xl:max-h-[calc(100vh-3rem)] xl:overflow-auto">
      <div className="space-y-5">
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <span className={`rounded-md border px-2 py-1 text-xs font-semibold tabular-nums ${scoreTone(video.rating)}`}>
              {video.rating > 0 ? `${video.rating.toFixed(1)} 分` : '未评分'}
            </span>
            {video.recommend_action && <span className="rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">{actionLabel(video.recommend_action)}</span>}
          </div>
          <h2 className="text-lg font-semibold leading-7 text-zinc-950">{video.title || '无标题'}</h2>
          <p className="mt-2 text-xs text-zinc-500">{video.blogger || '未知来源'} · {video.duration || '未知时长'}</p>
          <p className="mt-1 text-xs text-zinc-500">发表 {publishedDate(video)} · 收录 {collectedDate(video)}</p>
        </div>

        {conclusion && (
          <section className="rounded-lg border border-blue-100 bg-blue-50/70 p-3">
            <div className="mb-1 text-xs font-semibold text-blue-700">一句话结论</div>
            <p className="text-sm leading-6 text-blue-950">{conclusion}</p>
          </section>
        )}

        {video.recommendation_reason && (
          <section>
            <h3 className="mb-1 text-xs font-semibold text-zinc-500">为什么推荐</h3>
            <p className="text-sm leading-6 text-zinc-700">{video.recommendation_reason}</p>
          </section>
        )}

        <section>
          <h3 className="mb-1 text-xs font-semibold text-zinc-500">核心摘要</h3>
          <p className="text-sm leading-6 text-zinc-700">{summaryFor(video, 360) || '暂无摘要。'}</p>
        </section>

        {(video.tags || []).length > 0 && (
          <section>
            <h3 className="mb-2 text-xs font-semibold text-zinc-500">标签</h3>
            <div className="flex flex-wrap gap-1.5">
              {(video.tags || []).slice(0, 12).map(tag => (
                <span key={tag} className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-650">#{tag}</span>
              ))}
            </div>
          </section>
        )}

        <dl className="space-y-2 border-t border-zinc-100 pt-4 text-xs">
          <div className="flex justify-between gap-4">
            <dt className="text-zinc-500">来源</dt>
            <dd className="text-right font-medium text-zinc-900">{video.blogger || '-'}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-zinc-500">发表时间</dt>
            <dd className="text-right font-mono text-zinc-700">{publishedDate(video)}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-zinc-500">系统收录</dt>
            <dd className="text-right font-mono text-zinc-700">{collectedDate(video)}</dd>
          </div>
        </dl>

        <div className="flex flex-col gap-2 border-t border-zinc-100 pt-4">
          <button
            type="button"
            onClick={() => onRead(video.id)}
            className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md bg-zinc-950 px-4 py-2 text-sm font-semibold text-white hover:bg-zinc-800"
          >
            <BookOpen className="h-4 w-4" />
            阅读完整笔记
          </button>
          {video.original_url && (
            <a
              href={video.original_url}
              target="_blank"
              rel="noreferrer"
              referrerPolicy="no-referrer"
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-zinc-200 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
            >
              <ExternalLink className="h-4 w-4" />
              原视频链接
            </a>
          )}
        </div>
      </div>
    </aside>
  );
}

export default function ArchiveWorkspace({
  videos,
  libraryStats,
  navigateTo,
  notes,
  briefs,
}: ArchiveWorkspaceProps) {
  const archiveMode: ArchiveMode = window.location.pathname.includes('/archive/notes')
    ? 'notes'
    : window.location.pathname.includes('/archive/briefs')
      ? 'briefs'
      : 'library';
  const initialBlogger = archiveMode === 'library'
    ? new URLSearchParams(window.location.search).get('blogger')?.trim() || 'all'
    : 'all';
  const [mode, setMode] = useState<ArchiveMode>(archiveMode);
  const [smartView, setSmartView] = useState<SmartView>('recommended');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBlogger, setSelectedBlogger] = useState(initialBlogger);
  const [selectedTag, setSelectedTag] = useState('all');
  const [filterAction, setFilterAction] = useState('all');
  const [minRating, setMinRating] = useState<number>(0);
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>(initialBlogger === 'all' ? 'recommended' : 'latest');
  const [showMoreFilters, setShowMoreFilters] = useState(false);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [selectedSourceGroup, setSelectedSourceGroup] = useState('all');

  useEffect(() => setMode(archiveMode), [archiveMode]);

  const readableVideos = useMemo(() => videos.filter(isReadable), [videos]);

  const bloggers = useMemo(() => {
    const values = new Set<string>(readableVideos.map(video => String(video.blogger || '')).filter(Boolean));
    return Array.from(values).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }, [readableVideos]);

  const tags = useMemo(() => {
    const allTags = readableVideos.flatMap(video => video.tags || []).map(tag => String(tag || '')).filter(Boolean);
    return Array.from(new Set<string>(allTags)).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN')).slice(0, 120);
  }, [readableVideos]);

  const sourceCounts = useMemo(() => {
    const counter = new Map<string, number>();
    readableVideos.forEach(video => counter.set(video.blogger || '未知来源', (counter.get(video.blogger || '未知来源') || 0) + 1));
    return Array.from(counter.entries()).sort((a, b) => b[1] - a[1]);
  }, [readableVideos]);

  const sourceCategoryByBlogger = useMemo(() => {
    const buckets = new Map<string, Map<string, number>>();
    readableVideos.forEach(video => {
      const blogger = video.blogger || '未知来源';
      const category = (video.tags || []).find(tag => String(tag || '').trim()) || '未分类';
      if (!buckets.has(blogger)) buckets.set(blogger, new Map());
      const counter = buckets.get(blogger)!;
      counter.set(category, (counter.get(category) || 0) + 1);
    });
    const result = new Map<string, string>();
    buckets.forEach((counter, blogger) => {
      const [category] = Array.from(counter.entries()).sort((a, b) => b[1] - a[1])[0] || ['未分类'];
      result.set(blogger, category);
    });
    return result;
  }, [readableVideos]);

  const sourceGroups = useMemo(() => {
    const counter = new Map<string, number>();
    readableVideos.forEach(video => {
      const blogger = video.blogger || '未知来源';
      const category = sourceCategoryByBlogger.get(blogger) || '未分类';
      counter.set(category, (counter.get(category) || 0) + 1);
    });
    return Array.from(counter.entries()).sort((a, b) => b[1] - a[1]).slice(0, 10);
  }, [readableVideos, sourceCategoryByBlogger]);

  const stats = useMemo(() => {
    const recommended = readableVideos.filter(video => ['push', 'research'].includes(video.recommend_action) || Number(video.rating || 0) >= 8.5).length;
    const unread = readableVideos.filter(video => video.recommend_action === 'review' || (video.recommend_action !== 'skip' && video.push_status !== 'success')).length;
    const actualNotes = Number(libraryStats?.content_notes || 0);
    const loadedItems = Number(libraryStats?.loaded_items || videos.length);
    const totalItems = Number(libraryStats?.total_items || videos.length);
    return {
      readable: readableVideos.length,
      actualNotes: actualNotes || readableVideos.length,
      loadedItems: loadedItems || videos.length,
      totalItems: totalItems || videos.length,
      displayLimit: Number(libraryStats?.display_limit || 0),
      recommended,
      unread,
      briefs: briefs.length,
    };
  }, [readableVideos, briefs.length, libraryStats, videos.length]);

  const smartCounts = useMemo(() => {
    return SMART_VIEWS.reduce<Record<SmartView, number>>((acc, view) => {
      acc[view.id] = readableVideos.filter(video => applySmartView(video, view.id)).length;
      return acc;
    }, {} as Record<SmartView, number>);
  }, [readableVideos]);

  const filteredVideos = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return readableVideos
      .filter(video => mode === 'library')
      .filter(video => selectedBlogger !== 'all' || applySmartView(video, smartView))
      .filter(video => selectedSourceGroup === 'all' || (sourceCategoryByBlogger.get(video.blogger || '未知来源') || '未分类') === selectedSourceGroup)
      .filter(video => selectedBlogger === 'all' || video.blogger === selectedBlogger)
      .filter(video => selectedTag === 'all' || (video.tags || []).includes(selectedTag))
      .filter(video => filterAction === 'all' || video.recommend_action === filterAction)
      .filter(video => Number(video.rating || 0) >= minRating)
      .filter(video => withinTime(video.updated_at || video.created_at, timeFilter))
      .filter(video => {
        if (!q) return true;
        return [
          video.id,
          video.title,
          video.blogger,
          video.brief_summary || '',
          video.one_sentence_conclusion || '',
          video.recommendation_reason || '',
          video.summary_markdown || '',
          video.whisper_text || '',
          ...(video.tags || []),
        ].join(' ').toLowerCase().includes(q);
      })
      .sort((a, b) => sortArchive(a, b, sortMode));
  }, [readableVideos, mode, smartView, selectedSourceGroup, sourceCategoryByBlogger, selectedBlogger, selectedTag, filterAction, minRating, timeFilter, searchQuery, sortMode]);

  useEffect(() => {
    if (mode !== 'library') {
      setSelectedVideoId(null);
      return;
    }
    if (!filteredVideos.length) {
      setSelectedVideoId(null);
      return;
    }
    if (!selectedVideoId || !filteredVideos.some(video => video.id === selectedVideoId)) {
      setSelectedVideoId(filteredVideos[0].id);
    }
  }, [filteredVideos, mode, selectedVideoId]);

  const selectedVideo = filteredVideos.find(video => video.id === selectedVideoId) || null;
  const hasActiveFilters = selectedBlogger !== 'all' || selectedTag !== 'all' || filterAction !== 'all' || minRating > 0 || timeFilter !== 'all';

  const clearFilters = () => {
    setSelectedBlogger('all');
    setSelectedSourceGroup('all');
    setSelectedTag('all');
    setFilterAction('all');
    setMinRating(0);
    setTimeFilter('all');
    window.history.pushState(null, '', '/archive');
  };

  const openDetail = (id: string) => navigateTo('detail', id);
  const switchMode = (nextMode: ArchiveMode) => {
    setMode(nextMode);
    window.history.pushState(null, '', nextMode === 'notes' ? '/archive/notes' : nextMode === 'briefs' ? '/archive/briefs' : '/archive');
  };
  const openBloggerDirectory = (blogger: string) => {
    if (blogger === 'all') {
      clearFilters();
      return;
    }
    setMode('library');
    setSelectedBlogger(blogger);
    setSelectedSourceGroup('all');
    setSelectedTag('all');
    setFilterAction('all');
    setMinRating(0);
    setTimeFilter('all');
    setSearchQuery('');
    setSortMode('latest');
    window.history.pushState(null, '', `/archive?blogger=${encodeURIComponent(blogger)}`);
  };

  return (
    <div className="animate-fade-in space-y-5 font-sans">
      <header className="border-b border-zinc-200 pb-4">
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-900">阅读库</h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-zinc-500">
          阅读已归档内容，按来源、标签、评分和推荐动作快速定位值得沉淀的笔记。
        </p>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500">
          <span>内容笔记 <strong className="font-mono text-zinc-900">{stats.actualNotes}</strong> 篇</span>
          <span className="text-zinc-300">·</span>
          <span>当前加载 <strong className="font-mono text-zinc-900">{stats.readable}</strong> 篇</span>
          <span className="text-zinc-300">·</span>
          <span>推荐阅读 <strong className="font-mono text-zinc-900">{stats.recommended}</strong> 篇</span>
          <span className="text-zinc-300">·</span>
          <span>待读 <strong className="font-mono text-zinc-900">{stats.unread}</strong> 篇</span>
          <span className="text-zinc-300">·</span>
          <span>简报 <strong className="font-mono text-zinc-900">{stats.briefs}</strong> 份</span>
          {stats.loadedItems < stats.totalItems && (
            <>
              <span className="text-zinc-300">·</span>
              <span>共收录 <strong className="font-mono text-zinc-900">{stats.totalItems}</strong> 条，当前展示上限 {stats.displayLimit}</span>
            </>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[230px_minmax(0,1fr)_360px]">
        <aside className="rounded-lg border border-zinc-150 bg-zinc-50/70 p-2 xl:sticky xl:top-4 xl:self-start">
          <nav className="space-y-4">
            <div className="space-y-1">
              <SectionTitle>智能视图</SectionTitle>
              {SMART_VIEWS.map(view => (
                <NavButton
                  key={view.id}
                  active={mode === 'library' && selectedBlogger === 'all' && smartView === view.id}
                  count={smartCounts[view.id]}
                  icon={view.icon}
                  onClick={() => {
                    switchMode('library');
                    setSelectedBlogger('all');
                    setSelectedSourceGroup('all');
                    setSmartView(view.id);
                  }}
                >
                  {view.label}
                </NavButton>
              ))}
            </div>

            <div className="space-y-1">
              <SectionTitle>来源</SectionTitle>
              <NavButton
                active={mode === 'library' && selectedSourceGroup === 'all' && selectedBlogger === 'all'}
                count={readableVideos.length}
                icon={Library}
                onClick={() => {
                  switchMode('library');
                  setSelectedSourceGroup('all');
                  setSelectedBlogger('all');
                }}
              >
                全部来源
              </NavButton>
              {sourceGroups.map(([group, count]) => (
                <NavButton
                  key={group}
                  active={mode === 'library' && selectedSourceGroup === group && selectedBlogger === 'all'}
                  count={count}
                  icon={FolderOpen}
                  onClick={() => {
                    switchMode('library');
                    setSelectedSourceGroup(group);
                    setSelectedBlogger('all');
                  }}
                >
                  {group}
                </NavButton>
              ))}
              {selectedSourceGroup !== 'all' && (
                <div className="ml-2 border-l border-zinc-200 pl-2 space-y-1">
                  {sourceCounts
                    .filter(([blogger]) => (sourceCategoryByBlogger.get(blogger) || '未分类') === selectedSourceGroup)
                    .slice(0, 8)
                    .map(([blogger, count]) => (
                      <NavButton
                        key={blogger}
                        active={mode === 'library' && selectedBlogger === blogger}
                        count={count}
                        icon={Tags}
                        onClick={() => openBloggerDirectory(blogger)}
                      >
                        {blogger}
                      </NavButton>
                    ))}
                </div>
              )}
            </div>

            <div className="space-y-2">
              <SectionTitle>博主目录</SectionTitle>
              <label className="relative block px-1">
                <UserRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                <select
                  aria-label="选择博主查看全部笔记"
                  value={selectedBlogger}
                  onChange={event => openBloggerDirectory(event.target.value)}
                  className="min-h-10 w-full rounded-md border border-zinc-200 bg-white py-2 pl-8 pr-7 text-sm text-zinc-700 focus:border-blue-500 focus:outline-none"
                >
                  <option value="all">选择博主</option>
                  {sourceCounts.map(([blogger, count]) => (
                    <option key={blogger} value={blogger}>{blogger}（{count}）</option>
                  ))}
                </select>
              </label>
              <p className="px-2 text-[11px] leading-5 text-zinc-400">选择后查看该博主的全部已归档笔记。</p>
            </div>

            <div className="space-y-1">
              <SectionTitle>资产</SectionTitle>
              <NavButton active={mode === 'notes'} count={notes.length} icon={FileText} onClick={() => switchMode('notes')}>
                Obsidian 笔记
              </NavButton>
              <NavButton active={mode === 'briefs'} count={briefs.length} icon={CalendarDays} onClick={() => switchMode('briefs')}>
                简报文件
              </NavButton>
            </div>
          </nav>
        </aside>

        <main className="min-w-0">
          {mode === 'notes' && (
            <section className="overflow-hidden rounded-lg border border-zinc-150 bg-white">
              <div className="border-b border-zinc-100 px-5 py-4">
                <h2 className="text-lg font-semibold text-zinc-950">Obsidian 笔记</h2>
                <p className="mt-1 text-sm text-zinc-500">查看本地 Markdown 文件索引，阅读入口会优先跳转到统一内容详情。</p>
              </div>
              {notes.length === 0 ? (
                <div className="p-12 text-center text-zinc-500">
                  <FileText className="mx-auto mb-3 h-10 w-10 text-zinc-300" />
                  <p className="text-sm font-semibold text-zinc-900">暂无 Markdown 笔记文件</p>
                </div>
              ) : (
                <div className="divide-y divide-zinc-100">
                  {notes.map(note => (
                    <a key={note.path} href={`/file?path=${encodeURIComponent(note.path)}`} className="block px-5 py-4 transition hover:bg-zinc-50">
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div className="min-w-0">
                          <div className="line-clamp-1 text-sm font-semibold text-zinc-950">{note.title || note.name}</div>
                          <div className="mt-1 text-xs text-zinc-500">{note.platform} / {note.blogger}</div>
                        </div>
                        <div className="shrink-0 text-xs font-mono text-zinc-400">{note.updated_at} · {note.size_kb} KB</div>
                      </div>
                    </a>
                  ))}
                </div>
              )}
            </section>
          )}

          {mode === 'briefs' && (
            <section className="overflow-hidden rounded-lg border border-zinc-150 bg-white">
              <div className="border-b border-zinc-100 px-5 py-4">
                <h2 className="text-lg font-semibold text-zinc-950">简报文件</h2>
                <p className="mt-1 text-sm text-zinc-500">查看历史流媒体简报和研究简报。</p>
              </div>
              {briefs.length === 0 ? (
                <div className="p-12 text-center text-zinc-500">
                  <CalendarDays className="mx-auto mb-3 h-10 w-10 text-zinc-300" />
                  <p className="text-sm font-semibold text-zinc-900">暂无历史简报</p>
                </div>
              ) : (
                <div className="divide-y divide-zinc-100">
                  {briefs.map(brief => (
                    <a key={brief.path} href={`/file?path=${encodeURIComponent(brief.path)}`} className="block px-5 py-4 transition hover:bg-zinc-50">
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div className="min-w-0">
                          <div className="line-clamp-1 text-sm font-semibold text-zinc-950">{brief.title || brief.name}</div>
                          <div className="mt-1 text-xs text-zinc-500">{brief.item_count} 条内容 · {brief.status}</div>
                        </div>
                        <div className="shrink-0 text-xs font-mono text-zinc-400">{brief.created_at}</div>
                      </div>
                    </a>
                  ))}
                </div>
              )}
            </section>
          )}

          {mode === 'library' && (
            <section className="space-y-3">
              <div className="rounded-lg border border-zinc-150 bg-white p-3">
                {selectedBlogger !== 'all' && (
                  <div className="mb-3 flex items-center justify-between gap-3 border-l-2 border-blue-500 bg-blue-50/60 px-3 py-2.5">
                    <div className="flex min-w-0 items-center gap-2">
                      <UserRound className="h-4 w-4 shrink-0 text-blue-700" />
                      <div className="min-w-0">
                        <div className="text-[11px] font-semibold text-blue-700">博主笔记目录</div>
                        <div className="truncate text-sm font-semibold text-zinc-950">
                          {selectedBlogger}
                          <span className="ml-2 font-mono text-xs font-normal text-zinc-500">{filteredVideos.length} 篇</span>
                        </div>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => openBloggerDirectory('all')}
                      className="shrink-0 rounded-md px-2.5 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
                    >
                      返回全部
                    </button>
                  </div>
                )}
                <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_170px_auto] lg:items-center">
                  <label className="relative block">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                    <input
                      value={searchQuery}
                      onChange={event => setSearchQuery(event.target.value)}
                      placeholder="搜索标题、博主、标签、摘要或原稿"
                      className="min-h-10 w-full rounded-md border border-zinc-200 bg-white py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none"
                    />
                  </label>
                  <label className="relative block">
                    <ArrowUpDown className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                    <select
                      value={sortMode}
                      onChange={event => setSortMode(event.target.value as SortMode)}
                      className="min-h-10 w-full rounded-md border border-zinc-200 bg-white py-2 pl-9 pr-3 text-sm"
                    >
                      <option value="recommended">推荐优先</option>
                      <option value="latest">最新归档</option>
                      <option value="score">评分最高</option>
                      <option value="duration">视频最长</option>
                      <option value="recentRead">最近阅读</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowMoreFilters(value => !value)}
                    className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-zinc-200 px-3 py-2 text-sm font-medium text-zinc-650 hover:bg-zinc-50"
                  >
                    <Filter className="h-4 w-4" />
                    更多筛选
                    <ChevronDown className={`h-4 w-4 transition ${showMoreFilters ? 'rotate-180' : ''}`} />
                  </button>
                </div>
                {showMoreFilters && (
                  <div className="mt-3 grid grid-cols-1 gap-3 border-t border-zinc-100 pt-3 md:grid-cols-4">
                    <select value={selectedTag} onChange={event => setSelectedTag(event.target.value)} className="min-h-10 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm">
                      <option value="all">全部标签</option>
                      {tags.map(tag => <option key={tag} value={tag}>{tag}</option>)}
                    </select>
                    <select value={filterAction} onChange={event => setFilterAction(event.target.value)} className="min-h-10 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm">
                      <option value="all">全部推荐动作</option>
                      <option value="push">推荐阅读</option>
                      <option value="review">待读内容</option>
                      <option value="research">建议研究</option>
                      <option value="archive">已归档</option>
                      <option value="skip">跳过</option>
                    </select>
                    <select value={timeFilter} onChange={event => setTimeFilter(event.target.value as TimeFilter)} className="min-h-10 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm">
                      <option value="all">全部时间</option>
                      <option value="today">今天</option>
                      <option value="week">近 7 天</option>
                      <option value="month">近 30 天</option>
                    </select>
                    <select value={minRating} onChange={event => setMinRating(Number(event.target.value))} className="min-h-10 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm">
                      <option value="0">全部评分</option>
                      <option value="7">7.0+</option>
                      <option value="8">8.0+</option>
                      <option value="8.5">8.5+</option>
                      <option value="9">9.0+</option>
                    </select>
                  </div>
                )}
                <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                  <span>显示 {filteredVideos.length} 条</span>
                  <span className="rounded bg-zinc-50 px-2 py-1">
                    {selectedBlogger === 'all' ? SMART_VIEWS.find(item => item.id === smartView)?.label : '全部笔记'}
                  </span>
                  <span className="rounded bg-zinc-50 px-2 py-1">{selectedBlogger === 'all' ? '全部来源' : selectedBlogger}</span>
                  {selectedTag !== 'all' && <span className="rounded bg-zinc-50 px-2 py-1">#{selectedTag}</span>}
                  {filterAction !== 'all' && <span className="rounded bg-zinc-50 px-2 py-1">{actionLabel(filterAction)}</span>}
                  {minRating > 0 && <span className="rounded bg-zinc-50 px-2 py-1">{minRating}+ 分</span>}
                  {hasActiveFilters && (
                    <button type="button" onClick={clearFilters} className="rounded px-2 py-1 font-medium text-blue-700 hover:bg-blue-50">
                      清除筛选
                    </button>
                  )}
                </div>
              </div>

              {filteredVideos.length === 0 ? (
                <div className="rounded-lg border border-dashed border-zinc-200 bg-white p-14 text-center text-zinc-500">
                  <Search className="mx-auto mb-3 h-10 w-10 text-zinc-300" />
                  <p className="text-sm font-semibold text-zinc-900">未匹配到可阅读内容</p>
                  <p className="mt-1 text-xs">调整搜索、智能视图或筛选条件后再试。</p>
                </div>
              ) : (
                <div className="overflow-hidden rounded-lg border border-zinc-150 bg-white">
                  {filteredVideos.map(video => (
                    <ContentListItem
                      key={video.id}
                      video={video}
                      selected={video.id === selectedVideoId}
                      onSelect={() => setSelectedVideoId(video.id)}
                      onRead={() => openDetail(video.id)}
                    />
                  ))}
                </div>
              )}
            </section>
          )}
        </main>

        <div className={`${mode === 'library' ? 'block' : 'hidden xl:block'}`}>
          {mode === 'library' ? (
            <PreviewPanel video={selectedVideo} onRead={openDetail} />
          ) : (
            <aside className="rounded-lg border border-zinc-150 bg-white p-5 text-sm leading-6 text-zinc-600 xl:sticky xl:top-4">
              <h2 className="mb-2 text-base font-semibold text-zinc-950">{mode === 'notes' ? '笔记资产' : '简报资产'}</h2>
              <p>{mode === 'notes' ? '这里集中展示已经写入 Obsidian 的 Markdown 内容笔记。' : '这里集中展示历史生成的流媒体简报文件。'}</p>
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
