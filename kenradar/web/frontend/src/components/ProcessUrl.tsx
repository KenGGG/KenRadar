/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 *
 * V2 M4 unified single-link processing page. Accepts any douyin or xiaoyuzhou
 * link, enqueues a `process_url` task, and polls the queue until done.
 */

import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link2, Loader2, CheckCircle2, XCircle } from 'lucide-react';

type TaskRow = {
  results?: { title: string; url: string }[];
  id: number;
  task_type: string;
  status: string;
  message: string;
  priority: number;
  attempt: number;
  max_attempts: number;
  error_code: string | null;
  created_at: string;
  updated_at: string;
};

const SUPPORTED_HINTS = [
  'https://www.douyin.com/video/...',
  'https://v.douyin.com/AbCdEf/',
  'https://www.douyin.com/user/...',
  'https://www.xiaoyuzhoufm.com/episode/...',
  'https://www.xiaoyuzhoufm.com/podcast/...',
];

function isSupportedUrl(url: string): boolean {
  const host = (() => {
    try {
      return new URL(url).host.toLowerCase();
    } catch {
      return '';
    }
  })();
  return ['douyin.com', 'iesdouyin.com', 'xiaoyuzhoufm.com'].some(domain => host === domain || host.endsWith('.' + domain));
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || `请求失败: ${response.status}`);
  }
  return payload as T;
}

export default function ProcessUrl() {
  const [url, setUrl] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const queue = useQuery({queryKey:['process-url-tasks'],queryFn:() => requestJson<{tasks:TaskRow[]}>('/api/tasks?task_type=process_url&limit=12'),refetchInterval:() => document.hidden ? 30000 : 3000,refetchIntervalInBackground:false});
  const tasks = queue.data?.tasks || [];

  const submit = async () => {
    setError(null);
    const trimmed = url.trim();
    if (!trimmed) {
      setError('请输入待处理的链接');
      return;
    }
    if (!isSupportedUrl(trimmed)) {
      setError('仅支持抖音或小宇宙链接');
      return;
    }
    setSubmitting(true);
    try {
      await requestJson<{ task_id: number; message: string }>('/api/content/process-url', {
        method: 'POST',
        body: JSON.stringify({ url: trimmed, push: false, force: false }),
      });
      setUrl('');
      await queue.refetch();
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const statusBadge = (status: string) => {
    const map: Record<string, string> = {
      queued: 'bg-zinc-100 dark:bg-[var(--surface-muted)] text-zinc-600 dark:text-[var(--text-muted)]',
      running: 'bg-blue-100 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)]',
      retry_wait: 'bg-amber-100 dark:bg-[var(--warn-bg)] text-amber-700 dark:text-[var(--warn)]',
      paused: 'bg-purple-100 text-purple-700',
      success: 'bg-emerald-100 dark:bg-[var(--success-bg)] text-emerald-700 dark:text-[var(--success)]',
      failed: 'bg-red-100 dark:bg-[var(--danger-bg)] text-red-700 dark:text-[var(--danger)]',
      cancelled: 'bg-zinc-200 text-zinc-700',
    };
    return map[status] || 'bg-zinc-100 text-zinc-600';
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <Link2 className="w-5 h-5 text-blue-600 dark:text-[var(--accent)]" />
          处理链接
        </h1>
        <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
          粘贴任意抖音或小宇宙链接，系统会按来源平台自动选择连接器并处理（抓取 / 转录 / AI 整理 / 笔记 / 发布）。
        </p>
      </div>

      <div
        className="rounded-xl p-5 space-y-3"
        style={{ backgroundColor: 'var(--surface)', border: '1px solid var(--surface-border)' }}
      >
        <textarea
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder={SUPPORTED_HINTS[0]}
          rows={3}
          className="w-full rounded-lg p-3 text-sm font-mono outline-none"
          style={{ backgroundColor: 'var(--surface-muted)', border: '1px solid var(--surface-border)', color: 'var(--text-primary)' }}
        />
        <div className="flex items-center justify-between">
          <div className="flex flex-wrap gap-1.5">
            {SUPPORTED_HINTS.map(h => (
              <span key={h} className="text-[10px] font-mono px-1.5 py-0.5 rounded" style={{ backgroundColor: 'var(--surface-muted)', color: 'var(--text-muted)' }}>
                {h}
              </span>
            ))}
          </div>
          <button
            id="process_url_submit"
            onClick={submit}
            disabled={submitting}
            className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Link2 className="w-4 h-4" />}
            提交处理
          </button>
        </div>
        {error && (
          <div className="flex items-center gap-2 text-xs text-red-600 dark:text-[var(--danger)]">
            <XCircle className="w-4 h-4" /> {error}
          </div>
        )}
      </div>

      <div
        className="rounded-xl p-5"
        style={{ backgroundColor: 'var(--surface)', border: '1px solid var(--surface-border)' }}
      >
        <h2 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-secondary)' }}>最近处理队列</h2>
        <p className="text-xs mb-3" style={{ color: 'var(--text-secondary)' }}>完成后点击「查看结果」阅读笔记，也可前往 <a className="text-blue-600 underline" href="/archive/notes">内容归档</a> 查看全部笔记。</p>
        {queue.isError && <p role="alert">队列读取失败：{queue.error.message} <button onClick={() => queue.refetch()}>重试</button></p>}
        {queue.isPending ? <p role="status">正在读取任务…</p> : tasks.length === 0 && !queue.isError ? (
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>暂无处理任务。</p>
        ) : (
          <ul className="space-y-2">
            {tasks.map(t => (
              <li key={t.id} className="flex items-center justify-between text-sm" style={{ borderBottom: '1px solid var(--surface-border)' }}>
                <div className="flex items-center gap-2 py-2 min-w-0">
                  {t.status === 'success' ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-[var(--success)]" />
                  ) : t.status === 'failed' ? (
                    <XCircle className="w-4 h-4 text-red-600 dark:text-[var(--danger)]" />
                  ) : (
                    <Loader2 className="w-4 h-4 animate-spin text-blue-600 dark:text-[var(--accent)]" />
                  )}
                  <div className="min-w-0">
                    <span className="block truncate font-mono text-xs" style={{ color: 'var(--text-primary)' }}>{t.message}</span>
                    {t.status === 'success' && (
                      <div className="mt-1 flex flex-col gap-1">
                        {t.results?.length ? t.results.map(result => (
                          <a key={result.url} href={result.url} className="text-xs text-blue-600 hover:underline">
                            查看结果：{result.title}
                          </a>
                        )) : <a href="/archive/notes" className="text-xs text-blue-600 hover:underline">前往内容归档查看</a>}
                      </div>
                    )}
                  </div>
                </div>
                <span className={`text-[10px] font-mono px-2 py-0.5 rounded-full font-bold ${statusBadge(t.status)}`}>
                  {t.status}{t.attempt > 1 ? ` · retry ${t.attempt}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
