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
    <section className="rounded-lg border border-zinc-200 bg-white overflow-hidden">
      <div className="border-b border-zinc-100 px-5 py-3">
        <h2 className="text-sm font-semibold">③ 研究成果</h2>
      </div>
      <div className="p-5 space-y-4">
        {/* Search bar */}
        <div className="flex gap-3">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <input value={query} onChange={e => onQueryChange(e.target.value)}
              className="h-10 w-full rounded border border-zinc-200 pl-9 pr-3 text-sm outline-none focus:border-blue-400"
              placeholder="股票代码 / 名称" />
          </div>
          <button onClick={onSearch}
            className="inline-flex h-10 items-center gap-2 rounded bg-zinc-900 px-4 text-sm font-semibold text-white hover:bg-zinc-800">
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
            <div key={answer.question_key} className="rounded-lg border border-zinc-200 bg-white">
              <button onClick={() => onToggleAnswer(answer.question_key)}
                className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-zinc-50">
                <div className="flex items-center gap-3">
                  <span className="flex h-6 w-6 items-center justify-center rounded bg-zinc-900 text-xs font-semibold text-white">{answer.question_index}</span>
                  <span className="text-sm font-medium">{answer.question_title}</span>
                  <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(answer.status)}`}>{answer.status}</span>
                </div>
                {expandedAnswers[answer.question_key] ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
              </button>
              {expandedAnswers[answer.question_key] && (
                <div className="border-t border-zinc-100 p-4">
                  <MarkdownContent text={answer.answer_markdown || answer.raw_answer || '暂无回答'} />
                  <div className="mt-3 text-xs text-zinc-400">
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
    <div className="overflow-hidden rounded-lg border border-zinc-200 bg-white">
      <button onClick={() => setExpanded(prev => !prev)} className="flex w-full items-center justify-between border-b border-zinc-100 px-5 py-4 text-left hover:bg-zinc-50">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Download className="h-4 w-4 text-zinc-500" />
          已下载 PDF 公告
          <span className="rounded border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs font-normal text-zinc-500">{pdfs.length} 条</span>
        </div>
        {expanded ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
      </button>
      {expanded && (
        <div className="overflow-x-auto">
          <table className="min-w-[900px] w-full text-left text-sm">
            <thead className="bg-zinc-50 text-xs text-zinc-500">
              <tr>{['日期', '公告标题', '下载', '上传', '本地文件', '来源', '大小', '本地路径', '错误'].map(item => <th key={item} className="px-4 py-3 font-semibold">{item}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {pdfs.map(pdf => (
                <tr key={pdf.id}>
                  <td className="px-4 py-3 text-xs">{pdf.notice_date || '-'}</td>
                  <td className="px-4 py-3">{pdf.notice_title || '-'}</td>
                  <td className="px-4 py-3"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(pdf.download_status)}`}>{pdf.download_status}</span></td>
                  <td className="px-4 py-3"><span className={`rounded border px-2 py-0.5 text-xs font-semibold ${statusClass(pdf.upload_status || 'pending')}`}>{pdf.upload_status || 'pending'}</span></td>
                  <td className="px-4 py-3">
                    <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${pdf.local_file_deleted ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
                      {pdf.local_file_deleted ? '已删除' : '待清理'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs">{pdf.source_provider}</td>
                  <td className="px-4 py-3 text-xs">{Math.round(Number(pdf.file_size || 0) / 1024)} KB</td>
                  <td className="max-w-[260px] truncate px-4 py-3 font-mono text-xs text-zinc-500">{pdf.local_file_deleted ? '本地文件已删除' : pdf.file_path}</td>
                  <td className="max-w-[220px] truncate px-4 py-3 text-xs text-red-600">{pdf.delete_local_error || pdf.error_message || '-'}</td>
                </tr>
              ))}
              {pdfs.length === 0 && <tr><td colSpan={9} className="px-4 py-8 text-center text-sm text-zinc-400">暂无 PDF 记录</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
