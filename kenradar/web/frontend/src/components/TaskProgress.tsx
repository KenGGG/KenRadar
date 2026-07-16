/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { AlertTriangle, Check, CheckCircle2, Circle, Download, Loader2, Sparkles, Waves, X } from 'lucide-react';
import { ResearchTask } from '../types';

export const RESEARCH_PIPELINE = [
  { key: 'downloading', label: '抓取下载', detail: '获取作品与视频' },
  { key: 'transcribing', label: '语音转录', detail: 'FunASR / Whisper' },
  { key: 'summarizing', label: 'AI 整理', detail: 'Agnes / Ollama 后备' },
  { key: 'publishing', label: '笔记发布', detail: 'Markdown / HTML' },
  { key: 'pushing', label: '飞书通知', detail: '完成后发送' },
] as const;

export function taskStatusLabel(status: ResearchTask['status']) {
  if (status === 'processing') return '进行中';
  if (status === 'queued') return '排队中';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败待处理';
  return '已暂停';
}

export function taskStatusClass(status: ResearchTask['status']) {
  if (status === 'processing') return 'border-blue-100 bg-blue-50 text-blue-700 dark:border-[var(--info-border)] dark:bg-[var(--info-bg)] dark:text-[var(--info)]';
  if (status === 'queued') return 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-secondary)]';
  if (status === 'completed') return 'border-emerald-100 bg-emerald-50 text-emerald-700 dark:border-[var(--success-border)] dark:bg-[var(--success-bg)] dark:text-[var(--success)]';
  if (status === 'failed') return 'border-red-100 bg-red-50 text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]';
  return 'border-amber-100 bg-amber-50 text-amber-700 dark:border-[var(--warning-border)] dark:bg-[var(--warning-bg)] dark:text-[var(--warning)]';
}

export function stageLabel(stage?: ResearchTask['pipeline_stage']) {
  if (stage === 'downloading') return '正在抓取下载';
  if (stage === 'transcribing') return '正在语音转录';
  if (stage === 'summarizing') return '正在生成笔记';
  if (stage === 'pushing') return '正在发布与通知';
  if (stage === 'completed') return '全部流程完成';
  if (stage === 'failed') return '流程执行失败';
  return '等待进入处理队列';
}

function activeStageIndex(task: ResearchTask) {
  if (task.status === 'completed') return RESEARCH_PIPELINE.length;
  if (task.status === 'queued') return -1;
  if (task.pipeline_stage === 'downloading') return 0;
  if (task.pipeline_stage === 'transcribing') return 1;
  if (task.pipeline_stage === 'summarizing') return 2;
  if (task.pipeline_stage === 'pushing') return 4;
  return Math.min(RESEARCH_PIPELINE.length - 1, Math.max(0, Math.floor((task.pipeline_progress || 0) / 20)));
}

export function TaskProgressRail({ task, compact = false }: { task: ResearchTask; compact?: boolean }) {
  const activeIndex = activeStageIndex(task);

  return (
    <div className="grid grid-cols-5 gap-1.5" aria-label={`任务进度：${stageLabel(task.pipeline_stage)}`}>
      {RESEARCH_PIPELINE.map((stage, index) => {
        const complete = task.status === 'completed' || index < activeIndex;
        const active = task.status === 'processing' && index === activeIndex;
        const failed = task.status === 'failed' && index === activeIndex;
        return (
          <div key={stage.key} className="min-w-0">
            <div className="flex items-center">
              <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${
                complete ? 'border-emerald-500 bg-emerald-500 text-white dark:border-[var(--success)] dark:bg-[var(--success)]' :
                active ? 'border-blue-500 bg-blue-50 text-blue-700 dark:border-[var(--info)] dark:bg-[var(--info-bg)] dark:text-[var(--info)]' :
                failed ? 'border-red-500 bg-red-50 text-red-700 dark:border-[var(--danger)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]' :
                'border-zinc-200 bg-white text-zinc-400 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-muted)]'
              }`}>
                {complete ? <Check className="h-3.5 w-3.5" /> :
                  active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> :
                  failed ? <X className="h-3.5 w-3.5" /> :
                  <Circle className="h-2.5 w-2.5" />}
              </span>
              {index < RESEARCH_PIPELINE.length - 1 && (
                <span className={`h-px min-w-0 flex-1 ${index < activeIndex ? 'bg-emerald-300 dark:bg-[var(--success)]' : 'bg-zinc-200 dark:bg-[var(--surface-border)]'}`} />
              )}
            </div>
            <div className={`mt-1.5 truncate font-medium ${compact ? 'text-[10px]' : 'text-[11px]'} ${
              active ? 'text-blue-700 dark:text-[var(--info)]' : failed ? 'text-red-700 dark:text-[var(--danger)]' : complete ? 'text-emerald-700 dark:text-[var(--success)]' : 'text-zinc-500 dark:text-[var(--text-muted)]'
            }`}>{stage.label}</div>
            {!compact && <div className="mt-0.5 hidden truncate text-[9px] text-zinc-400 md:block">{stage.detail}</div>}
          </div>
        );
      })}
    </div>
  );
}

export function TaskStageCounts({ stages }: { stages: NonNullable<ResearchTask['pipeline_stages']> }) {
  const items = [
    { key: 'downloading', label: '下载', value: stages.downloading, icon: Download, tone: 'text-blue-700' },
    { key: 'transcribing', label: '转录', value: stages.transcribing, icon: Waves, tone: 'text-violet-700' },
    { key: 'ai', label: 'AI 与笔记', value: stages.ai, icon: Sparkles, tone: 'text-amber-700' },
    { key: 'done', label: '完成', value: stages.done, icon: CheckCircle2, tone: 'text-emerald-700' },
    { key: 'failed', label: '失败', value: stages.failed, icon: AlertTriangle, tone: stages.failed > 0 ? 'text-red-700' : 'text-zinc-500' },
  ];

  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-200 dark:bg-[var(--surface-border)] sm:grid-cols-5">
      {items.map(item => {
        const Icon = item.icon;
        return (
          <div key={item.key} className="bg-white dark:bg-[var(--surface)] px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-[11px] text-zinc-500 dark:text-[var(--text-secondary)]">
              <Icon className="h-3.5 w-3.5" />
              <span>{item.label}</span>
            </div>
            <div className={`mt-1 font-mono text-lg font-semibold tabular-nums ${item.tone}`}>{item.value}</div>
          </div>
        );
      })}
    </div>
  );
}

export function TaskProgressBar({ task }: { task: ResearchTask }) {
  const progress = Math.max(0, Math.min(100, Number(task.pipeline_progress || 0)));
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3 text-xs">
        <span className="font-medium text-zinc-700">{stageLabel(task.pipeline_stage)}</span>
        <span className="font-mono tabular-nums text-zinc-500 dark:text-[var(--text-secondary)]">{progress}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-[var(--surface-border)]">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            task.status === 'completed' ? 'bg-emerald-500' :
            task.status === 'failed' ? 'bg-red-500' :
            task.status === 'paused' ? 'bg-amber-500' : 'bg-blue-600'
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  );
}
