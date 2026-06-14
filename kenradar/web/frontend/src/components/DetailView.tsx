/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useState } from 'react';
import { 
  ArrowLeft, 
  ExternalLink, 
  Copy, 
  RefreshCw, 
  ChevronDown, 
  ChevronUp, 
  Video, 
  Check, 
  AlertTriangle,
} from 'lucide-react';
import { VideoContent } from '../types';

interface DetailViewProps {
  videoId: string;
  videos: VideoContent[];
  navigateTo: (page: string, id: string | null) => void;
  retryStage: (id: string, stage?: any) => void;
  pushToFeishuManually: (id: string) => void;
}

type NoteBlock =
  | { type: 'heading'; level: number; content: string }
  | { type: 'paragraph'; content: string }
  | { type: 'callout'; content: string }
  | { type: 'quote'; content: string }
  | { type: 'list'; ordered: boolean; items: string[] };

function cleanReadingMarkdown(markdown: string) {
  const withoutFrontmatter = markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '').trim();
  const transcriptStart = withoutFrontmatter.search(/^##\s+(?:四、视频原始转录|三、视频原稿)\s*$/m);
  return (transcriptStart >= 0 ? withoutFrontmatter.slice(0, transcriptStart) : withoutFrontmatter).trim();
}

function pushParagraph(blocks: NoteBlock[], paragraph: string[]) {
  const content = paragraph.map(line => line.trim()).filter(Boolean).join(' ');
  if (content) blocks.push({ type: 'paragraph', content });
  paragraph.length = 0;
}

function noteBlocks(markdown: string): NoteBlock[] {
  const blocks: NoteBlock[] = [];
  const lines = cleanReadingMarkdown(markdown).split(/\r?\n/);
  const paragraph: string[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    const line = raw.trim();
    if (!line) {
      pushParagraph(blocks, paragraph);
      continue;
    }

    if (/^#{1,3}\s+/.test(line)) {
      pushParagraph(blocks, paragraph);
      const [, marks, content] = line.match(/^(#{1,3})\s+(.+)$/) || [];
      blocks.push({ type: 'heading', level: marks.length, content });
      continue;
    }

    if (/^>\s*\[!summary\]/i.test(line)) {
      pushParagraph(blocks, paragraph);
      const callout: string[] = [];
      while (index + 1 < lines.length && lines[index + 1].trim().startsWith('>')) {
        index += 1;
        callout.push(lines[index].trim().replace(/^>\s?/, ''));
      }
      blocks.push({ type: 'callout', content: callout.join(' ').trim() });
      continue;
    }

    if (line.startsWith('>')) {
      pushParagraph(blocks, paragraph);
      const quote: string[] = [line.replace(/^>\s?/, '')];
      while (index + 1 < lines.length && lines[index + 1].trim().startsWith('>')) {
        index += 1;
        quote.push(lines[index].trim().replace(/^>\s?/, ''));
      }
      blocks.push({ type: 'quote', content: quote.join(' ').trim() });
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.+)$/);
    const bulletMatch = line.match(/^-\s+(.+)$/);
    if (orderedMatch || bulletMatch) {
      pushParagraph(blocks, paragraph);
      const ordered = Boolean(orderedMatch);
      const items: string[] = [];
      while (index < lines.length) {
        const itemLine = lines[index].trim();
        const itemMatch = ordered ? itemLine.match(/^\d+\.\s+(.+)$/) : itemLine.match(/^-\s+(.+)$/);
        if (!itemMatch) {
          index -= 1;
          break;
        }
        const itemParts = [itemMatch[1]];
        while (index + 1 < lines.length && lines[index + 1].trim() && /^\s{2,}\S/.test(lines[index + 1])) {
          index += 1;
          itemParts.push(lines[index].trim());
        }
        items.push(itemParts.join(' '));
        index += 1;
      }
      blocks.push({ type: 'list', ordered, items });
      continue;
    }

    paragraph.push(line);
  }

  pushParagraph(blocks, paragraph);
  return blocks;
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

function transcriptParagraphs(text: string) {
  const normalized = text.replace(/\s+/g, ' ').trim();
  if (!normalized) return [];
  const parts = normalized.split(/(?<=[。！？!?])\s*/).map(item => item.trim()).filter(Boolean);
  const paragraphs: string[] = [];
  let current = '';
  parts.forEach(part => {
    const next = current ? `${current}${part}` : part;
    if (next.length >= 120) {
      paragraphs.push(next);
      current = '';
    } else {
      current = next;
    }
  });
  if (current) paragraphs.push(current);
  return paragraphs;
}

function renderInline(text: string) {
  const tokens = text.split(/(\*\*[^*]+\*\*|\[\[[^\]]+\]\])/g).filter(Boolean);
  return tokens.map((token, index) => {
    if (token.startsWith('**') && token.endsWith('**')) {
      return <strong key={`${token}-${index}`} className="font-semibold text-zinc-950">{token.slice(2, -2)}</strong>;
    }
    if (token.startsWith('[[') && token.endsWith(']]')) {
      return (
        <span key={`${token}-${index}`} className="inline-flex rounded bg-blue-50 px-1.5 py-0.5 text-blue-700">
          {token.slice(2, -2)}
        </span>
      );
    }
    return <React.Fragment key={`${token}-${index}`}>{token}</React.Fragment>;
  });
}

function MarkdownNoteReader({ markdown, hideFirstCallout = false }: { markdown: string; hideFirstCallout?: boolean }) {
  let skippedCallout = false;
  const blocks = noteBlocks(markdown).filter(block => {
    if (hideFirstCallout && block.type === 'callout' && !skippedCallout) {
      skippedCallout = true;
      return false;
    }
    return true;
  });
  return (
    <article className="max-w-[76ch] space-y-4 font-sans text-base leading-8 text-zinc-700">
      {blocks.map((block, index) => {
        if (block.type === 'heading') {
          if (block.level === 1) {
            return <h1 key={`heading-${index}`} className="max-w-3xl text-2xl font-semibold leading-tight text-zinc-950 md:text-[28px]">{renderInline(block.content)}</h1>;
          }
          if (block.level === 2) {
            return <h2 key={`heading-${index}`} className="pt-5 text-lg font-semibold text-zinc-950">{renderInline(block.content)}</h2>;
          }
          return <h3 key={`heading-${index}`} className="pt-2 text-sm font-semibold text-zinc-900">{renderInline(block.content)}</h3>;
        }
        if (block.type === 'callout') {
          return (
            <div key={`callout-${index}`} className="rounded-lg border border-blue-100 bg-blue-50/70 p-4 text-[15px] leading-7 text-zinc-800">
              <div className="mb-1 text-xs font-semibold text-blue-700">一句话结论</div>
              <p>{renderInline(block.content)}</p>
            </div>
          );
        }
        if (block.type === 'quote') {
          return <blockquote key={`quote-${index}`} className="border-l-2 border-zinc-200 pl-4 text-sm leading-7 text-zinc-500">{renderInline(block.content)}</blockquote>;
        }
        if (block.type === 'list') {
          const List = block.ordered ? 'ol' : 'ul';
          return (
            <List key={`list-${index}`} className={`${block.ordered ? 'list-decimal' : 'list-disc'} space-y-3 pl-5 text-[15px] leading-7 marker:text-zinc-400`}>
              {block.items.map((item, itemIndex) => <li key={`${item}-${itemIndex}`}>{renderInline(item)}</li>)}
            </List>
          );
        }
        return <p key={`paragraph-${index}`} className="text-base leading-8 text-zinc-700">{renderInline(block.content)}</p>;
      })}
    </article>
  );
}

export default function DetailView({
  videoId,
  videos,
  navigateTo,
}: DetailViewProps) {
  const listedVideo = videos.find(v => v.id === videoId);

  // States
  const [showWhisper, setShowWhisper] = useState(false);
  const [copiedNote, setCopiedNote] = useState(false);
  const [detailVideo, setDetailVideo] = useState<VideoContent | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(true);
  const [progress, setProgress] = useState<Record<string, any> | null>(null);
  const video = detailVideo || listedVideo;

  useEffect(() => {
    let cancelled = false;
    setDetailVideo(null);
    setLoadingDetail(true);
    const loadDetail = async () => {
      try {
        const response = await fetch(`/api/aweme/detail?id=${encodeURIComponent(videoId)}`, { credentials: 'same-origin' });
        const payload = await response.json();
        if (!cancelled && response.ok && payload.ok !== false) setDetailVideo(payload.item || null);
      } catch {
        if (!cancelled) setDetailVideo(null);
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    };
    const loadProgress = async () => {
      try {
        const response = await fetch(`/api/aweme/progress?id=${encodeURIComponent(videoId)}`, { credentials: 'same-origin' });
        const payload = await response.json();
        if (!cancelled && payload.ok !== false) setProgress(payload.progress || null);
      } catch {
        if (!cancelled) setProgress(null);
      }
    };
    loadDetail();
    loadProgress();
    const timer = window.setInterval(loadProgress, 45000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [videoId]);

  if (loadingDetail && !video) {
    return (
      <div className="p-8 text-center space-y-4 font-sans text-zinc-500 animate-fade-in">
        <RefreshCw className="w-8 h-8 text-amber-500 animate-spin mx-auto" />
        <p className="text-sm">正在载入内容详情...</p>
      </div>
    );
  }

  if (!video) {
    return (
      <div className="p-8 text-center space-y-4 font-sans text-zinc-500 animate-fade-in">
        <AlertTriangle className="w-12 h-12 text-red-500 mx-auto" />
        <h3 className="font-bold text-lg text-zinc-900">未找到相应的 Aweme ID</h3>
        <p className="text-sm">该内容或已被离线清除，或 ID 拼写有错。</p>
        <button
          onClick={() => navigateTo('archive', null)}
          className="px-4 py-2 bg-zinc-950 text-white rounded text-xs font-sans font-medium"
        >
          返回阅读库
        </button>
      </div>
    );
  }

  const handleCopySummary = () => {
    if (!video.summary_markdown) return;
    navigator.clipboard.writeText(video.summary_markdown);
    setCopiedNote(true);
    setTimeout(() => setCopiedNote(false), 2500);
  };
  const openBloggerDirectory = () => {
    window.history.pushState(null, '', `/archive?blogger=${encodeURIComponent(video.blogger || '未知来源')}`);
    window.dispatchEvent(new PopStateEvent('popstate'));
  };
  const conclusion = conclusionFor(video);
  const scoreItems = [
    { label: '重要性', value: video.importance_score },
    { label: '新颖性', value: video.novelty_score },
    { label: '信息密度', value: video.information_density },
    { label: '业务相关', value: video.business_relevance },
  ].filter(item => Number(item.value || 0) > 0);
  const transcriptBlocks = transcriptParagraphs(video.whisper_text || '');

  return (
    <div className="space-y-6 animate-fade-in">
      
      {/* Top breadcrumb navigation link */}
      <div className="flex items-center justify-between border-b border-zinc-200 pb-3 gap-4">
        <button
          onClick={() => navigateTo('archive', null)}
          className="flex items-center space-x-1.5 text-zinc-500 hover:text-zinc-905 font-sans text-sm font-semibold transition cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>返回阅读库</span>
        </button>
        <div className="flex min-w-0 flex-1 items-center truncate text-xs text-zinc-400">
          <span className="shrink-0">阅读库</span>
          <span className="mx-1 shrink-0 text-zinc-300">/</span>
          <button
            type="button"
            onClick={openBloggerDirectory}
            title={`查看 ${video.blogger || '该博主'} 的全部笔记`}
            className="shrink-0 font-medium text-blue-700 hover:text-blue-900 hover:underline"
          >
            {video.blogger || '未知来源'}
          </button>
          <span className="mx-1 shrink-0 text-zinc-300">/</span>
          <span className="truncate text-zinc-600">{video.title}</span>
        </div>
        <div className="hidden text-zinc-400 font-mono text-xs md:block">
          aweme_id: {video.id}
        </div>
      </div>

      {/* Main Grid Conforming to Section 3.5 */}
      <div className="mx-auto grid max-w-[1180px] grid-cols-1 gap-8 xl:grid-cols-[minmax(0,820px)_320px]">
        
        {/* LEFT COLUMN: Markdown reading area (taking 2/3 space for deep readability) */}
        <div className="space-y-6">
          <div className="border border-zinc-150 rounded-lg bg-white min-h-[500px] shadow-xs relative overflow-hidden">
            
            {/* Ribbon tag indicating rating */}
            {video.status === 'completed' && (
              <div className="absolute right-5 top-5 flex items-center gap-2 rounded border border-amber-100 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 select-none">
                <span>{video.rating.toFixed(1)} 分</span>
                {video.recommend_action && <span className="text-amber-500">{video.recommend_action.toUpperCase()}</span>}
              </div>
            )}

            {video.status === 'completed' && video.summary_markdown ? (
              <div className="px-6 py-7 md:px-8 md:py-8">
                {conclusion && (
                  <div className="mb-7 max-w-[76ch] rounded-lg border border-blue-100 bg-blue-50/80 p-5 shadow-2xs">
                    <div className="mb-2 text-xs font-semibold text-blue-700">一句话结论</div>
                    <p className="text-lg font-medium leading-8 text-blue-950">“{renderInline(conclusion)}”</p>
                  </div>
                )}
                <MarkdownNoteReader markdown={video.summary_markdown} hideFirstCallout={Boolean(conclusion)} />
              </div>
            ) : video.status === 'failed' ? (
              <div className="py-20 text-center space-y-4 max-w-md mx-auto">
                <AlertTriangle className="w-12 h-12 text-red-500 mx-auto" />
                <h3 className="font-sans font-bold text-zinc-900 text-lg">此视频此前执行失败</h3>
                <p className="text-sm font-sans text-zinc-500 leading-relaxed">
                  在 **[{video.failed_at_step?.toUpperCase()}]** 环节处理失败。请在运行中心处理重试与日志排查。
                </p>
                <div className="bg-zinc-50 font-mono text-zinc-600 text-[11px] p-3 rounded border border-zinc-200 break-all leading-relaxed max-h-40 overflow-y-auto">
                  报错代码：{video.error_message}
                </div>
              </div>
            ) : (
              <div className="py-24 text-center space-y-4 max-w-sm mx-auto">
                <RefreshCw className="w-10 h-10 text-amber-500 animate-spin mx-auto" />
                <p className="font-sans font-bold text-zinc-800 text-base">定时调度进程执行中...</p>
                <p className="text-zinc-500 font-sans text-xs leading-relaxed">
                  正在依次进行：1. 下载视频 2. FunASR 转录，必要时回退 Whisper 3. Agnes AI 整理，必要时回退 Ollama 4. 生成 Obsidian 笔记。
                </p>
              </div>
            )}
          </div>

          {/* Whisper Raw transcript foldout (Section 3.5 Collapse transcript view) */}
          <div className="border border-zinc-150 rounded-lg bg-white overflow-hidden">
            <div
              onClick={() => setShowWhisper(!showWhisper)}
              className="p-4 bg-zinc-50 border-b border-zinc-150 flex items-center justify-between cursor-pointer hover:bg-zinc-100/50 transition select-none"
            >
              <h3 className="font-sans font-bold text-zinc-905 text-xs tracking-wider uppercase flex items-center space-x-2">
                <Video className="w-4 h-4 text-zinc-400" />
                <span>Whisper 语音识别完整原稿 ({showWhisper ? '收起折叠' : '点击展平'})</span>
              </h3>
              {showWhisper ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
            </div>

            {showWhisper && (
              <div className="p-6 bg-white animate-fade-in font-sans text-zinc-700 text-sm leading-7 select-text">
                {transcriptBlocks.length ? (
                  <div className="mx-auto max-w-[76ch] space-y-4">
                    {transcriptBlocks.map((paragraph, index) => (
                      <p key={`${index}-${paragraph.slice(0, 12)}`} className="rounded border border-zinc-100 bg-zinc-50/50 px-4 py-3 text-zinc-700">
                        {paragraph}
                      </p>
                    ))}
                  </div>
                ) : (
                  <p className="text-zinc-400 text-center py-6 text-xs">
                    {video.status === 'failed' ? '本条视频由于尚未完成转译，无法检索到 Whisper 原稿数据。' : '正在对分片切片进行提取中...'}
                  </p>
                )}
              </div>
            )}
          </div>

        </div>

        {/* RIGHT COLUMN: Info summary upper + foldout control lower (Section 3.5) */}
        <div className="space-y-6">
          
          {/* Upper Side Panel: Info summary cards */}
          <div className="p-5 border border-zinc-150 rounded-lg bg-zinc-50/50 space-y-4 font-sans text-xs text-zinc-650">
            <h3 className="font-sans font-semibold text-zinc-900 text-xs tracking-tight uppercase text-zinc-500 font-mono">雷达收录概览</h3>
            
            <div className="space-y-3 pt-1.5 border-t border-zinc-150">
              <div className="flex justify-between">
                <span>所属主播：</span>
                <span className="font-semibold text-zinc-900">{video.blogger}</span>
              </div>
              <div className="flex justify-between">
                <span>评分等级：</span>
                <span className={`font-mono font-bold ${video.rating >= 8.5 ? 'text-amber-600' : 'text-zinc-700'}`}>
                  {video.status === 'completed' ? `${video.rating.toFixed(1)} / 10.0` : '未完成'}
                </span>
              </div>
              <div className="flex justify-between">
                <span>推荐分发动作：</span>
                <span className="font-bold text-zinc-900 uppercase">{video.recommend_action}</span>
              </div>
              <div className="flex justify-between">
                <span>视频总时长：</span>
                <span className="font-mono text-zinc-900">{video.duration}</span>
              </div>
              <div className="flex justify-between items-center">
                <span>外部原地址：</span>
                <a 
                  href={video.original_url} 
                  target="_blank" 
                  referrerPolicy="no-referrer"
                  className="text-zinc-500 hover:text-zinc-950 font-sans font-semibold inline-flex items-center space-x-1 border-b border-zinc-300"
                >
                  <span>打开抖音源链</span>
                  <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            </div>

            {scoreItems.length > 0 && (
              <div className="border-t border-zinc-150 pt-4 space-y-3">
                <span className="text-[10px] text-zinc-400 font-serif uppercase tracking-widest block">四维评分</span>
                <div className="grid grid-cols-2 gap-2">
                  {scoreItems.map(item => {
                    const value = Number(item.value || 0);
                    return (
                      <div key={item.label} className="rounded border border-zinc-150 bg-white p-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[11px] text-zinc-500">{item.label}</span>
                          <span className="font-mono text-xs font-semibold text-zinc-900">{value.toFixed(1)}</span>
                        </div>
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-100">
                          <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.min(100, Math.max(0, value * 10))}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {video.recommendation_reason && (
              <div className="border-t border-zinc-150 pt-4 space-y-2">
                <span className="text-[10px] text-zinc-400 font-serif uppercase tracking-widest block">推荐理由</span>
                <p className="rounded border border-blue-100 bg-blue-50/60 p-3 text-xs leading-6 text-blue-950">
                  {video.recommendation_reason}
                </p>
              </div>
            )}

            {/* Keyword tags bubble list */}
            {video.tags && video.tags.length > 0 && (
              <div className="border-t border-zinc-150 pt-4 space-y-2">
                <span className="text-[10px] text-zinc-400 font-serif uppercase tracking-widest block">提取实体标签：</span>
                <div className="flex flex-wrap gap-1.5">
                  {video.tags.map((tag, idx) => (
                    <span key={idx} className="text-[10px] bg-white border border-zinc-200 px-2 py-0.5 rounded text-zinc-650 font-medium">
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {progress && (
            <div className="p-5 border border-zinc-150 rounded-lg bg-white space-y-4 font-sans text-xs text-zinc-650">
              <h3 className="font-sans font-semibold text-zinc-900 text-xs tracking-tight uppercase text-zinc-500 font-mono">处理进度</h3>
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-mono">
                  <span>{String(progress.overall || 'pending').toUpperCase()}</span>
                  <span>{Number(progress.percent || 0)}%</span>
                </div>
                <div className="h-2 bg-zinc-100 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-600 rounded-full transition-all" style={{ width: `${Number(progress.percent || 0)}%` }} />
                </div>
              </div>
              <div className="space-y-2">
                {(progress.steps || []).map((step: Record<string, any>, index: number) => (
                  <div key={String(step.key)} className="flex gap-3 rounded border border-zinc-150 bg-zinc-50 p-2.5">
                    <div className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                      String(step.state || step.status || '') === 'success' ? 'bg-emerald-100 text-emerald-700' :
                        String(step.state || step.status || '') === 'failed' ? 'bg-red-100 text-red-700' :
                          'bg-blue-100 text-blue-700'
                    }`}>
                      {index + 1}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex justify-between gap-2">
                        <span className="font-semibold text-zinc-900">{String(step.label || step.key)}</span>
                        <span className="font-mono text-zinc-500">{String(step.state || step.status || '-')}</span>
                      </div>
                      {step.updated_at && <div className="text-[10px] text-zinc-400 font-mono mt-1">{String(step.updated_at)}</div>}
                      {step.error && <div className="text-[10px] text-red-600 font-mono mt-1 break-all">{String(step.error)}</div>}
                    </div>
                  </div>
                ))}
              </div>
              {progress.latest_job?.id && (
                <a
                  href={`/?page=research`}
                  className="block text-xs font-sans font-semibold text-blue-600 hover:text-blue-700"
                >
                  关联研究任务 #{String(progress.latest_job.id)}
                </a>
              )}
              {progress.updated_at && <div className="text-[10px] text-zinc-400 font-mono">更新时间：{String(progress.updated_at)}</div>}
            </div>
          )}

          <div className="border border-zinc-150 rounded-lg bg-white p-4 space-y-3">
            <h3 className="text-xs font-semibold text-zinc-500">阅读资产</h3>
            <button
              onClick={handleCopySummary}
              disabled={video.status !== 'completed'}
              className="flex w-full min-h-10 items-center justify-center gap-2 rounded bg-zinc-900 px-3 py-2.5 text-xs font-semibold text-white transition hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {copiedNote ? <Check className="w-4 h-4 text-emerald-400" /> : <Copy className="w-4 h-4" />}
              <span>{copiedNote ? 'Markdown 已复制' : '复制 Obsidian 笔记'}</span>
            </button>
            {video.summary_path && (
              <div className="rounded border border-zinc-100 bg-zinc-50 p-3 text-[11px] leading-5 text-zinc-500">
                <div className="mb-1 font-semibold text-zinc-700">Obsidian 文件路径</div>
                <div className="break-all font-mono">{video.summary_path}</div>
              </div>
            )}
            {video.original_url && (
              <a
                href={video.original_url}
                target="_blank"
                rel="noreferrer"
                referrerPolicy="no-referrer"
                className="flex min-h-10 items-center justify-center gap-2 rounded border border-zinc-200 px-3 py-2.5 text-xs font-semibold text-zinc-700 hover:bg-zinc-50"
              >
                <ExternalLink className="w-4 h-4" />
                打开原视频
              </a>
            )}
          </div>

        </div>

      </div>
    </div>
  );
}
