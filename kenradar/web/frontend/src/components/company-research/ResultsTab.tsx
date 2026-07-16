/**
 * Results section — stock search, stat bar, Q&A cards, scorecard, PDF table.
 * @license Apache-2.0
 */
import React, { useState } from 'react';
import { ChevronDown, ChevronRight, Download, Search } from 'lucide-react';
import { CompanyNoticeFile, CompanyResearchAnswer } from '../../types';
import { FinScoreCard } from '../CompanyFinancialAnalysisMVP';
import { statusClass, StatCard, MarkdownContent } from './shared';

// ─── Props ───────────────────────────────────────────────────

export interface ResultsTabProps {
  query: string;
  onQueryChange: (v: string) => void;
  onSearch: () => void;
  summary: Record<string, any> | null;
  answers: CompanyResearchAnswer[];
  pdfs: CompanyNoticeFile[];
  savedCount: number;
  expandedAnswers: Record<string, boolean>;
  onToggleAnswer: (key: string) => void;
  finScore?: { score: number; tier: string | null } | null;
}

// ─── Component ───────────────────────────────────────────────

export function ResultsTab({
  query, onQueryChange, onSearch,
  summary, answers, pdfs, savedCount,
  expandedAnswers, onToggleAnswer, finScore,
}: ResultsTabProps) {
  return (
    <section className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] overflow-hidden">
      <div className="border-b border-zinc-100 dark:border-[var(--surface-border)] px-5 py-3">
        <h2 className="text-sm font-semibold dark:text-[var(--text-primary)]">③ 研究成果</h2>
      </div>
      <div className="p-5 space-y-4">
        {/* Search bar */}
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400 dark:text-[var(--text-muted)]" />
            <input value={query} onChange={e => onQueryChange(e.target.value)}
              className="h-10 w-full rounded border border-zinc-200 dark:border-[var(--surface-border)] pl-9 pr-3 text-sm outline-none focus:border-blue-400 dark:focus:border-[var(--accent)] bg-white dark:bg-[var(--surface)] text-zinc-900 dark:text-[var(--text-primary)]"
              placeholder="股票代码 / 名称" />
          </div>
          <button onClick={onSearch}
            className="inline-flex h-10 items-center gap-2 rounded bg-zinc-900 dark:bg-[var(--accent)] px-4 text-sm font-semibold text-white hover:bg-zinc-800 dark:hover:bg-[var(--accent-hover)]">
            <Search className="h-4 w-4" />查询
          </button>
        </div>

        {/* Stock stat bar */}
        {summary && (
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
            <StatCard label="股票代码" value={summary.symbol || query} />
            <StatCard label="股票名称" value={summary.stock_name || '-'} />
            <StatCard label="PDF 数" value={summary.local_pdf_count ?? 0} />
            <StatCard label="已回答" value={`${savedCount}/10`} />
            <StatCard label="状态" value={summary.status || '-'} badge={summary.status} />
            <StatCard label="更新" value={summary.last_researched_at ? summary.last_researched_at.slice(0, 10) : '-'} />
          </div>
        )}

        {/* Financial scorecard */}
        {finScore && finScore.score !== null && (
          <FinScoreCard
            parsedJson={null}
            score={finScore.score}
            tier={finScore.tier}
            source={null}
            repayment={null}
            advice={null}
          />
        )}

        {/* Q&A cards */}
        <div className="space-y-2">
          {answers.map(answer => (
            <div key={answer.question_key} className="rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
              <button onClick={() => onToggleAnswer(answer.question_key)}
                className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
                <div className="flex items-center gap-3">
                  <span className="flex h-6 w-6 items-center justify-center rounded bg-zinc-900 dark:bg-[var(--accent)] text-xs font-semibold text-white">{answer.question_index}</span>
                  <span className="text-sm font-medium dark:text-[var(--text-primary)]">{answer.question_title}</span>
                  <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(answer.status)}`}>{answer.status}</span>
                </div>
                {expandedAnswers[answer.question_key] ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
              </button>
              {expandedAnswers[answer.question_key] && (
                <div className="border-t border-zinc-100 dark:border-[var(--surface-border)] p-4">
                  <MarkdownContent text={answer.answer_markdown || answer.raw_answer || '暂无回答'} />
                  <div className="mt-3 text-xs text-zinc-400 dark:text-[var(--text-muted)]">
                    <span>生成: {answer.generated_at || '-'}</span>
                    <span className="ml-4">保存: {answer.saved_at || '-'}</span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* PDF table */}
        <PdfTable pdfs={pdfs} />
      </div>
    </section>
  );
}

// ─── PdfTable ────────────────────────────────────────────────

function PdfTable({ pdfs }: { pdfs: CompanyNoticeFile[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="overflow-hidden rounded-lg border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)]">
      <button onClick={() => setExpanded(prev => !prev)} className="flex w-full items-center justify-between border-b border-zinc-100 dark:border-[var(--surface-border)] px-5 py-4 text-left hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
        <div className="flex items-center gap-2 text-sm font-semibold dark:text-[var(--text-primary)]">
          <Download className="h-4 w-4 text-zinc-500 dark:text-[var(--text-secondary)]" />
          已下载 PDF 公告
          <span className="rounded border border-zinc-200 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] px-2 py-0.5 text-xs font-normal text-zinc-500 dark:text-[var(--text-muted)]">{pdfs.length} 条</span>
        </div>
        {expanded ? <ChevronDown className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" /> : <ChevronRight className="h-4 w-4 text-zinc-400 dark:text-[var(--text-muted)]" />}
      </button>
      {expanded && (
        <div className="overflow-x-auto">
          <table className="min-w-[900px] w-full text-left text-sm">
            <thead className="bg-zinc-50 dark:bg-[var(--surface-muted)] text-xs text-zinc-500 dark:text-[var(--text-muted)]">
              <tr>{['日期', '公告标题', '下载', '上传', '本地文件', '来源', '大小', '本地路径', '错误'].map(item => <th key={item} className="px-4 py-3 font-semibold dark:text-[var(--text-primary)]">{item}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-[var(--surface-border)]">
              {pdfs.map(pdf => (
                <tr key={pdf.id} className="hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)]">
                  <td className="px-4 py-3 text-xs dark:text-[var(--text-primary)]">{pdf.notice_date || '-'}</td>
                  <td className="px-4 py-3 dark:text-[var(--text-primary)]">{pdf.notice_title || '-'}</td>
                  <td className="px-4 py-3"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(pdf.download_status)}`}>{pdf.download_status}</span></td>
                  <td className="px-4 py-3"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(pdf.upload_status || 'pending')}`}>{pdf.upload_status || 'pending'}</span></td>
                  <td className="px-4 py-3">
                    <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${pdf.local_file_deleted ? 'border-emerald-200 dark:border-[var(--success-border)] bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-700 dark:text-[var(--success)]' : 'border-amber-200 dark:border-[var(--warning-border)] bg-amber-50 dark:bg-[var(--warning-bg)] text-amber-700 dark:text-[var(--warning)]'}`}>
                      {pdf.local_file_deleted ? '已删除' : '待清理'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs dark:text-[var(--text-primary)]">{pdf.source_provider}</td>
                  <td className="px-4 py-3 text-xs dark:text-[var(--text-primary)]">{Math.round(Number(pdf.file_size || 0) / 1024)} KB</td>
                  <td className="max-w-[260px] truncate px-4 py-3 font-mono text-xs text-zinc-500 dark:text-[var(--text-muted)]">{pdf.local_file_deleted ? '本地文件已删除' : pdf.file_path}</td>
                  <td className="max-w-[220px] truncate px-4 py-3 text-xs text-red-600 dark:text-[var(--danger)]">{pdf.delete_local_error || pdf.error_message || '-'}</td>
                </tr>
              ))}
              {pdfs.length === 0 && <tr><td colSpan={9} className="px-4 py-8 text-center text-sm text-zinc-400 dark:text-[var(--text-muted)]">暂无 PDF 记录</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
