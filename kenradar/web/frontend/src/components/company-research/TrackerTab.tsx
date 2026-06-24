/**
 * Tracker section — batch/job progress with stage pipelines and event log.
 * @license Apache-2.0
 */
import React, { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ChevronDown, ChevronRight, Clock } from 'lucide-react';
import { CompanyResearchJob } from '../../types';
import { FinAnalysisJobList } from '../CompanyFinancialAnalysisMVP';
import {
  statusClass, getStageLabel, getStageIndex, isTerminalStatus,
  STAGE_PIPELINE, groupJobsByBatch, requestJson, FinJob,
} from './shared';

// ─── Props ───────────────────────────────────────────────────

export interface TrackerTabProps {
  batches: any[];
  jobs: CompanyResearchJob[];
  finJobs: FinJob[];
  expandedBatches: Set<string>;
  expandedLogs: boolean;
  onToggleBatch: (id: string) => void;
  onToggleLogs: () => void;
  onViewStock: (symbol: string) => void;
}

// ─── Component ───────────────────────────────────────────────

export function TrackerTab({
  batches, jobs, finJobs,
  expandedBatches, expandedLogs,
  onToggleBatch, onToggleLogs, onViewStock,
}: TrackerTabProps) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white overflow-hidden">
      <div className="border-b border-zinc-100 px-5 py-3">
        <h2 className="text-sm font-semibold">② 研究进度</h2>
      </div>
      <div className="p-5 space-y-5">
        {/* General research */}
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold mb-3">
            <span className="rounded bg-blue-100 text-blue-700 px-2 py-0.5 text-xs">通用公告研究</span>
          </h3>
          {batches.length > 0 ? (
            <div className="space-y-3">
              {batches.map(batch => (
                <BatchCard key={batch.batch_id} batch={batch}
                  expanded={expandedBatches.has(batch.batch_id)}
                  onToggle={() => onToggleBatch(batch.batch_id)}
                  onView={onViewStock} />
              ))}
            </div>
          ) : jobs.length > 0 ? (
            <div className="space-y-3">
              {groupJobsByBatch(jobs).map(([batchId, batchJobs]) => (
                <BatchCard key={batchId}
                  batch={{ batch_id: batchId, total_stocks: batchJobs.length, status: 'legacy' }}
                  jobs={batchJobs}
                  expanded={expandedBatches.has(batchId)}
                  onToggle={() => onToggleBatch(batchId)}
                  onView={onViewStock} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-400">暂无通用研究任务</p>
          )}
        </div>

        {/* Financial analysis */}
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold mb-3">
            <span className="rounded bg-emerald-100 text-emerald-700 px-2 py-0.5 text-xs">财务风险分析</span>
          </h3>
          <FinAnalysisJobList jobs={finJobs} />
        </div>

        {/* Event log */}
        <EventLog jobs={jobs} expanded={expandedLogs} onToggle={onToggleLogs} />
      </div>
    </section>
  );
}

// ─── BatchCard ───────────────────────────────────────────────

function BatchCard({
  batch, jobs: externalJobs, expanded, onToggle, onView,
}: {
  key?: React.Key;
  batch: any;
  jobs?: CompanyResearchJob[];
  expanded: boolean;
  onToggle: () => void;
  onView: (symbol: string) => void;
}) {
  const [batchJobs, setBatchJobs] = useState<CompanyResearchJob[]>(externalJobs || []);
  const isLegacy = batch.status === 'legacy';

  useEffect(() => {
    if (externalJobs) { setBatchJobs(externalJobs); return; }
    if (isLegacy) return;
    requestJson<{ jobs: CompanyResearchJob[] }>(`/api/company-research/batches/${encodeURIComponent(batch.batch_id)}`)
      .then(data => setBatchJobs(data.jobs || []))
      .catch(() => undefined);
  }, [batch.batch_id, externalJobs, isLegacy]);

  const totalStocks = batch.total_stocks ?? batchJobs.length;
  const completed = batch.completed_stocks ?? batchJobs.filter(j => j.status === 'completed').length;
  const failedCount = batch.failed_stocks ?? batchJobs.filter(j => j.status === 'failed' || j.status === 'partial_failed').length;
  const running = batchJobs.filter(j => !isTerminalStatus(j.status)).length;
  const batchStatus = batch.status || 'unknown';

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <button onClick={onToggle} className="flex w-full items-center justify-between border-b border-zinc-100 px-5 py-3 text-left hover:bg-zinc-50">
        <div className="flex items-center gap-3">
          {expanded ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
          <span className="text-sm font-semibold text-zinc-700">批次: {batch.batch_id ? batch.batch_id.slice(0, 30) + '…' : '未分组'}</span>
          {isLegacy && <span className="rounded border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs text-zinc-500">旧数据</span>}
          <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(batchStatus)}`}>
            {batchStatus === 'completed' ? '已完成' : batchStatus === 'running' ? '执行中' : batchStatus === 'failed' ? '失败' : batchStatus === 'partial_failed' ? '部分失败' : batchStatus}
          </span>
        </div>
        <div className="flex items-center gap-4 text-xs text-zinc-500">
          <span>共 {totalStocks} 只</span>
          {completed > 0 && <span className="text-emerald-600">✓ {completed}</span>}
          {failedCount > 0 && <span className="text-red-600">✗ {failedCount}</span>}
          {running > 0 && <span className="text-blue-600">▶ {running}</span>}
        </div>
      </button>

      {expanded && (
        <div className="divide-y divide-zinc-50 px-5 py-3">
          {!isLegacy && (
            <div className="mb-3 grid grid-cols-4 gap-3 text-xs">
              {[
                ['查询区间', `${batch.begin_date || '-'} 至 ${batch.end_date || '-'}`],
                ['公告类型', batch.notice_type || '全部'],
                ['执行模式', batch.execution_mode === 'full' ? '完整流程' : batch.execution_mode === 'download_only' ? '仅下载PDF' : batch.execution_mode === 'download_upload' ? '下载+上传' : batch.execution_mode || '-'],
                ['创建时间', batch.created_at ? batch.created_at.slice(0, 16) : '-'],
              ].map(([label, value]) => (
                <div key={label as string} className="rounded border border-zinc-100 bg-zinc-50 px-3 py-2">
                  <div className="text-zinc-400">{label}</div>
                  <div className="mt-0.5 font-medium text-zinc-700">{value}</div>
                </div>
              ))}
            </div>
          )}

          {batchJobs.length === 0 && <div className="py-6 text-center text-sm text-zinc-400">暂无任务记录</div>}

          <div className="space-y-3">
            {batchJobs.map(job => (
              <JobStageCard key={job.id} job={job} onView={onView} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── JobStageCard ────────────────────────────────────────────

function JobStageCard({ job, onView }: { key?: React.Key; job: CompanyResearchJob; onView: (symbol: string) => void }) {
  const currentStage = job.current_stage || '';
  const jobStatus = job.status;
  const stageIdx = getStageIndex(currentStage);
  const isRunning = !isTerminalStatus(jobStatus);
  const progressPct = Math.round(Number(job.progress_percent || 0));

  return (
    <div className="rounded-lg border border-zinc-100 bg-zinc-50 p-4 transition-colors hover:bg-zinc-100">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold text-zinc-900">{job.symbol}</span>
          <span className="text-sm text-zinc-500">{job.stock_name}</span>
          <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(jobStatus)}`}>
            {getStageLabel(currentStage || jobStatus)}
          </span>
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          <span>进度 {progressPct}%</span>
          <button onClick={() => onView(job.symbol)} className="rounded border border-zinc-200 bg-white px-2.5 py-1 text-xs font-semibold hover:bg-zinc-50">
            查看详情
          </button>
        </div>
      </div>

      <div className="mb-3 flex items-center gap-1">
        {STAGE_PIPELINE.map((stage, idx) => {
          const isPast = idx < stageIdx;
          const isCurrent = idx === stageIdx || (stage.key === 'ask' && stageIdx >= 5 && !isTerminalStatus(jobStatus));
          const isDone = isPast || (idx <= stageIdx && isTerminalStatus(jobStatus));
          return (
            <React.Fragment key={stage.key}>
              <div className={`flex shrink-0 items-center gap-1 rounded px-2 py-1 text-xs font-medium ${
                isDone ? 'bg-emerald-100 text-emerald-700' :
                isCurrent ? 'bg-blue-100 text-blue-700 animate-pulse' :
                'bg-zinc-100 text-zinc-400'
              }`}>
                <span>{stage.icon}</span>
                <span className="hidden sm:inline">{stage.label}</span>
              </div>
              {idx < STAGE_PIPELINE.length - 1 && (
                <div className={`h-px flex-1 ${isPast ? 'bg-emerald-300' : 'bg-zinc-200'}`} />
              )}
            </React.Fragment>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-zinc-500">
        <span>索引: {job.notice_total || 0}</span>
        <span>PDF: <span className={job.pdf_failed ? 'text-red-600' : 'text-zinc-700'}>{job.pdf_downloaded || 0}</span>{job.pdf_failed ? <span className="text-red-600">/✗{job.pdf_failed}</span> : ''}</span>
        <span>上传: {job.source_uploaded || 0}/{job.source_ready || 0}</span>
        <span>问答: <span className="text-zinc-700">{job.question_saved || 0}</span>/10</span>
        <span>Notebook: {job.notebook_deleted ? '已删除' : job.notebook_id ? '未删除' : '-'}</span>
        {job.last_error && (
          <span className="flex items-center gap-1 text-red-600" title={job.last_error}>
            <AlertCircle className="h-3 w-3" />{job.last_error.length > 40 ? job.last_error.slice(0, 40) + '…' : job.last_error}
          </span>
        )}
      </div>
    </div>
  );
}

// ─── EventLog ────────────────────────────────────────────────

function EventLog({ jobs, expanded, onToggle }: { jobs: CompanyResearchJob[]; expanded: boolean; onToggle: () => void }) {
  const events = useMemo(() => {
    const entries: { time: string; symbol: string; stage: string; label: string; detail: string }[] = [];
    for (const job of jobs) {
      if (job.updated_at) {
        entries.push({
          time: job.updated_at, symbol: job.symbol,
          stage: job.current_stage || job.status,
          label: getStageLabel(job.current_stage || job.status),
          detail: job.last_error
            ? `失败: ${job.last_error}`
            : `PDF ${job.pdf_downloaded || 0}/${job.notice_total || 0}, 上传 ${job.source_uploaded || 0}, 问答 ${job.question_saved || 0}/10`,
        });
      }
      if (job.notebook_deleted && (job as any).notebook_deleted_at) {
        entries.push({
          time: (job as any).notebook_deleted_at, symbol: job.symbol,
          stage: 'delete_notebook', label: '删除 Notebook', detail: 'Notebook 已删除',
        });
      }
    }
    entries.sort((a, b) => (b.time || '').localeCompare(a.time || ''));
    return entries.slice(0, 100);
  }, [jobs]);

  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <button onClick={onToggle} className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50">
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
          <Clock className="h-4 w-4 text-zinc-500" />
          <span className="text-sm font-semibold text-zinc-700">任务日志</span>
          <span className="rounded border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs text-zinc-500">{events.length} 条</span>
        </div>
      </button>
      {expanded && (
        <div className="max-h-80 overflow-y-auto border-t border-zinc-100">
          {events.length === 0 ? (
            <div className="px-5 py-6 text-center text-sm text-zinc-400">暂无日志记录</div>
          ) : (
            <div className="divide-y divide-zinc-50">
              {events.map((ev, idx) => (
                <div key={idx} className="flex items-start gap-3 px-5 py-2 text-xs hover:bg-zinc-50">
                  <span className="shrink-0 font-mono text-zinc-400">{ev.time ? ev.time.slice(5, 19).replace('T', ' ') : '--'}</span>
                  <span className="shrink-0 font-mono font-semibold text-zinc-600">{ev.symbol}</span>
                  <span className={`shrink-0 rounded px-1.5 py-0.5 font-medium ${
                    ev.stage === 'failed' ? 'bg-red-50 text-red-600' :
                    ev.stage === 'completed' || ev.stage === 'delete_notebook' ? 'bg-emerald-50 text-emerald-600' :
                    'bg-blue-50 text-blue-600'
                  }`}>{ev.label}</span>
                  <span className="text-zinc-500">{ev.detail}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
