/**
 * 财务分析 MVP — 基于 3 份年报 + 1 份最新定期报告的财务分析工具。
 * @license Apache-2.0
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AlertCircle, Book, ChevronDown, ChevronRight, FileText, Play,
  RefreshCw,
} from 'lucide-react';

// ─── types ───────────────────────────────────────────────────

interface FinJob {
  id: number;
  symbol: string;
  stock_name: string;
  status: string;
  current_stage: string;
  queued?: boolean;
  task_run_id?: number;
  queue_position?: number;
  selected_pdf_count: number;
  uploaded_source_count: number;
  ready_source_count: number;
  question_answered: number;
  question_saved: number;
  financial_risk_score: number | null;
  financial_risk_tier: string;
  notebook_deleted: boolean;
  last_error: string;
  created_at: string;
  updated_at: string;
}

interface FinReportFile {
  id?: number;
  report_year: number;
  report_period: string;
  report_period_end: string;
  report_type: string;
  notice_title: string;
  notice_date: string;
  found: boolean;
  pdf_status: string;
  upload_status: string;
  file_path?: string;
  download_error?: string;
  upload_error?: string;
}

interface FinAnswer {
  question_index: number;
  question_key: string;
  question_title: string;
  answer_markdown: string;
  raw_answer: string;
  status: string;
  error_message: string;
  created_at: string;
  saved_at: string;
}

interface FinReport {
  report_markdown: string;
  parsed_json: Record<string, unknown>;
  financial_risk_score: number;
  financial_risk_tier: string;
  first_repayment_source: string;
  leasing_advice: string;
  parse_success: boolean;
  score_source: string;
  created_at: string;
}

interface FinRedFlag {
  id: number;
  flag_type: string;
  flag_name: string;
  risk_level: string;
  evidence: string;
  annual_report_explanation: string;
  explanation_sufficient: boolean;
  leasing_due_diligence_impact: string;
}

interface FinTaskRun {
  id: number;
  task_type: string;
  status: string;
  progress_json: Record<string, unknown>;
  stats_json: Record<string, unknown>;
  started_at: string;
  finished_at: string;
  last_error: string;
  cancel_requested_at: string;
  created_at: string;
}

// ─── helpers ──────────────────────────────────────────────────

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
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

function badgeClass(status: string) {
  if (['completed', 'saved', 'downloaded', 'deleted'].includes(status)) return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-[var(--success-border)] dark:bg-[var(--success-bg)] dark:text-[var(--success)]';
  if (['failed', 'partial_failed', 'invalid_pdf'].includes(status)) return 'border-red-200 bg-red-50 text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]';
  if (['asking', 'uploading', 'downloading', 'running', 'queued'].includes(status)) return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-[var(--info-border)] dark:bg-[var(--info-bg)] dark:text-[var(--info)]';
  return 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] dark:text-[var(--text-secondary)]';
}

const STAGE_LABEL: Record<string, string> = {
  created: '已创建',
  queued: '排队中',
  running: '执行中',
  select_report_files: '选择报告',
  download_pdfs: '下载PDF',
  create_notebook: '创建Notebook',
  upload_sources: '上传PDF',
  wait_sources_ready: '等待就绪',
  delete_local_pdfs: '删除本地PDF',
  ask_q1: 'Q1 审计意见',
  ask_q2: 'Q2 财务数据',
  ask_q3: 'Q3 盈利能力',
  ask_q4: 'Q4 收入回款',
  ask_q5: 'Q5 资产质量',
  ask_q6: 'Q6 债务流动性',
  ask_q7: 'Q7 现金流',
  ask_q8: 'Q8 关联交易',
  ask_q9: 'Q9 数据校验',
  ask_q10: 'Q10 风险评分',
  ask_q11_final_report: 'Q11 最终报告',
  parse_json: '解析JSON',
  save_red_flags: '保存红旗',
  save_score: '保存评分',
  delete_notebook: '删除Notebook',
  completed: '完成',
};

function stageLabel(stage: string): string {
  return STAGE_LABEL[stage] || stage;
}

function shortText(value: string | null | undefined, max = 90): string {
  const text = String(value || '').trim();
  if (!text) return '';
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

// ─── Exported sub-components for Workspace integration ───────

/** Props-driven launcher panel (no internal API calls). */
export function FinAnalysisLauncher({
  symbol, onSymbolChange,
  analysisBaseYear, onAnalysisBaseYearChange,
  autoDelete, onAutoDeleteChange,
  onPreview, onStart, onRefresh,
  previewResult,
  error, message,
}: {
  symbol: string;
  onSymbolChange: (v: string) => void;
  analysisBaseYear?: number;
  onAnalysisBaseYearChange?: (v: number) => void;
  autoDelete: boolean;
  onAutoDeleteChange: (v: boolean) => void;
  onPreview: () => void;
  onStart: () => void;
  onRefresh: () => void;
  previewResult: { selected_reports: FinReportFile[]; missing_reports: string[]; total_selected: number } | null;
  error?: string;
  message?: string;
}) {
  const [expandedPreview, setExpandedPreview] = useState(false);
  const baseYear = analysisBaseYear ?? new Date().getFullYear();
  return (
    <div className="space-y-3">
      {(error || message) && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]' : 'border-blue-200 bg-blue-50 text-blue-700 dark:border-[var(--info-border)] dark:bg-[var(--info-bg)] dark:text-[var(--info)]'}`}>
          {error || message}
        </div>
      )}
      <div className="grid gap-3 rounded-lg border border-zinc-200 bg-white p-4 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] md:grid-cols-4">
        <div className="space-y-1.5 text-sm font-medium text-zinc-700 dark:text-[var(--text-primary)]">
          <span>股票代码</span>
          <input value={symbol} onChange={e => onSymbolChange(e.target.value)}
            className="input h-9 w-full rounded border border-zinc-200 px-3 text-sm outline-none focus:border-blue-400 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-primary)] dark:focus:border-blue-400" />
        </div>
        <div className="space-y-1.5 text-sm font-medium text-zinc-700 dark:text-[var(--text-primary)]">
          <span>分析基准年份</span>
          <input type="number" value={baseYear}
            onChange={e => onAnalysisBaseYearChange?.(Number(e.target.value) || new Date().getFullYear())}
            className="input h-9 w-full rounded border border-zinc-200 px-3 text-sm outline-none focus:border-blue-400 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-primary)] dark:focus:border-blue-400" />
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-[var(--text-primary)]">
            <input type="checkbox" checked={autoDelete} onChange={e => onAutoDeleteChange(e.target.checked)}
              className="h-4 w-4 rounded border-zinc-300 dark:border-[var(--surface-border)] dark:bg-[var(--surface)]" />
            完成后删除 NotebookLM
          </label>
        </div>
        <div className="flex items-end gap-2">
          <button onClick={onPreview} className="inline-flex h-9 items-center gap-1.5 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-primary)] dark:hover:bg-[var(--surface-muted)]"><FileText className="h-4 w-4" />预览</button>
          <button onClick={onStart} className="inline-flex h-9 items-center gap-1.5 rounded bg-zinc-900 px-3 text-sm font-semibold text-white hover:bg-zinc-800 dark:bg-[var(--surface-border)] dark:hover:bg-zinc-700"><Play className="h-4 w-4" />开始执行</button>
          <button onClick={onRefresh} className="inline-flex h-9 items-center gap-1.5 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-primary)] dark:hover:bg-[var(--surface-muted)]"><RefreshCw className="h-4 w-4" />刷新</button>
        </div>
      </div>
      {previewResult && (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
          <button onClick={() => setExpandedPreview(!expandedPreview)}
            className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <FileText className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />报告文件预览
              <span className="rounded border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs font-normal text-zinc-500 dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">{previewResult.total_selected} 份</span>
            </div>
            {expandedPreview ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
          </button>
          {expandedPreview && (
            <div className="overflow-x-auto border-t border-zinc-100 dark:border-[var(--surface-border)]">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-50 text-xs text-zinc-500 dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">
                  <tr><th className="px-4 py-2 font-semibold">类型</th><th className="px-4 py-2 font-semibold">年份</th><th className="px-4 py-2 font-semibold">截止日</th><th className="px-4 py-2 font-semibold">公告标题</th><th className="px-4 py-2 font-semibold">状态</th></tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {previewResult.selected_reports.map((r, i) => (
                    <tr key={i}>
                      <td className="px-4 py-2 dark:text-[var(--text-primary)]">{r.report_type === 'annual_report' ? '年报' : r.report_type === 'semi_annual_report' ? '半年报' : '季报'}</td>
                      <td className="px-4 py-2 dark:text-[var(--text-primary)]">{r.report_year}</td>
                      <td className="px-4 py-2 font-mono text-xs dark:text-[var(--text-secondary)]">{r.report_period_end || '-'}</td>
                      <td className="px-4 py-2 dark:text-[var(--text-primary)]">{r.notice_title}</td>
                      <td className="px-4 py-2"><span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:border-[var(--success-border)] dark:bg-[var(--success-bg)] dark:text-[var(--success)]">已选中</span></td>
                    </tr>
                  ))}
                  {previewResult.missing_reports.map((mr, i) => (
                    <tr key={`miss-${i}`}>
                      <td className="px-4 py-2" colSpan={4}><span className="text-red-500 dark:text-[var(--danger)]">⚠️ {mr}</span></td>
                      <td className="px-4 py-2"><span className="rounded border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]">缺失</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Props-driven job list table. */
export function FinAnalysisJobList({
  jobs,
  onSelectJob,
  selectedJobId,
}: {
  jobs: FinJob[];
  onSelectJob?: (jobId: number) => void;
  selectedJobId?: number | null;
}) {
  if (jobs.length === 0) return <p className="text-sm text-zinc-400 py-3 dark:text-[var(--text-muted)]">暂无财务分析任务</p>;
  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
      <table className="w-full text-left text-sm">
        <thead className="bg-zinc-50 text-xs text-zinc-500 dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">
          <tr><th className="px-3 py-2 font-semibold">股票</th><th className="px-3 py-2 font-semibold">状态</th><th className="px-3 py-2 font-semibold">阶段</th><th className="px-3 py-2 font-semibold">PDF</th><th className="px-3 py-2 font-semibold">问答</th><th className="px-3 py-2 font-semibold">评分</th><th className="px-3 py-2 font-semibold">错误</th><th className="px-3 py-2 font-semibold">操作</th></tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
          {jobs.map(job => (
            <tr key={job.id} className={`${selectedJobId === job.id ? 'bg-blue-50 dark:bg-[var(--info-bg)]' : ''} dark:text-[var(--text-primary)]`}>
              <td className="px-3 py-2"><span className="font-mono font-semibold">{job.symbol}</span><span className="ml-1 text-xs text-zinc-500 dark:text-[var(--text-muted)]">{job.stock_name}</span></td>
              <td className="px-3 py-2"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${badgeClass(job.status)}`}>{job.status}</span></td>
              <td className="px-3 py-2 text-xs text-zinc-500 dark:text-[var(--text-muted)]">{stageLabel(job.current_stage || job.status)}</td>
              <td className="px-3 py-2 text-xs dark:text-[var(--text-primary)]">{job.selected_pdf_count}/{job.ready_source_count}</td>
              <td className="px-3 py-2 text-xs dark:text-[var(--text-primary)]">{job.question_saved}/11</td>
              <td className="px-3 py-2 text-xs dark:text-[var(--text-primary)]">{job.financial_risk_score !== null ? `${job.financial_risk_score} ${job.financial_risk_tier || ''}` : '-'}</td>
              <td className="max-w-[260px] truncate px-3 py-2 text-xs text-red-600 dark:text-[var(--danger)]" title={job.last_error || ''}>{shortText(job.last_error, 70) || '-'}</td>
              <td className="px-3 py-2">
                {onSelectJob && (
                  <button onClick={() => onSelectJob(job.id)}
                    className="rounded border border-zinc-200 px-2 py-0.5 text-xs font-semibold hover:bg-zinc-50 dark:border-[var(--surface-border)] dark:bg-[var(--surface)] dark:text-[var(--text-primary)] dark:hover:bg-[var(--surface-muted)]">查看</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** FinScoreCard — named export for the score card component. */
export { ScoreCard as FinScoreCard };

// ─── ScoreCard sub-component ──────────────────────────────────

const DIMENSIONS = [
  { key: 'revenue_quality', label: '收入与回款质量', max: 15 },
  { key: 'profit_quality', label: '利润质量', max: 15 },
  { key: 'cashflow_quality', label: '现金流质量', max: 20 },
  { key: 'asset_quality', label: '资产质量', max: 15 },
  { key: 'debt_liquidity', label: '债务与流动性', max: 15 },
  { key: 'related_party_funds', label: '关联交易和资金占用', max: 10 },
  { key: 'audit_internal_control', label: '审计内控', max: 10 },
];

function ScoreCard({ parsedJson, score, tier, source, repayment, advice }: {
  parsedJson: Record<string, unknown> | null;
  score: number | null;
  tier: string | null;
  source: string | null;
  repayment: string | null;
  advice: string | null;
}) {
  const detail = (parsedJson as any)?.score_detail || {};
  const tierDesc = tier === 'A' ? '财务质量较好' : tier === 'B' ? '存在一般性波动' : tier === 'C' ? '存在若干风险信号' : tier === 'D' ? '存在重大财务隐患' : tier === 'E' ? '存在严重财务真实性疑点' : '-';
  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
      <h3 className="mb-3 text-sm font-semibold dark:text-[var(--text-primary)]">财务风险评分</h3>
      <div className="overflow-x-auto mb-3">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-50 text-xs text-zinc-500 dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">
            <tr><th className="px-3 py-2 font-semibold">评分维度</th><th className="px-3 py-2 font-semibold">满分</th><th className="px-3 py-2 font-semibold">得分</th><th className="px-3 py-2 font-semibold">需复核</th></tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
            {DIMENSIONS.map(dim => {
              const d = detail[dim.key] || {};
              return (
                <tr key={dim.key}>
                  <td className="px-3 py-2 text-zinc-700 dark:text-[var(--text-primary)]">{dim.label}</td>
                  <td className="px-3 py-2 text-zinc-500 dark:text-[var(--text-muted)]">{dim.max}</td>
                  <td className="px-3 py-2 font-mono font-semibold dark:text-[var(--text-primary)]">{d.score ?? '-'}</td>
                  <td className="px-3 py-2 dark:text-[var(--text-primary)]">{d.review_required ? '⚠️ 是' : '否'}</td>
                </tr>
              );
            })}
            <tr className="bg-zinc-50 font-semibold dark:bg-[var(--surface-muted)]">
              <td className="px-3 py-2 dark:text-[var(--text-primary)]">合计</td><td className="px-3 py-2 dark:text-[var(--text-primary)]">100</td>
              <td className="px-3 py-2 font-mono dark:text-[var(--text-primary)]">{score ?? '-'}</td><td className="px-3 py-2" />
            </tr>
          </tbody>
        </table>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs text-zinc-600 dark:text-[var(--text-secondary)]">
        <div className="rounded bg-zinc-50 px-3 py-2 dark:bg-[var(--surface-muted)]"><span className="text-zinc-400 dark:text-[var(--text-muted)]">风险层级</span><br /><span className="font-semibold dark:text-[var(--text-primary)]">{tier || '-'} {tierDesc}</span></div>
        <div className="rounded bg-zinc-50 px-3 py-2 dark:bg-[var(--surface-muted)]"><span className="text-zinc-400 dark:text-[var(--text-muted)]">评分来源</span><br /><span className="font-semibold dark:text-[var(--text-primary)]">{source === 'ai_generated' ? 'AI 生成' : source === 'fallback' ? '兜底计算' : '-'}</span></div>
        <div className="rounded bg-zinc-50 px-3 py-2 dark:bg-[var(--surface-muted)]"><span className="text-zinc-400 dark:text-[var(--text-muted)]">第一还款来源</span><br /><span className="font-semibold dark:text-[var(--text-primary)]">{repayment || '-'}</span></div>
        <div className="rounded bg-zinc-50 px-3 py-2 dark:bg-[var(--surface-muted)]"><span className="text-zinc-400 dark:text-[var(--text-muted)]">融资租赁建议</span><br /><span className="font-semibold dark:text-[var(--text-primary)]">{advice || '-'}</span></div>
      </div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────

export default function CompanyFinancialAnalysisMVP() {
  const [symbol, setSymbol] = useState('300750.SZ');
  const [analysisBaseYear, setAnalysisBaseYear] = useState(new Date().getFullYear());
  const [autoDelete, setAutoDelete] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const [preview, setPreview] = useState<{ selected_reports: FinReportFile[]; missing_reports: string[]; total_selected: number } | null>(null);
  const [jobs, setJobs] = useState<FinJob[]>([]);
  const [selectedJob, setSelectedJob] = useState<FinJob | null>(null);
  const [answers, setAnswers] = useState<FinAnswer[]>([]);
  const [report, setReport] = useState<FinReport | null>(null);
  const [redFlags, setRedFlags] = useState<FinRedFlag[]>([]);
  const [reportFiles, setReportFiles] = useState<FinReportFile[]>([]);
  const [taskRuns, setTaskRuns] = useState<FinTaskRun[]>([]);
  const [expandedSection, setExpandedSection] = useState<string | null>('preview');
  const autoRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedJobIsActive = Boolean(selectedJob && ['created', 'queued', 'running'].includes(selectedJob.status));
  const selectedJobHasError = Boolean(selectedJob && (selectedJob.status === 'failed' || selectedJob.status === 'partial_failed' || selectedJob.last_error));

  // Auto-refresh when job is running
  const runningJobs = jobs.filter(j => !['completed', 'failed', 'partial_failed'].includes(j.status));
  useEffect(() => {
    if (runningJobs.length === 0) {
      if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null; }
      return;
    }
    if (autoRef.current) return;
    autoRef.current = setInterval(() => {
      loadJobs().catch(() => undefined);
      if (selectedJob) loadJobDetail(selectedJob.id).catch(() => undefined);
    }, 3000);
    return () => { if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null; } };
  }, [runningJobs.length, selectedJob?.id]);

  const loadJobs = useCallback(async () => {
    const data = await requestJson<{ items: FinJob[] }>('/api/company-research/financial-analysis/jobs');
    setJobs(data.items || []);
  }, []);

  const loadJobDetail = useCallback(async (jobId: number, seedJob?: Partial<FinJob>) => {
    const data = await requestJson<{
      job: FinJob; report_files: FinReportFile[]; answers: FinAnswer[];
      report: FinReport | null; red_flags: FinRedFlag[]; task_runs: FinTaskRun[];
    }>(`/api/company-research/financial-analysis/jobs/${jobId}`);
    setSelectedJob({ ...data.job, ...seedJob });
    setReportFiles(data.report_files || []);
    setAnswers(data.answers || []);
    setReport(data.report || null);
    setRedFlags(data.red_flags || []);
    setTaskRuns(data.task_runs || []);
    if (data.report) {
      setExpandedSection('report');
    }
  }, []);

  const doPreview = async () => {
    setError(''); setMessage('');
    const data = await requestJson<{
      selected_reports: FinReportFile[]; missing_reports: string[];
      total_selected: number; stock_name: string;
    }>('/api/company-research/financial-analysis/preview', {
      method: 'POST',
      body: JSON.stringify({ symbol, analysis_base_year: analysisBaseYear }),
    });
    setPreview(data);
    setExpandedSection('preview');
    setMessage(`预览完成：找到 ${data.total_selected} 份报告${data.missing_reports.length ? `，缺失 ${data.missing_reports.join(', ')}` : ''}`);
  };

  const doStart = async () => {
    setError(''); setMessage('');
    const data = await requestJson<{ job: FinJob }>('/api/company-research/financial-analysis/tasks', {
      method: 'POST',
      body: JSON.stringify({ symbol, analysis_base_year: analysisBaseYear, auto_delete_notebook: autoDelete }),
    });
    const queueText = data.job.queue_position ? `，排队第 ${data.job.queue_position} 位` : (data.job.status === 'queued' || data.job.queued ? '，已加入队列' : '');
    const runText = data.job.task_run_id ? `，task_run=${data.job.task_run_id}` : '';
    setMessage(`任务已创建: job_id=${data.job.id}${runText}${queueText}`);
    setSelectedJob(data.job);
    setTaskRuns([]);
    setReportFiles([]);
    setAnswers([]);
    setReport(null);
    setRedFlags([]);
    await loadJobs();
    await loadJobDetail(data.job.id, data.job);
  };

  const toggleSection = (key: string) => {
    setExpandedSection(prev => prev === key ? null : key);
  };

  const withError = (fn: () => Promise<void>) => {
    fn().catch(exc => setError(exc.message || String(exc)));
  };

  return (
    <div className="space-y-4">
      {/* 任务配置 (复用子组件) */}
      <FinAnalysisLauncher
        symbol={symbol}
        onSymbolChange={setSymbol}
        analysisBaseYear={analysisBaseYear}
        onAnalysisBaseYearChange={setAnalysisBaseYear}
        autoDelete={autoDelete}
        onAutoDeleteChange={setAutoDelete}
        onPreview={() => withError(doPreview)}
        onStart={() => withError(doStart)}
        onRefresh={() => withError(loadJobs)}
        previewResult={preview}
        error={error}
        message={message}
      />

      {/* 任务列表 (复用子组件) */}
      <FinAnalysisJobList
        jobs={jobs}
        onSelectJob={(jobId) => withError(() => loadJobDetail(jobId))}
      />

      {/* 失败诊断 */}
      {selectedJob && (selectedJobIsActive || selectedJobHasError) && (
        <div className={`rounded-lg border p-4 text-sm ${
          selectedJobHasError
            ? 'border-red-200 bg-red-50 text-red-800 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]'
            : 'border-blue-200 bg-blue-50 text-blue-800 dark:border-[var(--info-border)] dark:bg-[var(--info-bg)] dark:text-[var(--info)]'
        }`}>
          <div className="flex items-center gap-2 font-semibold">
            <AlertCircle className="h-4 w-4" />
            {selectedJobHasError ? '失败诊断' : '任务进度'}
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            <div><span className={selectedJobHasError ? 'text-red-500 dark:text-[var(--danger)]' : 'text-blue-500 dark:text-[var(--info)]'}>任务</span><br /><span className="font-mono dark:text-[var(--text-primary)]">job_id={selectedJob.id}</span></div>
            <div><span className={selectedJobHasError ? 'text-red-500 dark:text-[var(--danger)]' : 'text-blue-500 dark:text-[var(--info)]'}>{selectedJobHasError ? '失败阶段' : '当前阶段'}</span><br /><span className="font-semibold dark:text-[var(--text-primary)]">{stageLabel(selectedJob.current_stage || selectedJob.status)}</span></div>
            <div><span className={selectedJobHasError ? 'text-red-500 dark:text-[var(--danger)]' : 'text-blue-500 dark:text-[var(--info)]'}>状态</span><br /><span className="font-semibold dark:text-[var(--text-primary)]">{selectedJob.status}</span></div>
          </div>
          {(selectedJob.task_run_id || selectedJob.queue_position || selectedJob.queued) && (
            <div className={`mt-2 grid gap-2 md:grid-cols-3 text-xs ${selectedJobHasError ? 'text-red-700 dark:text-[var(--danger)]' : 'text-blue-700 dark:text-[var(--info)]'}`}>
              <div className="dark:text-[var(--text-primary)]">task_run={selectedJob.task_run_id || '-'}</div>
              <div className="dark:text-[var(--text-primary)]">{selectedJob.queue_position ? `排队第 ${selectedJob.queue_position} 位` : (selectedJob.queued ? '已进入队列' : '等待调度')}</div>
              <div className="dark:text-[var(--text-primary)]">{selectedJob.status === 'running' ? 'worker 正在执行' : '等待 worker 领取'}</div>
            </div>
          )}
          {selectedJobHasError && (
            <pre className="mt-3 max-h-36 overflow-auto whitespace-pre-wrap rounded border border-red-100 bg-white p-3 text-xs text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--surface)] dark:text-[var(--danger)]">{selectedJob.last_error || '未记录错误详情'}</pre>
          )}
        </div>
      )}

      {/* 执行日志 */}
      {taskRuns.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
          <button onClick={() => toggleSection('runs')} className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
            <div className="flex items-center gap-2 text-sm font-semibold dark:text-[var(--text-primary)]"><RefreshCw className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />执行日志</div>
            {expandedSection === 'runs' ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
          </button>
          {expandedSection === 'runs' && (
            <div className="overflow-x-auto border-t border-zinc-100 dark:border-[var(--surface-border)]">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-50 text-xs text-zinc-500 dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">
                  <tr><th className="px-3 py-2 font-semibold">Run</th><th className="px-3 py-2 font-semibold">状态</th><th className="px-3 py-2 font-semibold">开始</th><th className="px-3 py-2 font-semibold">结束</th><th className="px-3 py-2 font-semibold">错误</th></tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {taskRuns.map(run => (
                    <tr key={run.id} className="dark:text-[var(--text-primary)]">
                      <td className="px-3 py-2 font-mono text-xs">{run.id}</td>
                      <td className="px-3 py-2"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${badgeClass(run.status)}`}>{run.status}</span></td>
                      <td className="px-3 py-2 text-xs text-zinc-500 dark:text-[var(--text-muted)]">{run.started_at ? run.started_at.slice(0, 19).replace('T', ' ') : '-'}</td>
                      <td className="px-3 py-2 text-xs text-zinc-500 dark:text-[var(--text-muted)]">{run.finished_at ? run.finished_at.slice(0, 19).replace('T', ' ') : '-'}</td>
                      <td className="max-w-[360px] truncate px-3 py-2 text-xs text-red-600 dark:text-[var(--danger)]" title={run.last_error || ''}>{shortText(run.last_error, 100) || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 报告文件 */}
      {reportFiles.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
          <button onClick={() => toggleSection('files')} className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
            <div className="flex items-center gap-2 text-sm font-semibold dark:text-[var(--text-primary)]"><FileText className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />报告文件 <span className="rounded border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs font-normal text-zinc-500 dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">{reportFiles.length} 份</span></div>
            {expandedSection === 'files' ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
          </button>
          {expandedSection === 'files' && (
            <div className="overflow-x-auto border-t border-zinc-100 dark:border-[var(--surface-border)]">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-50 text-xs text-zinc-500 dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">
                  <tr><th className="px-3 py-2 font-semibold">报告</th><th className="px-3 py-2 font-semibold">下载</th><th className="px-3 py-2 font-semibold">上传</th><th className="px-3 py-2 font-semibold">错误</th><th className="px-3 py-2 font-semibold">文件</th></tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {reportFiles.map((file, index) => (
                    <tr key={file.id || index} className="dark:text-[var(--text-primary)]">
                      <td className="px-3 py-2"><div className="text-xs font-medium">{file.notice_title}</div><div className="font-mono text-xs text-zinc-400 dark:text-[var(--text-muted)]">{file.report_year} {file.report_period}</div></td>
                      <td className="px-3 py-2"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${badgeClass(file.pdf_status || '')}`}>{file.pdf_status || '-'}</span></td>
                      <td className="px-3 py-2"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${badgeClass(file.upload_status || '')}`}>{file.upload_status || '-'}</span></td>
                      <td className="max-w-[260px] truncate px-3 py-2 text-xs text-red-600 dark:text-[var(--danger)]" title={file.download_error || file.upload_error || ''}>{shortText(file.download_error || file.upload_error, 80) || '-'}</td>
                      <td className="max-w-[260px] truncate px-3 py-2 font-mono text-xs text-zinc-500 dark:text-[var(--text-muted)]" title={file.file_path || ''}>{file.file_path || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 逐题回答 */}
      {answers.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
          <button onClick={() => toggleSection('answers')} className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
            <div className="flex items-center gap-2 text-sm font-semibold dark:text-[var(--text-primary)]"><Book className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />逐题回答</div>
            {expandedSection === 'answers' ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
          </button>
          {expandedSection === 'answers' && (
            <div className="divide-y divide-zinc-100 border-t border-zinc-100 dark:divide-[var(--surface-border)] dark:border-[var(--surface-border)]">
              {answers.map(a => (
                <div key={a.question_key} className="px-5 py-3 dark:text-[var(--text-primary)]">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="flex h-6 w-6 items-center justify-center rounded bg-zinc-900 text-xs font-semibold text-white dark:bg-[var(--surface-border)] dark:text-[var(--text-primary)]">{a.question_index}</span>
                    <span className="text-sm font-medium">{a.question_title}</span>
                    <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${badgeClass(a.status)}`}>{a.status}</span>
                  </div>
                  {(a.answer_markdown || a.raw_answer) && (
                    <div className="mt-2 max-h-60 overflow-y-auto rounded bg-zinc-50 p-3 text-xs text-zinc-600 whitespace-pre-wrap dark:bg-[var(--surface-muted)] dark:text-[var(--text-secondary)]">{a.answer_markdown || a.raw_answer}</div>
                  )}
                  {a.error_message && <div className="mt-1 text-xs text-red-500 dark:text-[var(--danger)]">{a.error_message}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 财务分析报告 — 优先展示，默认展开 */}
      {report && (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
          <button onClick={() => toggleSection('report')} className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
            <div className="flex items-center gap-2 text-sm font-semibold dark:text-[var(--text-primary)]">
              <FileText className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />财务分析报告
              {report.financial_risk_tier && (
                <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${
                  report.financial_risk_tier <= 'B' ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-[var(--success-border)] dark:bg-[var(--success-bg)] dark:text-[var(--success)]' :
                  report.financial_risk_tier === 'C' ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-[var(--warning-border)] dark:bg-[var(--warning-bg)] dark:text-[var(--warning)]' :
                  'border-red-200 bg-red-50 text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]'
                }`}>风险 {report.financial_risk_tier}</span>
              )}
            </div>
            {expandedSection === 'report' ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
          </button>
          {expandedSection === 'report' && (
            <div className="border-t border-zinc-100 p-5 dark:border-[var(--surface-border)]">
              <MarkdownContent text={report.report_markdown || ''} />
            </div>
          )}
        </div>
      )}

      {/* 红旗清单 */}
      {redFlags.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-[var(--surface-border)] dark:bg-[var(--surface)]">
          <button onClick={() => toggleSection('flags')} className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
            <div className="flex items-center gap-2 text-sm font-semibold dark:text-[var(--text-primary)]"><AlertCircle className="h-4 w-4 text-zinc-500 dark:text-[var(--text-muted)]" />财务红旗清单 <span className="rounded border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs font-normal text-zinc-500 dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">{redFlags.length} 项</span></div>
            {expandedSection === 'flags' ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
          </button>
          {expandedSection === 'flags' && (
            <div className="overflow-x-auto border-t border-zinc-100 dark:border-[var(--surface-border)]">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-50 text-xs text-zinc-500 dark:bg-[var(--surface-muted)] dark:text-[var(--text-muted)]">
                  <tr><th className="px-3 py-2 font-semibold">维度</th><th className="px-3 py-2 font-semibold">红旗事项</th><th className="px-3 py-2 font-semibold">风险等级</th><th className="px-3 py-2 font-semibold">数据依据</th><th className="px-3 py-2 font-semibold">年报解释</th><th className="px-3 py-2 font-semibold">解释充分</th></tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
                  {redFlags.map(f => (
                    <tr key={f.id} className="dark:text-[var(--text-primary)]">
                      <td className="px-3 py-2 text-xs text-zinc-500 dark:text-[var(--text-muted)]">{f.flag_type}</td>
                      <td className="px-3 py-2 text-xs">{f.flag_name}</td>
                      <td className="px-3 py-2"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${f.risk_level === '高' ? 'border-red-200 bg-red-50 text-red-700 dark:border-[var(--danger-border)] dark:bg-[var(--danger-bg)] dark:text-[var(--danger)]' : f.risk_level === '中' ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-[var(--warning-border)] dark:bg-[var(--warning-bg)] dark:text-[var(--warning)]' : 'border-zinc-200 bg-zinc-50 text-zinc-600 dark:border-[var(--surface-border)] dark:bg-[var(--surface-muted)] dark:text-[var(--text-secondary)]'}`}>{f.risk_level}</span></td>
                      <td className="max-w-[200px] truncate px-3 py-2 text-xs text-zinc-500 dark:text-[var(--text-muted)]">{f.evidence}</td>
                      <td className="max-w-[200px] truncate px-3 py-2 text-xs text-zinc-500 dark:text-[var(--text-muted)]">{f.annual_report_explanation}</td>
                      <td className="px-3 py-2 text-xs">{f.explanation_sufficient ? '✅' : '❌'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* 风险评分卡片 */}
      {report && (
        <ScoreCard
          parsedJson={report.parsed_json || null}
          score={report.financial_risk_score}
          tier={report.financial_risk_tier}
          source={report.score_source}
          repayment={report.first_repayment_source}
          advice={report.leasing_advice}
        />
      )}
    </div>
  );
}

// ─── Lightweight Markdown renderer (reused pattern) ──────────
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="prose prose-sm max-w-none text-zinc-700 dark:text-[var(--text-primary)]
      [&_h1]:mt-5 [&_h1]:mb-2
      [&_h2]:mt-4 [&_h2]:mb-1.5
      [&_h3]:mt-3 [&_h3]:mb-1
      [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:my-1.5
      [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:my-1.5
      [&_li]:my-0.5
      [&_table]:w-full [&_table]:border-collapse [&_table]:my-2
      [&_th]:border [&_th]:border-zinc-200 [&_th]:bg-zinc-50 dark:[&_th]:border-[var(--surface-border)] dark:[&_th]:bg-[var(--surface-muted)]
      [&_th]:px-3 [&_th]:py-1.5 [&_th]:text-xs [&_th]:font-semibold
      [&_td]:border [&_td]:border-zinc-200 [&_td]:px-3 [&_td]:py-1.5 [&_td]:text-xs dark:[&_td]:border-[var(--surface-border)]
      [&_code]:rounded [&_code]:bg-zinc-100 [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-xs [&_code]:font-mono dark:[&_code]:bg-[var(--surface-muted)]
      [&_pre]:my-2 [&_pre]:rounded [&_pre]:bg-zinc-900 [&_pre]:p-3 [&_pre]:text-xs [&_pre]:text-zinc-100 dark:[&_pre]:bg-zinc-800
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
