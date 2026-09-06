/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useMemo, useState } from 'react';
import { 
  Database, 
  ChevronDown,
  ChevronUp,
  Cpu,
  FileText,
  Loader2,
  Pause,
  Play,
  Search,
  RotateCcw,
  XCircle
} from 'lucide-react';
import { BriefFile, ResearchTask, VideoContent } from '../types';
import {
  TaskStageCounts,
  taskStatusClass,
  taskStatusLabel,
} from './TaskProgress';

type ResearchJobPayload = {
  job?: Record<string, any> | null;
  items?: Record<string, any>[];
  pipeline?: Record<string, any>;
};

interface ResearchWorkspaceProps {
  videos: VideoContent[];
  tasks: ResearchTask[];
  runResearchTask: (type: 'single' | 'blogger', targetValue: string, forceRetry: boolean, limit?: number) => Promise<void>;
  controlResearchTask: (taskId: string, action: 'pause' | 'resume' | 'cancel' | 'restart') => void;
  loadResearchJob: (taskId: string) => Promise<ResearchJobPayload>;
  retryResearchFailed: (taskId: string) => void;
  briefs: BriefFile[];
}

export default function ResearchWorkspace({
  videos,
  tasks,
  runResearchTask,
  controlResearchTask,
  loadResearchJob,
  retryResearchFailed,
  briefs
}: ResearchWorkspaceProps) {
  const [activeCenterTab, setActiveCenterTab] = useState<'tasks' | 'reports' | 'notes'>('tasks');
  const [taskFilter, setTaskFilter] = useState<'active' | 'queued' | 'failed' | 'completed' | 'all'>('active');
  // Tabs: single vs blogger inputs
  const [researchType, setResearchType] = useState<'single' | 'blogger'>('single');

  // Input states
  const [singleUrl, setSingleUrl] = useState('');
  const [bloggerHandle, setBloggerHandle] = useState('');
  const [scrapeLimit, setScrapeLimit] = useState(20);
  const [forceRetry, setForceRetry] = useState(false);

  // Accordion list open states
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [jobDetails, setJobDetails] = useState<Record<string, ResearchJobPayload>>({});
  const [loadingJobId, setLoadingJobId] = useState<string | null>(null);
  const [backfillAction, setBackfillAction] = useState('');
  const [selectedBlogger, setSelectedBlogger] = useState('all');
  const [noteSearch, setNoteSearch] = useState('');
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [noteDetails, setNoteDetails] = useState<Record<string, VideoContent>>({});
  const [loadingNoteId, setLoadingNoteId] = useState<string | null>(null);
  const [noteError, setNoteError] = useState('');

  // Aggregated quantities
  const totalCount = tasks.length;
  const processingCount = tasks.filter(t => t.status === 'processing').length;
  const queuedCount = tasks.filter(t => t.status === 'queued').length;
  const pausedCount = tasks.filter(t => t.status === 'paused').length;
  const completedCount = tasks.filter(t => t.status === 'completed').length;
  const failedCount = tasks.filter(t => t.status === 'failed').length;
  const visibleTasks = [...tasks]
    .filter(task => {
      if (taskFilter === 'active') return task.status === 'processing' || task.status === 'paused';
      if (taskFilter === 'queued') return task.status === 'queued';
      if (taskFilter === 'failed') return task.status === 'failed';
      if (taskFilter === 'completed') return task.status === 'completed';
      return true;
    })
    .sort((a, b) => {
      const priority: Record<ResearchTask['status'], number> = {
        processing: 0,
        paused: 1,
        queued: 2,
        failed: 3,
        completed: 4,
      };
      return priority[a.status] - priority[b.status] || b.created_at.localeCompare(a.created_at);
    });

  const completedNotes = useMemo(() => (
    videos
      .filter(video => video.status === 'completed' && Boolean(video.summary_path || video.brief_summary || video.one_sentence_conclusion))
      .sort((a, b) => String(b.published_at || b.created_at || '').localeCompare(String(a.published_at || a.created_at || '')))
  ), [videos]);
  const bloggerOptions = useMemo(() => (
    Array.from(new Set(completedNotes.map(video => video.blogger || '未知来源'))).sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
  ), [completedNotes]);
  const filteredNotes = useMemo(() => {
    const query = noteSearch.trim().toLowerCase();
    return completedNotes.filter(video => {
      const matchBlogger = selectedBlogger === 'all' || (video.blogger || '未知来源') === selectedBlogger;
      const haystack = `${video.title || ''} ${video.blogger || ''} ${(video.tags || []).join(' ')}`.toLowerCase();
      return matchBlogger && (!query || haystack.includes(query));
    });
  }, [completedNotes, noteSearch, selectedBlogger]);
  const selectedNote = selectedNoteId ? (noteDetails[selectedNoteId] || filteredNotes.find(video => video.id === selectedNoteId) || null) : (filteredNotes[0] || null);

  useEffect(() => {
    if (selectedNoteId && filteredNotes.some(video => video.id === selectedNoteId)) return;
    setSelectedNoteId(filteredNotes[0]?.id || null);
  }, [filteredNotes, selectedNoteId]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (researchType === 'single') {
      if (!singleUrl.trim()) return;
      runResearchTask('single', singleUrl, forceRetry);
      setSingleUrl('');
    } else {
      if (!bloggerHandle.trim()) return;
      const targetStr = `${bloggerHandle} (限制前 ${scrapeLimit} 条视频)`;
      runResearchTask('blogger', targetStr, forceRetry, scrapeLimit);
      setBloggerHandle('');
    }
  };

  const showJobDetail = async (taskId: string, forceRefresh = false) => {
    setExpandedTaskId(taskId);
    if (!forceRefresh && jobDetails[taskId]) return;
    setLoadingJobId(taskId);
    try {
      const detail = await loadResearchJob(taskId);
      setJobDetails(prev => ({ ...prev, [taskId]: detail }));
    } finally {
      setLoadingJobId(null);
    }
  };

  const toggleTask = (task: ResearchTask) => {
    if (expandedTaskId === task.id) {
      setExpandedTaskId(null);
      return;
    }
    void showJobDetail(task.id);
  };

  const reviewBackfillItem = async (jobId: string, externalContentId: string, approve: boolean) => {
    setBackfillAction(`${jobId}:${externalContentId}`);
    try {
      const response = await fetch('/api/research/job/item-review', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: Number(jobId), external_content_id: externalContentId, approve }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await showJobDetail(jobId, true);
    } finally {
      setBackfillAction('');
    }
  };

  const executeBackfill = async (jobId: string) => {
    setBackfillAction(`${jobId}:execute`);
    try {
      const response = await fetch('/api/research/job/confirm', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: Number(jobId) }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      await showJobDetail(jobId, true);
    } finally {
      setBackfillAction('');
    }
  };

  const loadNoteDetail = async (videoId: string) => {
    if (!videoId) return;
    setSelectedNoteId(videoId);
    if (noteDetails[videoId]?.summary_markdown) return;
    setLoadingNoteId(videoId);
    setNoteError('');
    try {
      const note = videos.find(item => item.id === videoId);
      const params = new URLSearchParams({ platform: note?.platform || 'douyin', external_id: videoId });
      const response = await fetch(`/api/content?${params.toString()}`, { credentials: 'same-origin' });
      const payload = await response.json();
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message || `读取笔记失败: ${response.status}`);
      }
      setNoteDetails(prev => ({ ...prev, [videoId]: payload.item as VideoContent }));
    } catch (error) {
      setNoteError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoadingNoteId(null);
    }
  };

  useEffect(() => {
    if (!expandedTaskId) return;
    const activeTask = tasks.find(task => task.id === expandedTaskId);
    if (!activeTask || !['processing', 'queued', 'paused'].includes(activeTask.status)) return;
    const timer = window.setInterval(() => {
      void showJobDetail(expandedTaskId, true);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [expandedTaskId, tasks]);

  return (
    <div className="space-y-8 animate-fade-in">
      
      {/* Title block */}
      <div className="border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">博主研究</h1>
          <p className="text-zinc-500 dark:text-[var(--text-secondary)] font-sans text-sm mt-1">
            单视频快速分析、博主历史作品归档，以及研究完成后的批次报告。
          </p>
        </div>
        
      </div>

      <div className="flex border-b border-zinc-200 dark:border-[var(--surface-border)] gap-6">
        {[
          { id: 'tasks', label: '研究任务', icon: Cpu },
          { id: 'reports', label: '研究报告', icon: FileText },
          { id: 'notes', label: 'AI笔记原文', icon: Database },
        ].map(tab => {
          const Icon = tab.icon;
          const active = activeCenterTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveCenterTab(tab.id as typeof activeCenterTab)}
              className={`pb-3 inline-flex items-center gap-1.5 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
                active ? 'text-zinc-950 dark:text-[var(--text-primary)]' : 'text-zinc-400 hover:text-zinc-700 dark:text-[var(--text-muted)] dark:hover:text-[var(--text-secondary)]'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
              {active && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--text-primary)] rounded" />}
            </button>
          );
        })}
      </div>

      {activeCenterTab === 'reports' && (
        <section className="rounded-xl border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] shadow-2xs overflow-hidden">
          <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-5 py-4">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">研究报告</h2>
            <p className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">只读展示已生成的研究简报和归档报告，不额外伪造数据。</p>
          </div>
          {briefs.length === 0 ? (
            <div className="p-16 text-center text-zinc-400 dark:text-[var(--text-muted)] font-sans">
              <FileText className="w-10 h-10 mx-auto text-zinc-300 dark:text-[var(--text-secondary)] stroke-1 mb-3" />
              <p className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">暂无研究报告</p>
              <p className="text-xs mt-1">完成研究任务后，相关简报会出现在这里。</p>
            </div>
          ) : (
            <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
              {briefs.map(brief => (
                <a key={brief.path} href="/archive" className="block px-5 py-4 hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] transition">
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

      {activeCenterTab === 'notes' && (
        <section className="grid grid-cols-1 gap-5 xl:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="space-y-4 rounded-xl border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-4 shadow-2xs xl:sticky xl:top-4 xl:self-start">
            <div>
              <h2 className="text-sm font-semibold text-zinc-900 dark:text-[var(--text-primary)]">全部来源笔记</h2>
              <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-[var(--text-secondary)]">查看已完成 AI 整理后的 Markdown 原文，按博主快速筛选。</p>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium text-zinc-500 dark:text-[var(--text-secondary)]">博主 / 来源</label>
              <select
                value={selectedBlogger}
                onChange={event => setSelectedBlogger(event.target.value)}
                className="h-9 w-full rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-2 text-sm text-zinc-800 dark:text-[var(--text-primary)] focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="all">全部博主 ({completedNotes.length})</option>
                {bloggerOptions.map(blogger => (
                  <option key={blogger} value={blogger}>{blogger}</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-medium text-zinc-500 dark:text-[var(--text-secondary)]">搜索标题 / 标签</label>
              <div className="flex h-9 items-center gap-2 rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] px-2">
                <Search className="h-3.5 w-3.5 shrink-0 text-zinc-400 dark:text-[var(--text-muted)]" />
                <input
                  value={noteSearch}
                  onChange={event => setNoteSearch(event.target.value)}
                  placeholder="输入关键词"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none"
                />
              </div>
            </div>
            <div className="max-h-[560px] overflow-auto rounded border border-zinc-100 dark:border-[var(--surface-border)]">
              {filteredNotes.length === 0 ? (
                <div className="px-4 py-10 text-center text-sm text-zinc-400 dark:text-[var(--text-muted)]">暂无符合条件的 AI 笔记。</div>
              ) : (
                <div className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {filteredNotes.map(video => {
                    const active = selectedNote?.id === video.id;
                    return (
                      <button
                        key={video.id}
                        type="button"
                        onClick={() => loadNoteDetail(video.id)}
                        className={`block w-full px-3 py-3 text-left transition ${active ? 'bg-blue-50 dark:bg-[var(--info-bg)]' : 'bg-white dark:bg-[var(--surface)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]'}`}
                      >
                        <div className="line-clamp-2 text-sm font-semibold leading-5 text-zinc-900 dark:text-[var(--text-primary)]">{video.title || '无标题'}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-500 dark:text-[var(--text-secondary)]">
                          <span>{video.blogger || '未知来源'}</span>
                          <span className="text-zinc-300 dark:text-[var(--surface-border)]">·</span>
                          <span>{video.published_at || video.created_at || '-'}</span>
                          {video.rating > 0 && (
                            <>
                              <span className="text-zinc-300 dark:text-[var(--surface-border)]">·</span>
                              <span>{video.rating.toFixed(1)}分</span>
                            </>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </aside>

          <div className="min-w-0 rounded-xl border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] shadow-2xs">
            {!selectedNote ? (
              <div className="p-16 text-center text-zinc-400 dark:text-[var(--text-muted)]">
                <FileText className="mx-auto mb-3 h-10 w-10 text-zinc-300 dark:text-[var(--text-secondary)]" />
                <p className="text-sm font-medium text-zinc-700 dark:text-[var(--text-primary)]">请选择一篇 AI 笔记</p>
              </div>
            ) : (
              <div className="flex min-h-[640px] flex-col">
                <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-5 py-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <h2 className="line-clamp-2 text-base font-semibold leading-6 text-zinc-950 dark:text-[var(--text-primary)]">{selectedNote.title}</h2>
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                        <span>{selectedNote.blogger || '未知来源'}</span>
                        <span>{selectedNote.published_at || selectedNote.created_at || '-'}</span>
                        {selectedNote.summary_path && <span className="font-mono">Markdown</span>}
                      </div>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => loadNoteDetail(selectedNote.id)}
                        className="inline-flex h-8 items-center gap-1.5 rounded border border-zinc-200 dark:border-[var(--surface-border)] px-3 text-xs font-medium text-zinc-700 dark:text-[var(--text-primary)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]"
                      >
                        {loadingNoteId === selectedNote.id && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                        载入原文
                      </button>
                      <a
                        href={`/content?platform=${encodeURIComponent(selectedNote.platform || 'douyin')}&external_id=${encodeURIComponent(selectedNote.id)}`}
                        className="inline-flex h-8 items-center rounded bg-zinc-950 dark:bg-[var(--surface-border)] px-3 text-xs font-medium text-white dark:text-zinc-200 hover:bg-zinc-800 dark:hover:bg-[var(--text-muted)]"
                      >
                        打开详情
                      </a>
                    </div>
                  </div>
                  {noteError && <div className="mt-3 rounded border border-red-100 dark:border-[var(--danger-border)] bg-red-50 dark:bg-[var(--danger-bg)] px-3 py-2 text-xs text-red-700 dark:text-[var(--danger)]">{noteError}</div>}
                </div>
                <div className="flex-1 overflow-auto bg-zinc-50/60 dark:bg-[var(--surface-muted)] p-5">
                  {loadingNoteId === selectedNote.id ? (
                    <div className="flex items-center gap-2 text-sm text-zinc-500 dark:text-[var(--text-secondary)]">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      正在读取 Markdown 原文...
                    </div>
                  ) : (
                    <pre className="min-h-[520px] whitespace-pre-wrap break-words rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-5 font-mono text-xs leading-6 text-zinc-800 dark:text-[var(--text-primary)]">
                      {noteDetails[selectedNote.id]?.summary_markdown || selectedNote.summary_markdown || '点击“载入原文”读取完整 AI Markdown 笔记。'}
                    </pre>
                  )}
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Grid: Inputs Form Left, Tasks Monitor Right */}
      {activeCenterTab === 'tasks' && (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* LEFT COLUMN: Input Control panel */}
        <div className="space-y-6">
          <div className="p-6 border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl bg-white dark:bg-[var(--surface)] space-y-5 shadow-2xs">
            <h3 className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm tracking-tight uppercase">创建研判任务</h3>
            
            {/* Form category picker */}
            <div className="grid grid-cols-2 gap-1 p-0.5 border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg bg-zinc-100 dark:bg-[var(--surface-muted)]">
              <button
                type="button"
                onClick={() => setResearchType('single')}
                className={`py-1.5 rounded-md text-xs font-sans font-semibold transition cursor-pointer ${
                  researchType === 'single' ? 'bg-white dark:bg-[var(--surface)] text-zinc-950 dark:text-[var(--text-primary)] shadow-xs' : 'text-zinc-500 hover:text-zinc-900 dark:text-[var(--text-muted)] dark:hover:text-[var(--text-primary)]'
                }`}
              >
                单视频深度分析
              </button>
              <button
                type="button"
                onClick={() => setResearchType('blogger')}
                className={`py-1.5 rounded-md text-xs font-sans font-semibold transition cursor-pointer ${
                  researchType === 'blogger' ? 'bg-white dark:bg-[var(--surface)] text-zinc-950 dark:text-[var(--text-primary)] shadow-xs' : 'text-zinc-500 hover:text-zinc-900 dark:text-[var(--text-muted)] dark:hover:text-[var(--text-primary)]'
                }`}
              >
                博主作品批量分析
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              {researchType === 'single' ? (
                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">输入目标抖音地址 / 短链 / awemeID</label>
                  <input
                    type="text"
                    required
                    placeholder="例如：https://v.douyin.com/xyzB/"
                    value={singleUrl}
                    onChange={(e) => setSingleUrl(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg px-3.5 py-2 text-sm font-sans focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                  />
                  <span className="text-[10px] text-zinc-450 dark:text-[var(--text-muted)] font-sans block leading-relaxed">
                    系统将自动解析包含的短链，并由 Downloader 抓取无水印源流。
                  </span>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">博主主页分享地址 / 博主唯一代号</label>
                    <input
                      type="text"
                      required
                      placeholder="例如：AI创投派峰哥"
                      value={bloggerHandle}
                      onChange={(e) => setBloggerHandle(e.target.value)}
                      className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg px-3.5 py-2 text-sm font-sans focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">抓取篇数限制</label>
                    <input
                      type="number"
                      min={0}
                      value={scrapeLimit}
                      onChange={(e) => setScrapeLimit(Math.max(0, Number.parseInt(e.target.value || '0', 10) || 0))}
                      className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] rounded-lg px-3.5 py-2 text-sm font-sans focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                    />
                    <span className="text-[10px] text-zinc-450 dark:text-[var(--text-muted)] font-sans block leading-relaxed">
                      输入 0 表示不限制抓取篇数。成功识别博主后会自动加入持续监控，后续更新将按调度生成笔记并发布目录。
                    </span>
                  </div>
                </div>
              )}

              {/* Force overwrite parameter */}
              <div className="flex items-center space-x-2.5 pt-1.5">
                <input
                  type="checkbox"
                  id="force_retry_checkbox"
                  checked={forceRetry}
                  onChange={(e) => setForceRetry(e.target.checked)}
                  className="rounded border-zinc-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                />
                <label htmlFor="force_retry_checkbox" className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-sans select-none cursor-pointer">
                  强制重新跑 (覆盖已存在排队缓存)
                </label>
              </div>

              <button
                type="submit"
                className="w-full bg-blue-600 dark:bg-[var(--info)] text-white hover:bg-blue-700 dark:hover:bg-[var(--text-secondary)] rounded-lg font-sans py-2.5 text-xs font-semibold transition cursor-pointer flex items-center justify-center space-x-2 shadow-xs"
              >
                <Cpu className="w-4 h-4 text-white" />
                <span>立即启动 AI 研判任务</span>
              </button>
            </form>
          </div>

          {/* Guidelines info card */}
          <div className="p-5 border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl bg-white dark:bg-[var(--surface)] shadow-2xs font-sans space-y-3 text-zinc-500 dark:text-[var(--text-secondary)] text-xs leading-relaxed">
            <h4 className="font-semibold text-zinc-800 dark:text-[var(--text-primary)]">批量研究与资源调度说明</h4>
            <p>
              视频下载后会进入 FunASR 转录，质量不足或服务失败时回退 Whisper；转录成功的条目会立即排队交给 Agnes AI 整理。
            </p>
            <p>
              Ollama 仅在 Agnes AI 不可用时作为本地后备引擎，并继续服从现有 GPU 锁与显存调度。
            </p>
          </div>
        </div>

        {/* RIGHT COLUMN: Tasks execution monitors */}
        <div className="lg:col-span-2 space-y-6">
          
          {/* Statistical counters strip */}
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-100 dark:bg-[var(--surface-muted)] shadow-2xs md:grid-cols-5">
            <div>
              <div className="h-full bg-white dark:bg-[var(--surface)] p-4 text-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">全部任务</span>
                <span className="text-lg font-semibold font-sans text-zinc-900 dark:text-[var(--text-primary)] mt-1 block">{totalCount}</span>
              </div>
            </div>
            <div>
              <div className="h-full bg-white dark:bg-[var(--surface)] p-4 text-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">进行中</span>
                <span className="mt-1 flex items-center justify-center gap-1 text-lg font-semibold text-blue-700 dark:text-[var(--info)]">
                  {processingCount > 0 && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {processingCount + pausedCount}
                </span>
              </div>
            </div>
            <div>
              <div className="h-full bg-white dark:bg-[var(--surface)] p-4 text-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">排队中</span>
                <span className="text-lg font-semibold font-sans text-zinc-700 dark:text-[var(--text-primary)] mt-1 block">{queuedCount}</span>
              </div>
            </div>
            <div>
              <div className="h-full bg-white dark:bg-[var(--surface)] p-4 text-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">失败待处理</span>
                <span className="text-lg font-semibold font-sans text-red-700 dark:text-[var(--danger)] mt-1 block">{failedCount}</span>
              </div>
            </div>
            <div>
              <div className="h-full bg-white dark:bg-[var(--surface)] p-4 text-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans block">已完成</span>
                <span className="text-lg font-semibold font-sans text-emerald-700 dark:text-[var(--success)] mt-1 block">{completedCount}</span>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div>
                <h3 className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm tracking-tight">研究任务进度</h3>
                <p className="mt-1 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">默认只看进行中任务，历史完成项可通过筛选查看。</p>
              </div>
              <div className="flex flex-wrap gap-1 rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-1">
                {[
                  ['active', `进行中 ${processingCount + pausedCount}`],
                  ['queued', `排队 ${queuedCount}`],
                  ['failed', `失败 ${failedCount}`],
                  ['completed', `完成 ${completedCount}`],
                  ['all', `全部 ${totalCount}`],
                ].map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setTaskFilter(id as typeof taskFilter)}
                    className={`min-h-8 rounded-md px-2.5 text-xs font-medium transition ${
                      taskFilter === id ? 'bg-white dark:bg-[var(--surface)] text-zinc-950 dark:text-[var(--text-primary)] shadow-xs' : 'text-zinc-500 hover:text-zinc-800 dark:text-[var(--text-muted)] dark:hover:text-[var(--text-primary)]'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {visibleTasks.length === 0 ? (
              <div className="p-16 border border-dashed border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] rounded-xl text-center text-zinc-400 dark:text-[var(--text-muted)] font-sans shadow-2xs">
                <Database className="w-10 h-10 mx-auto text-zinc-300 dark:text-[var(--text-secondary)] stroke-1 mb-3" />
                <p className="text-sm font-medium text-zinc-700 dark:text-[var(--text-primary)]">
                  {tasks.length === 0 ? '暂无研究任务' : `当前没有“${taskFilter === 'active' ? '进行中' : taskFilter === 'queued' ? '排队中' : taskFilter === 'failed' ? '失败待处理' : taskFilter === 'completed' ? '已完成' : '全部'}”任务`}
                </p>
                <p className="mt-1 text-xs">{tasks.length === 0 ? '创建任务后，进度会按真实处理顺序显示在这里。' : '可以切换上方筛选查看其他任务。'}</p>
              </div>
            ) : (
              <div className="space-y-4">
                {visibleTasks.map((task) => {
                  const isExpanded = expandedTaskId === task.id;
                  
                  return (
                    <div
                      key={task.id}
                      id={`task_card_${task.id}`}
                      className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl bg-white dark:bg-[var(--surface)] overflow-hidden shadow-2xs"
                    >
                      {/* Accordion header line */}
                      <div
                        onClick={() => toggleTask(task)}
                        className={`p-4.5 cursor-pointer hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] transition flex items-center justify-between gap-4 ${
                          isExpanded ? 'bg-zinc-50/50 dark:bg-[var(--surface-muted)]' : ''
                        }`}
                      >
                        <div className="flex-1 min-w-0 space-y-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm font-semibold ${
                              task.type === 'single' ? 'bg-blue-50 text-blue-700 dark:bg-[var(--info-bg)] dark:text-[var(--info)]' : 'bg-purple-50 text-purple-700 dark:text-[var(--info)] dark:bg-[var(--info-bg)]'
                            }`}>
                              {task.type === 'single' ? '单视频解构' : '博主多篇'}
                            </span>
                            <span className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${taskStatusClass(task.status)}`}>
                              {taskStatusLabel(task.status)}
                            </span>
                            <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] font-mono">ID: {task.id}</span>
                            <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] font-mono">{task.created_at}</span>
                          </div>
                          <h4 className="text-sm font-sans font-bold text-zinc-900 dark:text-[var(--text-primary)] truncate">
                            目标: {task.target}
                          </h4>
                          {task.type === 'blogger' && task.pipeline_stages && (
                            <TaskStageCounts stages={task.pipeline_stages} />
                          )}
                        </div>

                        <div className="flex items-center space-x-3 shrink-0">
                          {isExpanded ? <ChevronUp className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" /> : <ChevronDown className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />}
                        </div>
                      </div>

                      {/* Accordion body expander panel */}
                      {isExpanded && (
                        <div className="border-t border-zinc-150 dark:border-[var(--surface-border)] p-5 bg-zinc-50/30 dark:bg-[var(--surface-muted)] space-y-6 animate-fade-in">
                          
                          {task.type === 'blogger' && (
                            <div className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] p-4">
                              <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-zinc-500 dark:text-[var(--text-secondary)]">
                                <span>总计 <strong className="font-mono text-zinc-900 dark:text-[var(--text-primary)]">{task.total_items || 0}</strong></span>
                                <span>成功 <strong className="font-mono text-emerald-700 dark:text-[var(--success)]">{task.completed_items || 0}</strong></span>
                                <span>跳过 <strong className="font-mono text-zinc-700 dark:text-[var(--text-primary)]">{task.skipped_items || 0}</strong></span>
                                <span>失败 <strong className="font-mono text-red-700 dark:text-[var(--danger)]">{task.failed_items || 0}</strong></span>
                              </div>
                            </div>
                          )}

                          {/* Operational button overrides inside collapsible view */}
                          <div className="flex flex-wrap items-center gap-2.5 pt-2">
                            {task.status === 'processing' && (
                              <button
                                type="button"
                                onClick={() => controlResearchTask(task.id, 'pause')}
                                className="px-3.5 py-1.5 border border-zinc-200 dark:border-[var(--surface-border)] hover:border-zinc-900 dark:hover:border-[var(--text-primary)] rounded-lg text-xs text-zinc-700 dark:text-[var(--text-primary)] bg-white dark:bg-[var(--surface)] font-sans transition cursor-pointer"
                              >
                                <Pause className="w-3.5 h-3.5 inline mr-1" />
                                暂停调度
                              </button>
                            )}
                            {task.status === 'paused' && (
                              <button
                                type="button"
                                onClick={() => controlResearchTask(task.id, 'resume')}
                                className="px-3.5 py-1.5 bg-emerald-600 dark:bg-[var(--success)] hover:bg-emerald-700 dark:hover:bg-[var(--text-secondary)] text-white rounded-lg text-xs font-sans font-semibold transition cursor-pointer"
                              >
                                <Play className="w-3.5 h-3.5 inline mr-1" />
                                继续任务
                              </button>
                            )}
                            {(task.status === 'completed' || task.status === 'failed') && (
                              <button
                                type="button"
                                onClick={() => controlResearchTask(task.id, 'restart')}
                                className="px-3.5 py-1.5 bg-blue-600 dark:bg-[var(--info)] hover:bg-blue-700 dark:hover:bg-[var(--text-secondary)] text-white rounded-lg text-xs font-sans font-semibold transition cursor-pointer"
                              >
                                <RotateCcw className="w-3.5 h-3.5 inline mr-1" />
                                重新拉取
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => showJobDetail(task.id)}
                              className="px-3.5 py-1.5 border border-zinc-200 hover:border-zinc-900 rounded-lg text-xs text-zinc-700 bg-white font-sans transition cursor-pointer"
                            >
                              查看详情
                            </button>
                            {Number(task.failed_items || 0) > 0 && (
                              <button
                                type="button"
                                onClick={() => retryResearchFailed(task.id)}
                                className="px-3.5 py-1.5 bg-red-600 dark:bg-[var(--danger)] hover:bg-red-700 dark:hover:bg-[var(--text-secondary)] text-white rounded-lg text-xs font-sans font-semibold transition cursor-pointer"
                              >
                                重试失败项
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => controlResearchTask(task.id, 'cancel')}
                              className="px-3.5 py-1.5 text-xs font-sans text-red-655 hover:text-red-700 dark:hover:text-[var(--danger)] hover:bg-red-50 dark:hover:bg-[var(--danger-bg)] rounded-lg transition cursor-pointer font-semibold"
                            >
                              <XCircle className="w-3.5 h-3.5 inline mr-1" />
                              取消任务
                            </button>
                          </div>

                          {(loadingJobId === task.id || jobDetails[task.id]) && (
                            <div className="p-4 border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] rounded-lg space-y-4">
                              {loadingJobId === task.id ? (
                                <div className="flex items-center space-x-2 text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-sans">
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  <span>正在读取研究任务详情...</span>
                                </div>
                              ) : (
                                <>
                                  <div className="grid grid-cols-2 md:grid-cols-6 gap-2 text-center text-xs font-mono">
                                    {[
                                      ['下载', jobDetails[task.id]?.pipeline?.counts?.download],
                                      ['转录', jobDetails[task.id]?.pipeline?.counts?.transcript],
                                      ['AI 与笔记', jobDetails[task.id]?.pipeline?.counts?.ai],
                                      ['完成', jobDetails[task.id]?.pipeline?.counts?.done],
                                      ['失败', jobDetails[task.id]?.pipeline?.counts?.failed],
                                      ['ETA', jobDetails[task.id]?.pipeline?.eta_text]
                                    ].map(([label, value]) => (
                                      <div key={String(label)} className="p-2 bg-zinc-50 dark:bg-[var(--surface-muted)] rounded border border-zinc-100 dark:border-[var(--surface-border)]">
                                        <div className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)]">{label as string}</div>
                                        <div className="text-zinc-900 dark:text-[var(--text-primary)] font-semibold mt-1">{value ?? '暂无'}</div>
                                      </div>
                                    ))}
                                  </div>

                                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs font-mono">
                                    <div className="p-2 bg-zinc-50 dark:bg-[var(--surface-muted)] rounded border border-zinc-100 dark:border-[var(--surface-border)]">下载目录：{jobDetails[task.id]?.pipeline?.download_dir_size || '暂无'}</div>
                                    <div className="p-2 bg-zinc-50 dark:bg-[var(--surface-muted)] rounded border border-zinc-100 dark:border-[var(--surface-border)]">笔记目录：{jobDetails[task.id]?.pipeline?.notes_dir_size || '暂无'}</div>
                                    <div className="p-2 bg-zinc-50 dark:bg-[var(--surface-muted)] rounded border border-zinc-100 dark:border-[var(--surface-border)]">任务状态：{String(jobDetails[task.id]?.job?.status || task.status)}</div>
                                  </div>

                                  {jobDetails[task.id]?.job?.confirm_status === 'pending' && (
                                    <div className="flex items-center justify-between gap-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-[var(--warning-border)] dark:bg-[var(--warning-bg)] dark:text-[var(--warning)]">
                                      <span>历史扫描仅列出内容；批准条目后才会处理。</span>
                                      <button type="button" disabled={backfillAction === `${task.id}:execute`} onClick={() => void executeBackfill(task.id)} className="rounded bg-amber-700 px-2.5 py-1 font-semibold text-white disabled:opacity-60">
                                        {backfillAction === `${task.id}:execute` ? '提交中' : '确认执行已批准项'}
                                      </button>
                                    </div>
                                  )}

                                  <div className="max-h-72 overflow-auto border border-zinc-150 dark:border-[var(--surface-border)] rounded">
                                    <table className="w-full text-xs font-sans">
                                      <thead className="bg-zinc-50 dark:bg-[var(--surface-muted)] text-zinc-500 dark:text-[var(--text-secondary)] sticky top-0">
                                        <tr>
                                          <th className="text-left p-2 font-semibold">作品 / 标题</th>
                                          <th className="text-left p-2 font-semibold">状态</th>
                                          <th className="text-left p-2 font-semibold">错误</th>
                                          {jobDetails[task.id]?.job?.confirm_status === 'pending' && <th className="text-right p-2 font-semibold">审核</th>}
                                        </tr>
                                      </thead>
                                      <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                                        {(jobDetails[task.id]?.items || []).slice(0, 80).map((item, index) => {
                                          const itemStatus = String(item.status || item.current_stage || 'pending');
                                          return (
                                            <tr key={`${task.id}-${index}`}>
                                              <td className="p-2 max-w-[200px]">
                                                <div className="truncate font-mono text-zinc-600 dark:text-[var(--text-secondary)]" title={String(item.aweme_id || item.id || '-')}>
                                                  {String(item.aweme_id || item.id || '-')}
                                                </div>
                                                {item.title && (
                                                  <div className="truncate text-[10px] text-zinc-400 dark:text-[var(--text-muted)]" title={item.title}>{item.title}</div>
                                                )}
                                              </td>
                                              <td className="p-2">
                                                <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                                                  itemStatus === 'success' || itemStatus === 'skipped' ? 'bg-emerald-50 text-emerald-600 dark:bg-[var(--success-bg)] dark:text-[var(--success)]' :
                                                  itemStatus === 'failed' || itemStatus === 'cancelled' ? 'bg-red-50 text-red-600 dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]' :
                                                  itemStatus === 'downloading' || itemStatus === 'transcribing' || itemStatus === 'summarizing' || itemStatus === 'noting' ? 'bg-blue-50 text-blue-600 dark:bg-[var(--info-bg)] dark:text-[var(--info)]' :
                                                  'bg-zinc-50 text-zinc-400 dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]'
                                                }`}>{itemStatus}</span>
                                              </td>
                                              <td className="p-2 text-red-600 dark:text-[var(--danger)] max-w-[160px] truncate" title={String(item.error_message || item.last_error || '')}>
                                                {String(item.error_message || item.last_error || '')}
                                              </td>
                                              {jobDetails[task.id]?.job?.confirm_status === 'pending' && (
                                                <td className="p-2 text-right whitespace-nowrap">
                                                  <button type="button" disabled={!item.external_content_id || Boolean(backfillAction)} onClick={() => void reviewBackfillItem(task.id, String(item.external_content_id), true)} className="mr-1 rounded border border-emerald-200 px-1.5 py-0.5 text-[10px] text-emerald-700 disabled:opacity-50">批准</button>
                                                  <button type="button" disabled={!item.external_content_id || Boolean(backfillAction)} onClick={() => void reviewBackfillItem(task.id, String(item.external_content_id), false)} className="rounded border border-zinc-200 px-1.5 py-0.5 text-[10px] text-zinc-600 disabled:opacity-50">跳过</button>
                                                </td>
                                              )}
                                            </tr>
                                          );
                                        })}
                                      </tbody>
                                    </table>
                                  </div>
                                </>
                              )}
                            </div>
                          )}

                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

        </div>

      </div>
      )}
    </div>
  );
}
