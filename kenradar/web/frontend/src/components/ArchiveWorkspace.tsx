/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * ArchiveWorkspace - Content archive
 * Two-column layout, title-first cards, inline expansion, chip filters.
 */

import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
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
  Inbox,
  Library,
  Search,
  Sparkles,
  Star,
  Tags,
  UserRound,
  X,
} from 'lucide-react';
import { BriefFile, LibraryStats, NoteFile, VideoContent } from '../types';
import { useContentItems } from '../hooks/useContentItems';
import {
  ScoreBadge,
  ActionTag,
  BloggerLabel,
  RelativeTime,
  DurationDisplay,
  EmptyState,
  FilterChip,
  InlineExpander,
} from './UITokens';

/* ── Types ── */
type SortMode = 'recommended' | 'latest' | 'score' | 'duration' | 'recentRead';
type TimeFilter = 'all' | 'today' | 'week' | 'month';
type SmartView = 'recommended' | 'unread' | 'recent' | 'perfect' | 'long' | 'pushed';
type ArchiveMode = 'library' | 'notes' | 'briefs';

interface ArchiveWorkspaceProps {
  videos: VideoContent[];
  libraryStats?: LibraryStats;
  navigateTo: (page: string, id: string | null) => void;
  pushToFeishuManually: (id: string) => void;
  generateWeeklyBrief: () => Promise<string>;
  notes: NoteFile[];
  briefs: BriefFile[];
  highValueThreshold?: number;
  recommendationThreshold?: number;
}

/* ── Helpers ── */
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

function applySmartView(video: VideoContent, view: SmartView, recommendationThreshold = 8) {
  if (view === 'recommended') return ['push', 'review', 'research'].includes(video.recommend_action) || Number(video.rating || 0) >= recommendationThreshold;
  if (view === 'unread') return video.recommend_action === 'review' || (video.recommend_action !== 'skip' && video.push_status !== 'success');
  if (view === 'recent') return withinTime(video.updated_at || video.created_at, 'week');
  if (view === 'perfect') return Number(video.rating || 0) >= 9.5;
  if (view === 'long') return durationMinutes(video.duration) >= 20;
  if (view === 'pushed') return video.push_status === 'success' || video.recommend_action === 'push';
  return true;
}

const SMART_VIEWS: { id: SmartView; label: string; icon: React.ElementType }[] = [
  { id: 'recommended', label: '推荐阅读', icon: Sparkles },
  { id: 'unread', label: '待读内容', icon: Inbox },
  { id: 'recent', label: '最近归档', icon: Clock3 },
  { id: 'perfect', label: '10分内容', icon: Star },
  { id: 'long', label: '长视频精华', icon: BookOpen },
  { id: 'pushed', label: '已推送飞书', icon: CheckCircle2 },
];

/* ── Sub Components ── */

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="px-2 pt-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-400 dark:text-[var(--text-muted)]">{children}</div>;
}

interface NavButtonProps {
  active: boolean;
  children: React.ReactNode;
  count?: number;
  icon: React.ElementType;
  onClick: () => void;
}

function NavButton({ active, children, count, icon: Icon, onClick }: NavButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex min-h-10 w-full items-center justify-between gap-3 rounded-md px-2.5 py-2 text-left text-sm transition ${
        active ? 'bg-zinc-950 text-white dark:bg-[var(--surface)] dark:text-[var(--text-primary)]' : 'text-zinc-650 dark:text-[var(--text-secondary)] hover:bg-white dark:hover:bg-[var(--surface)] hover:text-zinc-950 dark:hover:text-[var(--text-primary)]'
      }`}
    >
      <span className="flex min-w-0 items-center gap-2">
        <Icon className={`h-4 w-4 shrink-0 ${active ? 'text-white dark:text-[var(--text-primary)]' : 'text-zinc-400 dark:text-[var(--text-muted)]'}`} />
        <span className="truncate">{children}</span>
      </span>
      {typeof count === 'number' && (
        <span className={`font-mono text-[11px] ${active ? 'text-zinc-200 dark:text-[var(--text-secondary)]' : 'text-zinc-400 dark:text-[var(--text-muted)]'}`}>{count}</span>
      )}
    </button>
  );
}

/* ── ContentListItem (redesigned: title-first, inline expand) ── */
const PAGE_SIZE = 30;

interface ContentListItemProps {
  video: VideoContent;
  selected: boolean;
  expanded: boolean;
  onSelect: () => void;
  onRead: () => void;
  onToggleExpand: () => void;
}

function ContentListItem({ video, selected, expanded, onSelect, onRead, onToggleExpand }: ContentListItemProps) {
  const conclusion = conclusionFor(video);
  const summary = summaryFor(video, 180);

  const handleClick = () => {
    onSelect();
    if (!expanded) {
      onToggleExpand();
    }
  };

  return (
    <article
      onClick={handleClick}
      className={`group cursor-pointer border-b border-zinc-100 dark:border-[var(--surface-border)] px-4 py-4 transition md:px-5 ${
        selected || expanded ? 'bg-blue-50/50 dark:bg-[var(--info-bg)] shadow-[inset_3px_0_0_rgb(37,99,235)]' : 'bg-white dark:bg-[var(--surface)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]'
      }`}
    >
      {/* Row 1: Title + Score + Action (side by side) */}
      <div className="mb-1 flex items-start justify-between gap-3">
        <button
          type="button"
          onClick={event => {
            event.stopPropagation();
            onRead();
          }}
          className="min-w-0 flex-1 text-left text-[15px] font-semibold leading-6 text-zinc-950 dark:text-[var(--text-primary)] hover:text-blue-700 dark:hover:text-[var(--info)]"
        >
          {video.title || '无标题'}
        </button>
        <div className="flex shrink-0 items-center gap-2">
          <ScoreBadge rating={video.rating} size="sm" />
          {video.recommend_action && <ActionTag action={video.recommend_action} />}
        </div>
      </div>

      {/* Row 2: Conclusion or Summary (one line, truncated) */}
      <p className="mb-1.5 text-sm leading-6 text-zinc-650 dark:text-[var(--text-secondary)] line-clamp-1">
        {conclusion || summary || '暂无摘要'}
      </p>

      {/* Row 3: Blogger · Duration · Relative Time · Tags */}
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
        <BloggerLabel name={video.blogger} />
        {video.duration && <DurationDisplay duration={video.duration} />}
        <RelativeTime date={video.published_at || video.created_at} />
        {(video.tags || []).slice(0, 6).map(tag => (
          <span key={tag} className="rounded bg-zinc-100 dark:bg-[var(--surface-border)] px-1.5 py-0.5 text-[11px] text-zinc-600 dark:text-[var(--text-secondary)]">#{tag}</span>
        ))}
      </div>

      {/* Expanded content: recommendation reason + full summary + metadata + actions */}
      <InlineExpander expanded={expanded}>
        <div className="space-y-3">
          {video.recommendation_reason && (
            <div>
              <div className="mb-0.5 text-xs font-semibold text-blue-700 dark:text-[var(--info)]">推荐理由</div>
              <p className="text-sm leading-6 text-zinc-700 dark:text-[var(--text-primary)]">{video.recommendation_reason}</p>
            </div>
          )}
          <div>
            <div className="mb-0.5 text-xs font-semibold text-zinc-500 dark:text-[var(--text-muted)]">核心摘要</div>
            <p className="text-sm leading-6 text-zinc-700 dark:text-[var(--text-primary)]">{summaryFor(video, 360) || '暂无摘要。'}</p>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
            <span>评分 {video.rating > 0 ? video.rating.toFixed(1) : '未评分'}</span>
            {video.duration && <span>时长 {video.duration}</span>}
            <span>发表 <RelativeTime date={video.published_at || video.created_at} /></span>
            {video.collected_at && <span>收录 <RelativeTime date={video.collected_at} /></span>}
            {video.recommend_action && <span>动作 {video.recommend_action}</span>}
          </div>
          {(video.tags || []).length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {(video.tags || []).map(tag => (
                <span key={tag} className="rounded bg-zinc-100 dark:bg-[var(--surface-border)] px-2 py-0.5 text-xs text-zinc-600 dark:text-[var(--text-secondary)]">#{tag}</span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              onClick={event => { event.stopPropagation(); onRead(); }}
              className="inline-flex items-center gap-1.5 rounded-md bg-zinc-950 dark:bg-[var(--surface)] px-3 py-1.5 text-xs font-medium text-white dark:text-[var(--text-primary)] hover:bg-zinc-800 dark:hover:bg-[var(--surface-border)]"
            >
              <BookOpen className="h-3.5 w-3.5" />
              阅读完整笔记
            </button>
            {video.original_url && (
              <a
                href={video.original_url}
                target="_blank"
                rel="noreferrer"
                referrerPolicy="no-referrer"
                onClick={event => event.stopPropagation()}
                className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 dark:border-[var(--surface-border)] px-3 py-1.5 text-xs font-medium text-zinc-700 dark:text-[var(--text-primary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                原视频链接
              </a>
            )}
          </div>
        </div>
      </InlineExpander>
    </article>
  );
}

/* ── Main component ── */
export default function ArchiveWorkspace({
  videos: bootstrapVideos,
  libraryStats,
  navigateTo,
  notes: bootstrapNotes,
  briefs: bootstrapBriefs,
  highValueThreshold: configuredHighValueThreshold = 7,
  recommendationThreshold = 8,
}: ArchiveWorkspaceProps) {
  const contentFeed = useContentItems({ sort: 'priority_desc' });
  const videos = contentFeed.loading ? bootstrapVideos : contentFeed.items;
  const highValueThreshold = contentFeed.highValueThreshold || configuredHighValueThreshold;
  const [notes, setNotes] = useState<NoteFile[]>(bootstrapNotes);
  const [briefs, setBriefs] = useState<BriefFile[]>(bootstrapBriefs);
  const archiveMode: ArchiveMode = window.location.pathname.includes('/archive/notes')
    ? 'notes' : window.location.pathname.includes('/archive/briefs') ? 'briefs' : 'library';
  const initialBlogger = archiveMode === 'library'
    ? new URLSearchParams(window.location.search).get('blogger')?.trim() || 'all' : 'all';

  const [mode, setMode] = useState<ArchiveMode>(archiveMode);
  const [smartView, setSmartView] = useState<SmartView>('recommended');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBlogger, setSelectedBlogger] = useState(initialBlogger);
  const [selectedTag, setSelectedTag] = useState('all');
  const [filterAction, setFilterAction] = useState('all');
  const [minRating, setMinRating] = useState<number>(0);
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('all');
  const [sortMode, setSortMode] = useState<SortMode>(initialBlogger === 'all' ? 'recommended' : 'latest');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [expandedVideoId, setExpandedVideoId] = useState<string | null>(null);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const [focusIndex, setFocusIndex] = useState(-1);

  const searchRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMode(archiveMode), [archiveMode]);

  useEffect(() => {
    let cancelled = false;
    const loadFiles = async (kind: 'notes' | 'briefs') => {
      const response = await fetch(`/api/archive/files?kind=${kind}`, { credentials: 'same-origin' });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) throw new Error(payload.message || '归档文件加载失败');
      return Array.isArray(payload.items) ? payload.items : [];
    };
    Promise.all([loadFiles('notes'), loadFiles('briefs')])
      .then(([nextNotes, nextBriefs]) => {
        if (!cancelled) {
          setNotes(nextNotes);
          setBriefs(nextBriefs);
        }
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const readableVideos = useMemo(() => videos.filter(isReadable), [videos]);

  const bloggers = useMemo(() => {
    const values = new Set<string>(readableVideos.map(video => String(video.blogger || '')).filter(Boolean));
    return Array.from(values).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'));
  }, [readableVideos]);

  const sourceCounts = useMemo(() => {
    const counter = new Map<string, number>();
    readableVideos.forEach(video => counter.set(video.blogger || '未知来源', (counter.get(video.blogger || '未知来源') || 0) + 1));
    return Array.from(counter.entries()).sort((a, b) => b[1] - a[1]);
  }, [readableVideos]);

  const tags = useMemo(() => {
    const allTags = readableVideos.flatMap(video => video.tags || []).map(tag => String(tag || '')).filter(Boolean);
    return Array.from(new Set<string>(allTags)).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN')).slice(0, 120);
  }, [readableVideos]);

  const stats = useMemo(() => {
    const recommended = readableVideos.filter(video => applySmartView(video, 'recommended', recommendationThreshold)).length;
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
  }, [readableVideos, briefs.length, libraryStats, videos.length, recommendationThreshold]);

  const smartCounts = useMemo(() => {
    return SMART_VIEWS.reduce<Record<SmartView, number>>((acc, view) => {
      acc[view.id] = readableVideos.filter(video => applySmartView(video, view.id, recommendationThreshold)).length;
      return acc;
    }, {} as Record<SmartView, number>);
  }, [readableVideos, recommendationThreshold]);

  const filteredVideos = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return readableVideos
      .filter(video => mode === 'library')
      .filter(video => selectedBlogger !== 'all' || applySmartView(video, smartView, recommendationThreshold))
      .filter(video => selectedBlogger === 'all' || video.blogger === selectedBlogger)
      .filter(video => selectedTag === 'all' || (video.tags || []).includes(selectedTag))
      .filter(video => filterAction === 'all' || video.recommend_action === filterAction)
      .filter(video => Number(video.rating || 0) >= minRating)
      .filter(video => withinTime(video.updated_at || video.created_at, timeFilter))
      .filter(video => {
        if (!q) return true;
        return [video.id, video.title, video.blogger, video.brief_summary || '', video.one_sentence_conclusion || '',
          video.recommendation_reason || '', video.summary_markdown || '', video.whisper_text || '', ...(video.tags || [])]
          .join(' ').toLowerCase().includes(q);
      })
      .sort((a, b) => sortArchive(a, b, sortMode));
  }, [readableVideos, mode, smartView, selectedBlogger, selectedTag, filterAction, minRating, timeFilter, searchQuery, sortMode]);

  const visibleVideos = useMemo(() => filteredVideos.slice(0, visibleCount), [filteredVideos, visibleCount]);

  const hasActiveFilters = selectedBlogger !== 'all' || selectedTag !== 'all' || filterAction !== 'all' || minRating > 0 || timeFilter !== 'all';

  const clearFilters = () => {
    setSelectedBlogger('all');
    setSelectedTag('all');
    setFilterAction('all');
    setMinRating(0);
    setTimeFilter('all');
    setExpandedVideoId(null);
    window.history.pushState(null, '', '/archive');
  };

  const openDetail = (id: string) => navigateTo('detail', id);

  const switchMode = (nextMode: ArchiveMode) => {
    setMode(nextMode);
    setExpandedVideoId(null);
    window.history.pushState(null, '', nextMode === 'notes' ? '/archive/notes' : nextMode === 'briefs' ? '/archive/briefs' : '/archive');
  };

  const openBloggerDirectory = (blogger: string) => {
    if (blogger === 'all') { clearFilters(); return; }
    setMode('library');
    setSelectedBlogger(blogger);
    setSelectedTag('all');
    setFilterAction('all');
    setMinRating(0);
    setTimeFilter('all');
    setSearchQuery('');
    setSortMode('latest');
    setExpandedVideoId(null);
    window.history.pushState(null, '', `/archive?blogger=${encodeURIComponent(blogger)}`);
  };

  const toggleExpand = (id: string) => {
    setExpandedVideoId(prev => prev === id ? null : id);
  };

  /* ── Keyboard navigation ── */
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    if (mode !== 'library') return;
    const target = event.target as HTMLElement;
    const isInSearch = target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT';

    // Ctrl/Cmd key pressed -> skip
    if (event.ctrlKey || event.metaKey) return;

    // / to focus search
    if (event.key === '/' && !isInSearch) {
      event.preventDefault();
      searchRef.current?.focus();
      return;
    }

    // j/k for navigation
    if (event.key === 'j' && !isInSearch) {
      event.preventDefault();
      setFocusIndex(prev => {
        const next = Math.min(prev + 1, visibleVideos.length - 1);
        if (next >= 0 && next < visibleVideos.length) {
          setSelectedVideoId(visibleVideos[next].id);
        }
        return next;
      });
      return;
    }
    if (event.key === 'k' && !isInSearch) {
      event.preventDefault();
      setFocusIndex(prev => {
        const next = Math.max(prev - 1, 0);
        if (next >= 0 && next < visibleVideos.length) {
          setSelectedVideoId(visibleVideos[next].id);
        }
        return next;
      });
      return;
    }

    // Enter to open detail
    if (event.key === 'Enter' && focusIndex >= 0 && focusIndex < visibleVideos.length) {
      event.preventDefault();
      openDetail(visibleVideos[focusIndex].id);
      return;
    }

    // Escape to collapse expanded
    if (event.key === 'Escape') {
      if (expandedVideoId) {
        event.preventDefault();
        setExpandedVideoId(null);
      }
    }
  }, [mode, visibleVideos, focusIndex, expandedVideoId]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // Sync focusIndex when filteredVideos changes
  useEffect(() => {
    setFocusIndex(-1);
    setVisibleCount(PAGE_SIZE);
  }, [searchQuery, smartView, selectedBlogger, selectedTag, filterAction, minRating, timeFilter, sortMode]);

  // Reset expanded when mode changes
  useEffect(() => {
    if (mode !== 'library') setExpandedVideoId(null);
  }, [mode]);

  return (
    <div className="animate-fade-in space-y-5 font-sans">
      <header className="border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4">
        <h1 className="text-3xl font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">内容归档</h1>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-zinc-500 dark:text-[var(--text-secondary)]">
          阅读已归档内容，按来源、标签、评分和推荐动作定位已经沉淀的笔记。
        </p>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
          <span>内容笔记 <strong className="font-mono text-zinc-900 dark:text-[var(--text-primary)]">{stats.actualNotes}</strong> 篇</span>
          <span className="text-zinc-300 dark:text-[var(--surface-border)]">·</span>
          <span>当前加载 <strong className="font-mono text-zinc-900 dark:text-[var(--text-primary)]">{stats.readable}</strong> 篇</span>
          <span className="text-zinc-300 dark:text-[var(--surface-border)]">·</span>
          <span>推荐阅读 <strong className="font-mono text-zinc-900 dark:text-[var(--text-primary)]">{stats.recommended}</strong> 篇</span>
          <span className="text-zinc-300 dark:text-[var(--surface-border)]">·</span>
          <span>待读 <strong className="font-mono text-zinc-900 dark:text-[var(--text-primary)]">{stats.unread}</strong> 篇</span>
          <span className="text-zinc-300 dark:text-[var(--surface-border)]">·</span>
          <span>简报 <strong className="font-mono text-zinc-900 dark:text-[var(--text-primary)]">{stats.briefs}</strong> 份</span>
          {stats.loadedItems < stats.totalItems && (
            <>
              <span className="text-zinc-300 dark:text-[var(--surface-border)]">·</span>
              <span>共收录 <strong className="font-mono text-zinc-900 dark:text-[var(--text-primary)]">{stats.totalItems}</strong> 条，当前展示上限 {stats.displayLimit}</span>
            </>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[230px_minmax(0,1fr)]">
        {/* ── Left navigation ── */}
        <aside className="rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-zinc-50/70 dark:bg-[var(--surface-muted)] p-2 xl:sticky xl:top-4 xl:self-start">
          <nav className="space-y-4">

            {/* Smart Views */}
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
                    setSmartView(view.id);
                  }}
                >
                  {view.label}
                </NavButton>
              ))}
            </div>

            {/* Blogger Directory */}
            <div className="space-y-2">
              <SectionTitle>博主目录</SectionTitle>
              <label className="relative block px-1">
                <UserRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400 dark:text-[var(--text-muted)]" />
                <select
                  aria-label="选择博主查看全部笔记"
                  value={selectedBlogger}
                  onChange={event => openBloggerDirectory(event.target.value)}
                  className="min-h-10 w-full rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] py-2 pl-8 pr-7 text-sm text-zinc-700 dark:text-[var(--text-primary)] focus:border-blue-500 focus:outline-none"
                >
                  <option value="all">选择博主</option>
                  {sourceCounts.map(([blogger, count]) => (
                    <option key={blogger} value={blogger}>{blogger}（{count}）</option>
                  ))}
                </select>
              </label>
              <p className="px-2 text-[11px] leading-5 text-zinc-400 dark:text-[var(--text-muted)]">选择后查看该博主的全部已归档笔记。</p>
            </div>

            {/* Assets */}
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

        {/* ── Main content area ── */}
        <main className="min-w-0">
          {mode === 'notes' && (
            <section className="overflow-hidden rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
              <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-5 py-4">
                <h2 className="text-lg font-semibold text-zinc-950 dark:text-[var(--text-primary)]">Obsidian 笔记</h2>
                <p className="mt-1 text-sm text-zinc-500 dark:text-[var(--text-secondary)]">查看本地 Markdown 文件索引，阅读入口会优先跳转到统一内容详情。</p>
              </div>
              {notes.length === 0 ? (
                <EmptyState icon={FileText} title="暂无 Markdown 笔记文件" description="研究任务完成后，笔记会自动写入 Obsidian 目录。" />
              ) : (
                <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {notes.map(note => (
                    <a key={note.path} href="/archive" className="block px-5 py-4 transition hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div className="min-w-0">
                          <div className="line-clamp-1 text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)]">{note.title || note.name}</div>
                          <div className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{note.platform} / {note.blogger}</div>
                        </div>
                        <div className="shrink-0 text-xs font-mono text-zinc-400 dark:text-[var(--text-muted)]">{note.updated_at} · {note.size_kb} KB</div>
                      </div>
                    </a>
                  ))}
                </div>
              )}
            </section>
          )}

          {mode === 'briefs' && (
            <section className="overflow-hidden rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
              <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-5 py-4">
                <h2 className="text-lg font-semibold text-zinc-950 dark:text-[var(--text-primary)]">简报文件</h2>
                <p className="mt-1 text-sm text-zinc-500 dark:text-[var(--text-secondary)]">查看历史流媒体简报和研究简报。</p>
              </div>
              {briefs.length === 0 ? (
                <EmptyState icon={CalendarDays} title="暂无历史简报" description="定期生成的简报文件会出现在这里。" />
              ) : (
                <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {briefs.map(brief => (
                    <a key={brief.path} href="/archive" className="block px-5 py-4 transition hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div className="min-w-0">
                          <div className="line-clamp-1 text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)]">{brief.title || brief.name}</div>
                          <div className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">{brief.item_count} 条内容 · {brief.status}</div>
                        </div>
                        <div className="shrink-0 text-xs font-mono text-zinc-400 dark:text-[var(--text-muted)]">{brief.created_at}</div>
                      </div>
                    </a>
                  ))}
                </div>
              )}
            </section>
          )}

          {mode === 'library' && (
            <section className="space-y-3">
              {/* ── Search & Filter bar ── */}
              <div className="rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
                {/* Blogger banner */}
                {selectedBlogger !== 'all' && (
                  <div className="flex items-center justify-between gap-3 border-b border-zinc-100 dark:border-[var(--surface-border)] bg-blue-50/60 dark:bg-[var(--info-bg)] px-4 py-2.5">
                    <div className="flex min-w-0 items-center gap-2">
                      <UserRound className="h-4 w-4 shrink-0 text-blue-700 dark:text-[var(--info)]" />
                      <div className="min-w-0">
                        <span className="text-[11px] font-semibold text-blue-700 dark:text-[var(--info)]">博主笔记目录</span>
                        <span className="ml-2 truncate text-sm font-semibold text-zinc-950 dark:text-[var(--text-primary)]">
                          {selectedBlogger}
                          <span className="ml-2 font-mono text-xs font-normal text-zinc-500 dark:text-[var(--text-secondary)]">{filteredVideos.length} 篇</span>
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => openBloggerDirectory('all')}
                      className="shrink-0 rounded-md px-2.5 py-1.5 text-xs font-medium text-blue-700 dark:text-[var(--info)] hover:bg-blue-100 dark:hover:bg-[var(--info-border)]"
                    >
                      返回全部
                    </button>
                  </div>
                )}

                {/* Search row */}
                <div className="flex flex-col gap-3 p-3 md:flex-row md:items-center">
                  <label className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400 dark:text-[var(--text-muted)]" />
                    <input
                      ref={searchRef}
                      value={searchQuery}
                      onChange={event => setSearchQuery(event.target.value)}
                      placeholder="搜索标题、博主、标签、摘要或原稿（/ 快速聚焦）"
                      className="min-h-10 w-full rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] py-2 pl-9 pr-3 text-sm focus:border-blue-500 focus:outline-none"
                    />
                  </label>
                  <label className="relative md:w-44">
                    <ArrowUpDown className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400 dark:text-[var(--text-muted)]" />
                    <select
                      value={sortMode}
                      onChange={event => setSortMode(event.target.value as SortMode)}
                      className="min-h-10 w-full rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] py-2 pl-9 pr-3 text-sm"
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
                    onClick={() => setShowAdvancedFilters(value => !value)}
                    className="inline-flex min-h-10 items-center justify-center gap-2 rounded-md border border-zinc-200 dark:border-[var(--surface-border)] px-3 py-2 text-sm font-medium text-zinc-650 dark:text-[var(--text-secondary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]"
                  >
                    <Filter className="h-4 w-4" />
                    高级筛选
                    <ChevronDown className={`h-4 w-4 transition ${showAdvancedFilters ? 'rotate-180' : ''}`} />
                  </button>
                </div>

                {/* Quick filter chips */}
                <div className="flex flex-wrap items-center gap-2 px-3 pb-3">
                  <FilterChip
                    active={timeFilter === 'all' && minRating === 0}
                    onClick={() => { setTimeFilter('all'); setMinRating(0); }}
                  >
                    全部
                  </FilterChip>
                  <FilterChip active={timeFilter === 'today'} onClick={() => setTimeFilter(timeFilter === 'today' ? 'all' : 'today')}>
                    今天
                  </FilterChip>
                  <FilterChip active={timeFilter === 'week'} onClick={() => setTimeFilter(timeFilter === 'week' ? 'all' : 'week')}>
                    近 7 天
                  </FilterChip>
                  <FilterChip active={minRating >= highValueThreshold} onClick={() => setMinRating(minRating >= highValueThreshold ? 0 : highValueThreshold)}>
                    高价值 {highValueThreshold.toFixed(1)}+
                  </FilterChip>
                  <FilterChip active={minRating >= 9} onClick={() => setMinRating(minRating >= 9 ? 0 : 9)}>
                    评分 9.0+
                  </FilterChip>
                  <FilterChip active={selectedBlogger !== 'all'} onClick={() => openBloggerDirectory('all')}>
                    {selectedBlogger !== 'all' ? `博主: ${selectedBlogger}` : '不限博主'}
                    {selectedBlogger !== 'all' && <X className="ml-1 h-3 w-3" />}
                  </FilterChip>
                </div>

                {/* Advanced filters */}
                {showAdvancedFilters && (
                  <div className="grid grid-cols-1 gap-3 border-t border-zinc-100 dark:border-[var(--surface-border)] px-3 pb-3 pt-3 md:grid-cols-3">
                    <select value={selectedTag} onChange={event => setSelectedTag(event.target.value)} className="min-h-10 rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
                      <option value="all">全部标签</option>
                      {tags.map(tag => <option key={tag} value={tag}>{tag}</option>)}
                    </select>
                    <select value={filterAction} onChange={event => setFilterAction(event.target.value)} className="min-h-10 rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
                      <option value="all">全部推荐动作</option>
                      <option value="push">推荐阅读</option>
                      <option value="review">待读内容</option>
                      <option value="research">建议研究</option>
                      <option value="archive">已归档</option>
                      <option value="skip">跳过</option>
                    </select>
                    <select value={timeFilter} onChange={event => setTimeFilter(event.target.value as TimeFilter)} className="min-h-10 rounded-md border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-3 py-2 text-sm">
                      <option value="all">全部时间</option>
                      <option value="today">今天</option>
                      <option value="week">近 7 天</option>
                      <option value="month">近 30 天</option>
                    </select>
                  </div>
                )}

                {/* Active filter summary */}
                <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 dark:border-[var(--surface-border)] px-3 py-2 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                  <span>匹配 <strong className="text-zinc-900 dark:text-[var(--text-primary)]">{filteredVideos.length}</strong> 条</span>
                  <span className="rounded bg-zinc-50 dark:bg-[var(--surface-muted)] px-2 py-1">
                    {selectedBlogger === 'all' ? SMART_VIEWS.find(item => item.id === smartView)?.label : '全部笔记'}
                  </span>
                  {selectedTag !== 'all' && <span className="rounded bg-zinc-50 dark:bg-[var(--surface-muted)] px-2 py-1">#{selectedTag}</span>}
                  {filterAction !== 'all' && <span className="rounded bg-zinc-50 dark:bg-[var(--surface-muted)] px-2 py-1">{filterAction}</span>}
                  {minRating > 0 && <span className="rounded bg-zinc-50 dark:bg-[var(--surface-muted)] px-2 py-1">{minRating}+ 分</span>}
                  {hasActiveFilters && (
                    <button type="button" onClick={clearFilters} className="rounded px-2 py-1 font-medium text-blue-700 dark:text-[var(--info)] hover:bg-blue-50 dark:hover:bg-[var(--info-bg)]">
                      清除筛选
                    </button>
                  )}
                </div>
              </div>

              {/* ── Content list ── */}
              {filteredVideos.length === 0 ? (
                <EmptyState
                  icon={Search}
                  title="未匹配到可阅读内容"
                  description={hasActiveFilters ? "尝试清除筛选条件或切换到其他智能视图。" : "系统正在后台检测内容，请稍后再试或切换到'全部来源'视图。"}
                  action={hasActiveFilters ? { label: '清除所有筛选', onClick: clearFilters } : undefined}
                />
              ) : (
                <div className="overflow-hidden rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
                  <div ref={listRef} className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                    {visibleVideos.map((video, index) => (
                      <ContentListItem
                        key={video.id}
                        video={video}
                        selected={video.id === selectedVideoId}
                        expanded={video.id === expandedVideoId}
                        onSelect={() => setSelectedVideoId(video.id)}
                        onRead={() => openDetail(video.id)}
                        onToggleExpand={() => toggleExpand(video.id)}
                      />
                    ))}
                  </div>

                  {/* Pagination */}
                  {filteredVideos.length > visibleCount && (
                    <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] px-5 py-3 text-center">
                      <button
                        type="button"
                        onClick={() => setVisibleCount(prev => Math.min(prev + PAGE_SIZE, filteredVideos.length))}
                        className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 dark:border-[var(--surface-border)] px-4 py-2 text-xs font-medium text-zinc-700 dark:text-[var(--text-primary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]"
                      >
                        显示更多（已加载 {visibleCount}/{filteredVideos.length} 条）
                      </button>
                    </div>
                  )}
                  {filteredVideos.length <= visibleCount && filteredVideos.length > 0 && contentFeed.hasMore && (
                    <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] px-5 py-3 text-center">
                      <button
                        type="button"
                        onClick={contentFeed.loadMore}
                        className="inline-flex items-center gap-1.5 rounded-md border border-zinc-200 dark:border-[var(--surface-border)] px-4 py-2 text-xs font-medium text-zinc-700 dark:text-[var(--text-primary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]"
                      >
                        从资料库继续加载
                      </button>
                    </div>
                  )}
                  {filteredVideos.length <= visibleCount && filteredVideos.length > 0 && !contentFeed.hasMore && (
                    <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] px-5 py-2 text-center text-[11px] text-zinc-400 dark:text-[var(--text-muted)]">
                      已全部加载 · 共 {filteredVideos.length} 条
                    </div>
                  )}
                </div>
              )}
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
