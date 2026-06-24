/**
 * Company Research Workspace — single-page research pipeline.
 * Manages state, handlers, polling, and orchestrates 4 section components.
 * @license Apache-2.0
 */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { FinAnalysisLauncher, FinAnalysisJobList, FinScoreCard } from './CompanyFinancialAnalysisMVP';
import {
  requestJson, isoDate, today, threeYearsAgo, PreviewStock,
} from './company-research/shared';
import { LauncherTab } from './company-research/LauncherTab';
import { TrackerTab } from './company-research/TrackerTab';
import { ResultsTab } from './company-research/ResultsTab';
import { SettingsTab } from './company-research/SettingsTab';
import { CompanyNoticeFile, CompanyResearchAnswer, CompanyResearchJob, NotebookLMNotebook, NotebookLMStatus } from '../types';

// ─── Financial analysis types ─────────────────────────────────

interface FinJob {
  id: number; symbol: string; stock_name: string; status: string;
  current_stage: string; selected_pdf_count: number;
  uploaded_source_count: number; ready_source_count: number;
  question_answered: number; question_saved: number;
  financial_risk_score: number | null; financial_risk_tier: string;
  notebook_deleted: boolean; last_error: string;
  created_at: string; updated_at: string;
  queued?: boolean; task_run_id?: number; queue_position?: number;
}

interface FinReportFile {
  id?: number; report_year: number; report_period: string;
  report_period_end: string; report_type: string;
  notice_title: string; notice_date: string; found: boolean;
  pdf_status: string; upload_status: string;
  file_path?: string; download_error?: string; upload_error?: string;
}

// ─── Main Component ──────────────────────────────────────────

export default function CompanyResearchWorkspace() {
  // ─── Research mode ──
  const [activeResearchMode, setActiveResearchMode] = useState<'general' | 'financial'>('general');
  const [expandedAnswers, setExpandedAnswers] = useState<Record<string, boolean>>({});
  const [settingsExpanded, setSettingsExpanded] = useState(false);
  const [expandedLogs, setExpandedLogs] = useState(false);

  // ─── General research state ──
  const [query, setQuery] = useState('300750.SZ');
  const [summary, setSummary] = useState<Record<string, any> | null>(null);
  const [answers, setAnswers] = useState<CompanyResearchAnswer[]>([]);
  const [pdfs, setPdfs] = useState<CompanyNoticeFile[]>([]);
  const [jobs, setJobs] = useState<CompanyResearchJob[]>([]);
  const [beginDate, setBeginDate] = useState(isoDate(threeYearsAgo));
  const [endDate, setEndDate] = useState(isoDate(today));
  const [stockScope, setStockScope] = useState('manual');
  const [maxStocks, setMaxStocks] = useState(1);
  const [symbols, setSymbols] = useState('300750.SZ');
  const [noticeType, setNoticeType] = useState('全部');
  const [executionMode, setExecutionMode] = useState('full');
  const [autoDelete, setAutoDelete] = useState(true);
  const [previewStocks, setPreviewStocks] = useState<PreviewStock[]>([]);
  const [batches, setBatches] = useState<any[]>([]);
  const [expandedBatches, setExpandedBatches] = useState<Set<string>>(new Set());

  // ─── Financial analysis state ──
  const [finSymbol, setFinSymbol] = useState('300750.SZ');
  const [finBaseYear, setFinBaseYear] = useState(new Date().getFullYear());
  const [finAutoDelete, setFinAutoDelete] = useState(true);
  const [finJobs, setFinJobs] = useState<FinJob[]>([]);
  const [finPreviewResult, setFinPreviewResult] = useState<{ selected_reports: FinReportFile[]; missing_reports: string[]; total_selected: number } | null>(null);

  // ─── NotebookLM state ──
  const [notebookStatus, setNotebookStatus] = useState<NotebookLMStatus | null>(null);
  const [notebooks, setNotebooks] = useState<NotebookLMNotebook[]>([]);

  // ─── Shared ──
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const autoRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const savedCount = useMemo(() => answers.filter(item => item.status === 'saved').length, [answers]);

  // ─── Handlers: General research ──
  const loadStock = async (symbolOverride?: string) => {
    const target = symbolOverride ?? query;
    setError(''); setMessage('');
    const data = await requestJson<{ summary: Record<string, any>; answers: CompanyResearchAnswer[]; pdfs: CompanyNoticeFile[]; jobs: CompanyResearchJob[] }>(
      `/api/company-research/stocks/${encodeURIComponent(target)}/answers`
    );
    setSummary(data.summary || null);
    setAnswers(data.answers || []);
    setPdfs(data.pdfs || []);
    setJobs(data.jobs || []);
  };

  const requestPayload = () => ({
    begin_date: beginDate, end_date: endDate, stock_scope: stockScope,
    max_stocks: maxStocks,
    symbols: symbols.split(/[,\n]/).map(item => item.trim()).filter(Boolean),
    notice_type: noticeType, execution_mode: executionMode, auto_delete_notebook: autoDelete,
  });

  const preview = async () => {
    setError('');
    const data = await requestJson<{ stocks: PreviewStock[]; estimated_questions: number }>('/api/company-research/tasks/preview', {
      method: 'POST', body: JSON.stringify(requestPayload()),
    });
    setPreviewStocks(data.stocks || []);
    setMessage(`预览完成：${data.stocks?.length || 0} 只股票，预计 ${data.estimated_questions || 0} 次提问。`);
  };

  const startTask = async () => {
    setError('');
    const data = await requestJson<{ batch_id: string; total_stocks: number; queue_position: number }>('/api/company-research/tasks', {
      method: 'POST', body: JSON.stringify(requestPayload()),
    });
    setMessage(`批次已提交：${data.batch_id}，共 ${data.total_stocks} 只股票，队列第 ${data.queue_position} 位。`);
    window.setTimeout(() => loadJobs(), 1000);
  };

  const loadJobs = async () => {
    const data = await requestJson<{ items: CompanyResearchJob[] }>('/api/company-research/jobs');
    setJobs(data.items || []);
  };

  const loadBatches = async () => {
    const data = await requestJson<{ items: any[] }>('/api/company-research/batches');
    setBatches(data.items || []);
  };

  // ─── Handlers: Financial analysis ──
  const loadFinJobs = async () => {
    const data = await requestJson<{ items: FinJob[] }>('/api/company-research/financial-analysis/jobs');
    setFinJobs(data.items || []);
  };

  const finPreview = async () => {
    setError(''); setMessage('');
    const data = await requestJson<{ selected_reports: FinReportFile[]; missing_reports: string[]; total_selected: number }>(
      '/api/company-research/financial-analysis/preview', {
        method: 'POST', body: JSON.stringify({ symbol: finSymbol, analysis_base_year: finBaseYear }),
      });
    setFinPreviewResult(data);
    setMessage(`预览完成：找到 ${data.total_selected} 份报告`);
  };

  const finStart = async () => {
    setError(''); setMessage('');
    const data = await requestJson<{ job: FinJob }>('/api/company-research/financial-analysis/tasks', {
      method: 'POST', body: JSON.stringify({ symbol: finSymbol, analysis_base_year: finBaseYear, auto_delete_notebook: finAutoDelete }),
    });
    setMessage(`财务分析任务已创建: job_id=${data.job.id}`);
    setFinPreviewResult(null);
    await loadFinJobs();
  };

  // ─── Handlers: NotebookLM ──
  const loadNotebookStatus = async () => {
    const data = await requestJson<NotebookLMStatus>('/api/company-research/notebooklm/status');
    setNotebookStatus(data);
  };

  const loadNotebooks = async () => {
    const data = await requestJson<{ items: NotebookLMNotebook[] }>('/api/company-research/notebooklm/notebooks?limit=100');
    setNotebooks(data.items || []);
  };

  const cleanupNotebooks = async () => {
    const data = await requestJson<{ queue_position: number }>('/api/company-research/notebooks/cleanup', { method: 'POST', body: '{}' });
    setMessage(`NotebookLM 清理任务已加入队列，第 ${data.queue_position} 位。`);
  };

  const cleanupLocalPdfs = async () => {
    const data = await requestJson<{ queue_position: number }>('/api/company-research/pdfs/cleanup-local', { method: 'POST', body: '{}' });
    setMessage(`本地 PDF 清理任务已加入队列，第 ${data.queue_position} 位。`);
  };

  const reloginNotebook = async (accountEmail: string) => {
    const email = accountEmail.trim();
    if (!email) return;
    setError('');
    const data = await requestJson<NotebookLMStatus>('/api/company-research/notebooklm/relogin', {
      method: 'POST', body: JSON.stringify({ account_email: email, browser: 'chrome' }),
    });
    setNotebookStatus(data);
    setMessage(`NotebookLM 已切换并重新登录：${email}`);
  };

  // ─── Handlers: Cross-tab navigation ──
  const handleViewStock = async (symbol: string) => {
    setQuery(symbol);
    await loadStock(symbol);
  };

  // ─── Auto-refresh ──
  const hasRunningJobs = useMemo(() => {
    const running = ['running', 'downloading', 'uploading', 'asking', 'queued'];
    return jobs.some(j => running.includes(j.status));
  }, [jobs]);

  useEffect(() => {
    if (!hasRunningJobs) {
      if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null; }
      return;
    }
    if (autoRef.current) return;
    autoRef.current = setInterval(async () => {
      await Promise.all([loadJobs(), loadBatches()]);
    }, 3000);
    return () => { if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null; } };
  }, [hasRunningJobs]);

  // ─── Init ──
  useEffect(() => {
    loadStock().catch(() => undefined);
    loadNotebookStatus().catch(() => undefined);
    loadFinJobs().catch(() => undefined);
  }, []);

  // ─── Toggles ──
  const toggleBatch = (batchId: string) => {
    setExpandedBatches(prev => {
      const next = new Set(prev);
      if (next.has(batchId)) next.delete(batchId); else next.add(batchId);
      return next;
    });
  };

  const toggleAnswerExpanded = (answerKey: string) => {
    setExpandedAnswers(prev => ({ ...prev, [answerKey]: !prev[answerKey] }));
  };

  const withError = (fn: () => Promise<void>) => {
    fn().catch(exc => setError(exc.message || String(exc)));
  };

  // ─── Compute financial score for ResultsTab ──
  const finScore = summary?.symbol
    ? finJobs.find(j => j.symbol === summary.symbol)
    : null;
  const resultsFinScore = finScore && finScore.financial_risk_score !== null
    ? { score: finScore.financial_risk_score, tier: finScore.financial_risk_tier }
    : null;

  return (
    <div className="space-y-6 font-sans text-zinc-900">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">公司研究平台</h1>
        <p className="text-sm text-zinc-500">按标准研究流水线发起任务、跟踪进度、查看成果和管理系统设置。</p>
      </header>

      {(message || error) && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${error ? 'border-red-200 bg-red-50 text-red-700' : 'border-blue-200 bg-blue-50 text-blue-700'}`}>
          {error || message}
        </div>
      )}

      <LauncherTab
        activeResearchMode={activeResearchMode}
        onModeChange={setActiveResearchMode}
        beginDate={beginDate} onBeginDateChange={setBeginDate}
        endDate={endDate} onEndDateChange={setEndDate}
        stockScope={stockScope} onStockScopeChange={setStockScope}
        maxStocks={maxStocks} onMaxStocksChange={setMaxStocks}
        symbols={symbols} onSymbolsChange={setSymbols}
        noticeType={noticeType} onNoticeTypeChange={setNoticeType}
        executionMode={executionMode} onExecutionModeChange={setExecutionMode}
        autoDelete={autoDelete} onAutoDeleteChange={setAutoDelete}
        previewStocks={previewStocks}
        onPreview={() => withError(preview)}
        onStartTask={() => withError(startTask)}
        onRefresh={() => withError(loadJobs)}
        finSymbol={finSymbol} onFinSymbolChange={setFinSymbol}
        finBaseYear={finBaseYear} onFinBaseYearChange={setFinBaseYear}
        finAutoDelete={finAutoDelete} onFinAutoDeleteChange={setFinAutoDelete}
        finPreviewResult={finPreviewResult}
        onFinPreview={() => withError(finPreview)}
        onFinStart={() => withError(finStart)}
        onFinRefresh={() => withError(loadFinJobs)}
      />

      <TrackerTab
        batches={batches}
        jobs={jobs}
        finJobs={finJobs}
        expandedBatches={expandedBatches}
        expandedLogs={expandedLogs}
        onToggleBatch={toggleBatch}
        onToggleLogs={() => setExpandedLogs(prev => !prev)}
        onViewStock={handleViewStock}
      />

      <ResultsTab
        query={query} onQueryChange={setQuery} onSearch={() => withError(() => loadStock())}
        summary={summary} answers={answers} pdfs={pdfs} savedCount={savedCount}
        expandedAnswers={expandedAnswers} onToggleAnswer={toggleAnswerExpanded}
        finScore={resultsFinScore}
      />

      <SettingsTab
        settingsExpanded={settingsExpanded}
        onToggleSettings={() => setSettingsExpanded(prev => !prev)}
        notebookStatus={notebookStatus}
        notebooks={notebooks}
        onRefreshStatus={() => withError(loadNotebookStatus)}
        onRefreshNotebooks={() => withError(loadNotebooks)}
        onRelogin={(email) => withError(() => reloginNotebook(email))}
        onCleanupNotebooks={() => withError(cleanupNotebooks)}
        onCleanupLocalPdfs={() => withError(cleanupLocalPdfs)}
      />
    </div>
  );
}
