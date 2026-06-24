/**
 * Settings section — NotebookLM accounts, notebook management, cleanup tools.
 * @license Apache-2.0
 */
import React, { useState } from 'react';
import { Book, FolderOpen, LogIn, RefreshCw, Settings, Trash2, UserCircle2, ChevronDown, ChevronRight } from 'lucide-react';
import { NotebookLMNotebook, NotebookLMStatus } from '../../types';
import { StatusItem } from './shared';

// ─── Props ───────────────────────────────────────────────────

export interface SettingsTabProps {
  settingsExpanded: boolean;
  onToggleSettings: () => void;
  notebookStatus: NotebookLMStatus | null;
  notebooks: NotebookLMNotebook[];
  onRefreshStatus: () => void;
  onRefreshNotebooks: () => void;
  onRelogin: (email: string) => void;
  onCleanupNotebooks: () => void;
  onCleanupLocalPdfs: () => void;
}

// ─── Component ───────────────────────────────────────────────

export function SettingsTab({
  settingsExpanded, onToggleSettings,
  notebookStatus, notebooks,
  onRefreshStatus, onRefreshNotebooks, onRelogin,
  onCleanupNotebooks, onCleanupLocalPdfs,
}: SettingsTabProps) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white overflow-hidden">
      <button onClick={onToggleSettings}
        className="flex w-full items-center justify-between px-5 py-3 text-left hover:bg-zinc-50">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <Settings className="h-4 w-4 text-zinc-500" />④ 系统设置
        </div>
        {settingsExpanded ? <ChevronDown className="h-4 w-4 text-zinc-400" /> : <ChevronRight className="h-4 w-4 text-zinc-400" />}
      </button>
      {settingsExpanded && (
        <div className="border-t border-zinc-100 p-5 space-y-4">
          <NotebookLMStatusCard status={notebookStatus} onRefresh={onRefreshStatus} onRelogin={onRelogin} />
          <PdfPathCard />
          <NotebookTable notebooks={notebooks} onRefresh={onRefreshNotebooks} />
          <div className="flex flex-wrap gap-3">
            <button onClick={onCleanupNotebooks} className="inline-flex h-9 items-center gap-1.5 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50"><Trash2 className="h-4 w-4" />清理 Notebook</button>
            <button onClick={onCleanupLocalPdfs} className="inline-flex h-9 items-center gap-1.5 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50"><Trash2 className="h-4 w-4" />清理本地 PDF</button>
            <button onClick={() => { onRefreshStatus(); onRefreshNotebooks(); }} className="inline-flex h-9 items-center gap-1.5 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50"><RefreshCw className="h-4 w-4" />刷新状态</button>
          </div>
        </div>
      )}
    </section>
  );
}

// ─── NotebookLMStatusCard ────────────────────────────────────

function NotebookLMStatusCard({
  status, onRefresh, onRelogin,
}: {
  status: NotebookLMStatus | null;
  onRefresh: () => void;
  onRelogin: (email: string) => void;
}) {
  const authenticated = Boolean(status?.authenticated);
  const currentAccount = status?.current_account || (status?.accounts?.find(item => item.is_default)?.email ?? '');

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <UserCircle2 className="h-4 w-4 text-zinc-500" />
            <h2 className="text-sm font-semibold">NotebookLM 账号</h2>
            <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${authenticated ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : 'border-amber-200 bg-amber-50 text-amber-700'}`}>
              {authenticated ? '已认证' : '未认证'}
            </span>
          </div>
          <p className="text-sm text-zinc-500">复用本机 Chrome Cookie 登录 NotebookLM。可在这里切换账号并重新登录，查看 KenRadar 创建的笔记本列表。</p>
        </div>
        <button onClick={onRefresh} className="inline-flex h-9 items-center justify-center gap-2 rounded border border-zinc-200 px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-50">
          <RefreshCw className="h-4 w-4" />刷新账号状态
        </button>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatusItem label="当前账号" value={currentAccount || '未记录'} mono />
        <StatusItem label="最近登录" value={status?.last_login_at || '未记录'} />
        <StatusItem label="浏览器" value={status?.browser || 'chrome'} />
        <StatusItem label="认证详情" value={status?.auth_detail || '未获取'} />
      </div>

      {status?.profile_dir && (
        <div className="mt-3 rounded border border-zinc-100 bg-zinc-50 px-3 py-2 font-mono text-xs text-zinc-500">
          Profile: {status.profile_dir}
        </div>
      )}

      {status?.inspect_error && (
        <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
          Chrome 账号读取异常：{status.inspect_error}
        </div>
      )}

      <div className="mt-4 space-y-3">
        <div className="text-sm font-medium text-zinc-700">可用 Google 账号</div>
        {status?.accounts?.length ? (
          <div className="space-y-2">
            {status.accounts.map(account => {
              const isCurrent = Boolean(currentAccount && currentAccount === account.email);
              return (
                <div key={account.email} className="flex flex-col gap-3 rounded border border-zinc-100 bg-zinc-50 px-3 py-3 md:flex-row md:items-center md:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-zinc-900">{account.email}</span>
                      {account.is_default && <span className="rounded border border-zinc-200 bg-white px-2 py-0.5 text-xs text-zinc-600">Chrome 默认</span>}
                      {isCurrent && <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">当前使用</span>}
                    </div>
                    <div className="mt-1 font-mono text-xs text-zinc-500">{account.browser_profile || 'Chrome'}</div>
                  </div>
                  <button onClick={() => onRelogin(account.email)}
                    className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded border border-zinc-200 bg-white px-3 text-sm font-semibold text-zinc-700 hover:bg-zinc-100">
                    <LogIn className="h-4 w-4" />重新登录
                  </button>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="rounded border border-zinc-100 bg-zinc-50 px-3 py-4 text-sm text-zinc-500">暂未识别到本机 Chrome 中的 Google 账号。</div>
        )}
      </div>
    </section>
  );
}

// ─── PdfPathCard ─────────────────────────────────────────────

function PdfPathCard() {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5">
      <div className="flex items-center gap-2">
        <FolderOpen className="h-4 w-4 text-zinc-500" />
        <h2 className="text-sm font-semibold">本地 PDF 存储</h2>
      </div>
      <p className="mt-2 text-sm text-zinc-500">PDF 下载目录：</p>
      <code className="mt-1 block rounded border border-zinc-100 bg-zinc-50 px-3 py-2 font-mono text-xs text-zinc-600">
        data/company_research/downloads/announcements/&lt;stock&gt;/&lt;year&gt;/
      </code>
      <p className="mt-2 text-xs text-zinc-400">
        系统在下载 PDF 时会自动检查文件有效性（%PDF 头部标记、文件大小 &gt; 20KB）。若上传 NotebookLM 失败，可在此目录抽查 PDF 文件是否可正常打开。
      </p>
    </section>
  );
}

// ─── NotebookTable ───────────────────────────────────────────

function badgeClass(val: string) {
  if (['deleted', 'delete_failed'].includes(val)) return 'border-red-200 bg-red-50 text-red-700';
  if (val === 'active') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  return 'border-zinc-200 bg-zinc-50 text-zinc-600';
}

function NotebookTable({ notebooks, onRefresh }: { notebooks: NotebookLMNotebook[]; onRefresh: () => void }) {
  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Book className="h-4 w-4 text-zinc-500" />
          <h2 className="text-sm font-semibold">KenRadar 创建的笔记本</h2>
          <span className="rounded border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs text-zinc-600">{notebooks.length} 个</span>
        </div>
        <button onClick={onRefresh} className="inline-flex h-8 items-center justify-center gap-1.5 rounded border border-zinc-200 px-3 text-xs font-semibold text-zinc-700 hover:bg-zinc-50">
          <RefreshCw className="h-3.5 w-3.5" />刷新
        </button>
      </div>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-zinc-50 text-xs text-zinc-500">
            <tr>
              <th className="px-3 py-2 font-semibold">股票</th>
              <th className="px-3 py-2 font-semibold">Notebook ID</th>
              <th className="px-3 py-2 font-semibold">来源数</th>
              <th className="px-3 py-2 font-semibold">已就绪</th>
              <th className="px-3 py-2 font-semibold">已回答</th>
              <th className="px-3 py-2 font-semibold">已保存</th>
              <th className="px-3 py-2 font-semibold">状态</th>
              <th className="px-3 py-2 font-semibold">创建时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {notebooks.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-sm text-zinc-400">暂无 KenRadar 创建的笔记本记录。</td></tr>
            ) : (
              notebooks.map(item => (
                <tr key={item.id}>
                  <td className="px-3 py-2.5">
                    <span className="font-mono font-semibold">{item.symbol}</span>
                    {item.stock_name && <span className="ml-1.5 text-xs text-zinc-500">{item.stock_name}</span>}
                  </td>
                  <td className="max-w-[240px] truncate px-3 py-2.5 font-mono text-xs text-zinc-600" title={item.notebook_id}>{item.notebook_id}</td>
                  <td className="px-3 py-2.5">{item.source_count}</td>
                  <td className="px-3 py-2.5">{item.ready_source_count}</td>
                  <td className="px-3 py-2.5">{item.question_answered}</td>
                  <td className="px-3 py-2.5">{item.question_saved}</td>
                  <td className="px-3 py-2.5">
                    <span className={`rounded border px-2 py-0.5 text-xs font-semibold ${badgeClass(item.notebook_status || item.delete_status || '')}`}>
                      {item.delete_status === 'deleted' ? '已删除' : item.notebook_status || '-'}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-xs text-zinc-500">{item.created_at ? item.created_at.slice(0, 16) : '-'}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
