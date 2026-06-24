/**
 * Launcher section — research mode selector + configuration forms.
 * @license Apache-2.0
 */
import React from 'react';
import { FileText, Play, RefreshCw } from 'lucide-react';
import { FinAnalysisLauncher } from '../CompanyFinancialAnalysisMVP';
import { Field, PreviewStock } from './shared';

// ─── Props ───────────────────────────────────────────────────

export type ResearchMode = 'general' | 'financial';

export interface LauncherTabProps {
  activeResearchMode: ResearchMode;
  onModeChange: (mode: ResearchMode) => void;
  // General research
  beginDate: string; onBeginDateChange: (v: string) => void;
  endDate: string; onEndDateChange: (v: string) => void;
  stockScope: string; onStockScopeChange: (v: string) => void;
  maxStocks: number; onMaxStocksChange: (v: number) => void;
  symbols: string; onSymbolsChange: (v: string) => void;
  noticeType: string; onNoticeTypeChange: (v: string) => void;
  executionMode: string; onExecutionModeChange: (v: string) => void;
  autoDelete: boolean; onAutoDeleteChange: (v: boolean) => void;
  previewStocks: PreviewStock[];
  onPreview: () => void; onStartTask: () => void; onRefresh: () => void;
  // Financial analysis
  finSymbol: string; onFinSymbolChange: (v: string) => void;
  finBaseYear: number; onFinBaseYearChange: (v: number) => void;
  finAutoDelete: boolean; onFinAutoDeleteChange: (v: boolean) => void;
  finPreviewResult: unknown;
  onFinPreview: () => void; onFinStart: () => void; onFinRefresh: () => void;
}

// ─── Component ───────────────────────────────────────────────

export function LauncherTab({
  activeResearchMode, onModeChange,
  beginDate, onBeginDateChange,
  endDate, onEndDateChange,
  stockScope, onStockScopeChange,
  maxStocks, onMaxStocksChange,
  symbols, onSymbolsChange,
  noticeType, onNoticeTypeChange,
  executionMode, onExecutionModeChange,
  autoDelete, onAutoDeleteChange,
  previewStocks,
  onPreview, onStartTask, onRefresh,
  finSymbol, onFinSymbolChange,
  finBaseYear, onFinBaseYearChange,
  finAutoDelete, onFinAutoDeleteChange,
  finPreviewResult,
  onFinPreview, onFinStart, onFinRefresh,
}: LauncherTabProps) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white overflow-hidden">
      <div className="border-b border-zinc-100 px-5 py-3">
        <h2 className="text-sm font-semibold">① 发起研究</h2>
      </div>
      <div className="p-5 space-y-4">
        {/* Research mode selector */}
        <div className="flex flex-wrap items-center gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="researchMode" checked={activeResearchMode === 'general'}
              onChange={() => onModeChange('general')} className="h-4 w-4" />
            <span className="text-sm font-medium">通用公告研究（10题）</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="researchMode" checked={activeResearchMode === 'financial'}
              onChange={() => onModeChange('financial')} className="h-4 w-4" />
            <span className="text-sm font-medium">财务风险分析（11题）</span>
          </label>
          <label className="flex items-center gap-2 cursor-not-allowed opacity-50">
            <input type="radio" disabled className="h-4 w-4" />
            <span className="text-sm">自定义问题集（第二期）</span>
          </label>
        </div>

        {/* General mode */}
        {activeResearchMode === 'general' && (
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Field label="开始日期"><input type="date" value={beginDate} onChange={e => onBeginDateChange(e.target.value)} className="input" /></Field>
              <Field label="结束日期"><input type="date" value={endDate} onChange={e => onEndDateChange(e.target.value)} className="input" /></Field>
              <Field label="处理模式">
                <select value={stockScope} onChange={e => onStockScopeChange(e.target.value)} className="input">
                  <option value="manual">手动输入多只股票</option>
                  <option value="first_n">从股票列表前 N 只</option>
                </select>
              </Field>
              <Field label="本次最多处理">
                <input type="number" min={1} max={50} value={maxStocks} onChange={e => onMaxStocksChange(Number(e.target.value || 1))} className="input" />
              </Field>
              <Field label="股票代码">
                <textarea value={symbols} onChange={e => onSymbolsChange(e.target.value)} className="input min-h-20 resize-y" placeholder="300750.SZ, 000001.SZ" />
              </Field>
              <Field label="公告类型">
                <select value={noticeType} onChange={e => onNoticeTypeChange(e.target.value)} className="input">
                  {['全部', '财务报告', '重大事项', '融资公告', '风险提示', '资产重组', '信息变更', '持股变动'].map(i => <option key={i} value={i}>{i}</option>)}
                </select>
              </Field>
              <Field label="执行模式">
                <select value={executionMode} onChange={e => onExecutionModeChange(e.target.value)} className="input">
                  <option value="download_only">仅下载 PDF</option>
                  <option value="download_upload">下载 PDF + 上传 NotebookLM</option>
                  <option value="download_upload_ask">下载 + 上传 + 逐题提问</option>
                  <option value="full">完整流程</option>
                </select>
              </Field>
              <label className="flex items-end gap-2 text-sm font-medium text-zinc-700 pb-2">
                <input type="checkbox" checked={autoDelete} onChange={e => onAutoDeleteChange(e.target.checked)} className="h-4 w-4 rounded border-zinc-300" />
                10 题保存后删除 NotebookLM
              </label>
            </div>
            <div className="flex flex-wrap gap-3">
              <button onClick={onPreview} className="inline-flex h-9 items-center gap-1.5 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50"><FileText className="h-4 w-4" />预览任务</button>
              <button onClick={onStartTask} className="inline-flex h-9 items-center gap-1.5 rounded bg-zinc-900 px-3 text-sm font-semibold text-white hover:bg-zinc-800"><Play className="h-4 w-4" />开始研究</button>
              <button onClick={onRefresh} className="inline-flex h-9 items-center gap-1.5 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50"><RefreshCw className="h-4 w-4" />刷新进度</button>
            </div>
            {previewStocks.length > 0 && (
              <div className="rounded-lg border border-zinc-100 bg-zinc-50 p-3">
                <div className="text-xs text-zinc-500 mb-2">任务预览（{previewStocks.length} 只股票）</div>
                <div className="flex flex-wrap gap-2">
                  {previewStocks.map(s => (
                    <span key={s.symbol} className="rounded border border-zinc-200 bg-white px-2 py-1 text-xs font-mono">{s.symbol} {s.name}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Financial mode */}
        {activeResearchMode === 'financial' && (
          <FinAnalysisLauncher
            symbol={finSymbol}
            onSymbolChange={onFinSymbolChange}
            analysisBaseYear={finBaseYear}
            onAnalysisBaseYearChange={onFinBaseYearChange}
            autoDelete={finAutoDelete}
            onAutoDeleteChange={onFinAutoDeleteChange}
            onPreview={onFinPreview}
            onStart={onFinStart}
            onRefresh={onFinRefresh}
            previewResult={finPreviewResult as any}
          />
        )}
      </div>
    </section>
  );
}
