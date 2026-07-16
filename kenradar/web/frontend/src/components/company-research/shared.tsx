/**
 * Shared utilities and components for the Company Research workspace.
 * @license Apache-2.0
 */
import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// ─── API helper ───────────────────────────────────────────────

export async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || `请求失败: ${response.status}`);
  }
  return payload as T;
}

// ─── Date helpers ─────────────────────────────────────────────

export const today = new Date();
export const threeYearsAgo = new Date(today.getTime() - 365 * 3 * 24 * 60 * 60 * 1000);
export const isoDate = (date: Date) => date.toISOString().slice(0, 10);

// ─── Status badge class ───────────────────────────────────────

export const statusClass = (status: string) => {
  if (['completed', 'saved', 'downloaded', 'deleted'].includes(status)) return 'border-emerald-200 dark:border-[var(--success-border)] bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-700 dark:text-[var(--success)]';
  if (['failed', 'partial_failed', 'invalid_pdf', 'delete_failed'].includes(status)) return 'border-red-200 dark:border-[var(--danger-border)] bg-red-50 dark:bg-[var(--danger-bg)] text-red-700 dark:text-[var(--danger)]';
  if (['asking', 'uploading', 'downloading', 'running'].includes(status)) return 'border-blue-200 dark:border-[var(--info-border)] bg-blue-50 dark:bg-[var(--info-bg)] text-blue-700 dark:text-[var(--info)]';
  return 'border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] text-zinc-600 dark:text-[var(--text-secondary)]';
};

// ─── Stage helpers (general research) ────────────────────────

export const STAGE_LABELS: Record<string, string> = {
  created: '已创建',
  fetch_notice_index: '获取公告索引',
  fetch_stock_info: '获取股票信息',
  download_pdfs_by_akshare: '下载 PDF',
  fallback_download_by_a_stock_data: '备用源下载',
  validate_pdfs: '校验 PDF',
  create_notebook: '创建 Notebook',
  upload_pdfs: '上传 PDF',
  wait_sources_ready: '等待 Source 就绪',
};

export const STAGE_ICONS: Record<string, string> = {
  fetch_notice_index: '📋',
  download_pdfs_by_akshare: '⬇️',
  create_notebook: '📓',
  upload_pdfs: '☁️',
  wait_sources_ready: '⏳',
};

export function getStageLabel(stage: string): string {
  if (STAGE_LABELS[stage]) return STAGE_LABELS[stage];
  if (stage.startsWith('ask_question')) return `逐题问答 (${stage.replace('ask_question_', '问题 ')})`;
  if (stage === 'ask_questions') return '逐题问答';
  if (stage === 'verify_answers') return '验证答案';
  if (stage === 'delete_notebook') return '删除 Notebook';
  if (stage === 'downloaded') return '下载完成';
  if (stage === 'uploaded') return '上传完成';
  if (stage === 'completed') return '完成';
  return stage;
}

export function getStageIndex(stage: string): number {
  const order = [
    'fetch_notice_index', 'download_pdfs_by_akshare', 'create_notebook',
    'upload_pdfs', 'wait_sources_ready',
  ];
  if (stage.startsWith('ask_question')) return 5;
  if (stage === 'verify_answers') return 6;
  if (stage === 'delete_notebook') return 7;
  const idx = order.indexOf(stage);
  return idx >= 0 ? idx : 0;
}

export function isTerminalStatus(status: string): boolean {
  return ['completed', 'failed', 'partial_failed', 'completed_with_delete_pending'].includes(status);
}

export const STAGE_PIPELINE = [
  { key: 'fetch_notice_index', label: '获取公告索引', icon: '📋' },
  { key: 'download_pdfs_by_akshare', label: '下载PDF', icon: '⬇️' },
  { key: 'create_notebook', label: '创建Notebook', icon: '📓' },
  { key: 'upload_pdfs', label: '上传PDF', icon: '☁️' },
  { key: 'wait_sources_ready', label: '等待就绪', icon: '⏳' },
  { key: 'ask', label: '逐题问答', icon: '💬' },
  { key: 'delete_notebook', label: '删除Notebook', icon: '🗑️' },
];

// ─── Types ───────────────────────────────────────────────────

export type PreviewStock = { symbol: string; name: string };

export interface FinJob {
  id: number; symbol: string; stock_name: string; status: string;
  current_stage: string; selected_pdf_count: number;
  uploaded_source_count: number; ready_source_count: number;
  question_answered: number; question_saved: number;
  financial_risk_score: number | null; financial_risk_tier: string;
  notebook_deleted: boolean; last_error: string;
  created_at: string; updated_at: string;
  queued?: boolean; task_run_id?: number; queue_position?: number;
}

export interface FinReportFile {
  id?: number; report_year: number; report_period: string;
  report_period_end: string; report_type: string;
  notice_title: string; notice_date: string; found: boolean;
  pdf_status: string; upload_status: string;
  file_path?: string; download_error?: string; upload_error?: string;
}

export interface FinAnswer {
  question_index: number; question_key: string; question_title: string;
  answer_markdown: string; raw_answer: string; status: string;
  error_message: string; created_at: string; saved_at: string;
}

export interface FinReport {
  report_markdown: string; parsed_json: Record<string, unknown>;
  financial_risk_score: number; financial_risk_tier: string;
  first_repayment_source: string; leasing_advice: string;
  parse_success: boolean; score_source: string; created_at: string;
}

export interface FinRedFlag {
  id: number; flag_type: string; flag_name: string; risk_level: string;
  evidence: string; annual_report_explanation: string;
  explanation_sufficient: boolean; leasing_due_diligence_impact: string;
}

// ─── Common components ───────────────────────────────────────

export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-1.5 text-sm font-medium dark:text-[var(--text-primary)]">
      <span>{label}</span>
      {children}
    </label>
  );
}

export function StatusItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 py-3">
      <div className="text-xs dark:text-[var(--text-muted)]">{label}</div>
      <div className={`mt-1 text-sm font-medium dark:text-[var(--text-primary)] ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  );
}

export function StatCard({ label, value, mono = false, badge }: { label: string; value: string | number; mono?: boolean; badge?: string }) {
  return (
    <div className="rounded border border-zinc-100 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-3 py-3">
      <div className="text-xs dark:text-[var(--text-muted)]">{label}</div>
      <div className={`mt-1 flex items-center gap-2 text-sm font-medium dark:text-[var(--text-primary)] ${mono ? 'font-mono' : ''}`}>
        {String(value)}
        {badge && <span className={`rounded border px-1.5 py-0.5 text-xs font-semibold ${statusClass(badge)}`}>{badge}</span>}
      </div>
    </div>
  );
}

export function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert
      [&_h1]:mt-5 [&_h1]:mb-2
      [&_h2]:mt-4 [&_h2]:mb-1.5
      [&_h3]:mt-3 [&_h3]:mb-1
      [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-1.5
      [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-1.5
      [&_li]:my-0.5
      [&_table]:w-full [&_table]:border-collapse [&_table]:my-2
      [&_th]:border [&_th]:border-zinc-200 dark:[&_th]:border-[var(--surface-border)] [&_th]:bg-zinc-50 dark:[&_th]:bg-[var(--surface-muted)]
      [&_th]:px-3 [&_th]:py-1.5 [&_th]:text-xs [&_th]:font-semibold
      [&_td]:border [&_td]:border-zinc-200 dark:[&_td]:border-[var(--surface-border)] [&_td]:px-3 [&_td]:py-1.5 [&_td]:text-xs
      [&_code]:rounded [&_code]:bg-zinc-100 dark:[&_code]:bg-[var(--surface-muted)] [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-xs [&_code]:font-mono
      [&_pre]:my-2 [&_pre]:rounded [&_pre]:bg-zinc-900 [&_pre]:p-3 [&_pre]:text-xs [&_pre]:text-zinc-100
      [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-zinc-100
      [&_p]:my-1 [&_strong]:font-semibold
      [&_hr]:my-4 [&_hr]:border-zinc-200 dark:[&_hr]:border-[var(--surface-border)]"
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function groupJobsByBatch(jobs: any[]): [string, any[]][] {
  const map = new Map<string, any[]>();
  for (const job of jobs) {
    const key = job.batch_id || 'legacy';
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(job);
  }
  return Array.from(map.entries());
}
