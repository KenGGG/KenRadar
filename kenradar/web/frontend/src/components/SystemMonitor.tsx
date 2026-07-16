/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useState, useMemo } from 'react';
import { 
  Activity, 
  RotateCw, 
  Send, 
  AlertTriangle, 
  Terminal, 
  RefreshCw,
  Search, 
  Copy, 
  Eye, 
  Power,
  CheckCircle2,
  Inbox
} from 'lucide-react';
import { PushRecord, SystemLog, AlertRecord, SystemInfo } from '../types';

export type SystemMonitorTab = 'status' | 'push' | 'alerts' | 'logs';

interface SystemMonitorProps {
  pushRecords: PushRecord[];
  logs: SystemLog[];
  alerts: AlertRecord[];
  system: SystemInfo;
  rebootWebUI: () => void;
  triggerManualScan: () => void;
  initialTab?: SystemMonitorTab;
  hideHeader?: boolean;
  hideTabs?: boolean;
}

export default function SystemMonitor({
  pushRecords,
  logs,
  alerts,
  system,
  rebootWebUI,
  triggerManualScan,
  initialTab,
  hideHeader = false,
  hideTabs = false
}: SystemMonitorProps) {
  const [activeTab, setActiveTab] = useState<SystemMonitorTab>(() => {
    if (initialTab) return initialTab;
    const pathname = window.location.pathname;
    if (pathname.includes('/pushes')) return 'push';
    if (pathname.includes('/alerts')) return 'alerts';
    if (pathname.includes('/runtime')) return 'logs';
    return 'status';
  });

  useEffect(() => {
    if (initialTab) setActiveTab(initialTab);
  }, [initialTab]);

  // Logs filters
  const [logLevelFilter, setLogLevelFilter] = useState<'all' | 'info' | 'warn' | 'error' | 'debug'>('all');
  const [logSearchQuery, setLogSearchQuery] = useState('');

  // Feishu inspect detail tracking ID
  const [inspectedPushId, setInspectedPushId] = useState<string | null>(null);

  // Filter logs dynamically
  const filteredLogs = useMemo(() => {
    return logs.filter(l => {
      const matchLevel = logLevelFilter === 'all' || l.level === logLevelFilter;
      const matchSearch = l.message.toLowerCase().includes(logSearchQuery.toLowerCase()) || 
                          l.module.toLowerCase().includes(logSearchQuery.toLowerCase());
      return matchLevel && matchSearch;
    });
  }, [logs, logLevelFilter, logSearchQuery]);

  const activeAlerts = alerts;

  const runReboot = () => {
    if (window.confirm("确定安全重新运行 Web 端口服务吗？（连接缓存将被短暂冲刷）")) {
      rebootWebUI();
      alert("服务进程重启指令已投递，正在同步端口缓存中。");
    }
  };

  return (
    <div className="space-y-8 animate-fade-in">
      
      {/* Top system monitor controller row */}
      {!hideHeader && (
      <div className="border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">运行概览</h1>
          <p className="text-zinc-500 dark:text-[var(--text-muted)] font-sans text-sm mt-1">查看系统状态、飞书推送记录、告警和运行日志。</p>
        </div>

        {/* Global manuals */}
        <div className="flex items-center space-x-3 shrink-0">
          <button
            onClick={() => {
              triggerManualScan();
              alert("已向后台发起手动全量检测更新请求。");
            }}
            className="flex items-center space-x-1.5 px-3 py-2 border border-zinc-200 dark:border-[var(--surface-border)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] rounded text-xs font-sans font-medium text-zinc-700 dark:text-[var(--text-secondary)] transition cursor-pointer"
          >
            <RotateCw className="w-3.5 h-3.5" />
            <span>全量检测</span>
          </button>

          <button
            onClick={runReboot}
            className="flex items-center space-x-1.5 px-3 py-2 bg-red-50 dark:bg-[var(--danger-bg)] text-red-600 dark:text-[var(--danger)] border border-red-100/60 dark:border-[var(--danger-border)] hover:bg-red-100 dark:hover:bg-[var(--danger-bg)] rounded text-xs font-sans font-medium transition cursor-pointer"
          >
            <Power className="w-3.5 h-3.5" />
            <span>Web 重新启动</span>
          </button>
        </div>
      </div>
      )}

      {/* Main navigation controls */}
      {!hideTabs && (
      <div className="flex border-b border-zinc-200 dark:border-[var(--surface-border)] space-x-6">
        <button
          onClick={() => setActiveTab('status')}
          className={`pb-3 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
            activeTab === 'status' ? 'text-zinc-950 dark:text-[var(--text-primary)] font-bold' : 'text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-700 dark:hover:text-[var(--text-secondary)]'
          }`}
        >
          <span>系统状态</span>
          {activeTab === 'status' && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--text-primary)] rounded" />}
        </button>
        <button
          onClick={() => setActiveTab('push')}
          className={`pb-3 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
            activeTab === 'push' ? 'text-zinc-950 dark:text-[var(--text-primary)] font-bold' : 'text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-700 dark:hover:text-[var(--text-secondary)]'
          }`}
        >
          <span>飞书推送日志</span>
          {activeTab === 'push' && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--text-primary)] rounded" />}
        </button>
        <button
          onClick={() => setActiveTab('alerts')}
          className={`pb-3 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
            activeTab === 'alerts' ? 'text-zinc-950 dark:text-[var(--text-primary)] font-bold' : 'text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-700 dark:hover:text-[var(--text-secondary)]'
          }`}
        >
          <span>系统告警盘</span>
          {activeTab === 'alerts' && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--text-primary)] rounded" />}
        </button>
        <button
          onClick={() => setActiveTab('logs')}
          className={`pb-3 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
            activeTab === 'logs' ? 'text-zinc-950 dark:text-[var(--text-primary)] font-bold' : 'text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-700 dark:hover:text-[var(--text-secondary)]'
          }`}
        >
          <span>运行日志流 (Log)</span>
          {activeTab === 'logs' && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 dark:bg-[var(--text-primary)] rounded" />}
        </button>
      </div>
      )}

      {activeTab === 'status' && (
        <div className="space-y-6 animate-fade-in">
          {/* Background task status */}
          {system.background_task?.running && (
            <div className="bg-blue-50 dark:bg-[var(--info-bg)] border border-blue-100 dark:border-[var(--info-border)] rounded-lg p-4 space-y-3">
              <div className="flex items-center space-x-4">
                <div className="w-3 h-3 bg-blue-500 dark:bg-[var(--info)] rounded-full animate-pulse shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-sans font-semibold text-blue-900 dark:text-[var(--info)]">{system.background_task.message}</p>
                  <p className="text-xs font-mono text-blue-700 dark:text-[var(--info)] mt-0.5">
                    开始于 {system.background_task.started_at}
                  </p>
                </div>
              </div>
              {system.background_task.progress && (
                <div className="space-y-2">
                  <div className="flex justify-between text-xs font-mono text-blue-700 dark:text-[var(--info)]">
                    <span>{system.background_task.progress.message}</span>
                    <span>{system.background_task.progress.current}/{system.background_task.progress.total}</span>
                  </div>
                  <div className="w-full bg-blue-200 dark:bg-[var(--info-bg)] rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-blue-600 dark:bg-[var(--info)] h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${Math.round(
                          (system.background_task.progress.current /
                            system.background_task.progress.total) *
                            100
                        )}%`,
                      }}
                    />
                  </div>
                  <div className="flex justify-between text-[10px] font-mono text-blue-500 dark:text-[var(--info)]">
                    <span>阶段: {system.background_task.progress.stage}</span>
                    <span>进度: {Math.round(
                      (system.background_task.progress.current /
                        system.background_task.progress.total) *
                        100
                    )}%</span>
                  </div>
                </div>
              )}
            </div>
          )}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 animate-fade-in">
          {[
            { label: '调度状态', value: system.health.schedule || '未知', icon: Activity },
            { label: '下次运行', value: system.health.next_run || '暂无', icon: RotateCw },
            { label: '磁盘剩余', value: system.health.disk_free || '未知', icon: Inbox },
            { label: '磁盘使用率', value: system.health.disk_used_percent || '未知', icon: Terminal },
            { label: '推送成功率', value: system.health.push_rate || '暂无推送', icon: Send },
            { label: '需关注告警', value: system.health.alert_attention_label || `${system.health.alert_attention || 0} 条`, icon: AlertTriangle },
            { label: '历史告警', value: system.health.alerts || `${activeAlerts.length} 条`, icon: AlertTriangle },
            { label: 'GPU', value: `${system.gpu_label} · ${system.gpu_percent ?? '-'}%`, icon: Activity },
            { label: 'Whisper', value: system.whisper_model, icon: RefreshCw }
          ].map((item) => {
            const Icon = item.icon;
            return (
              <div key={item.label} className="bg-white dark:bg-[var(--surface)] border border-zinc-150 dark:border-[var(--surface-border)] rounded-lg p-4 shadow-2xs">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] font-mono uppercase">{item.label}</span>
                  <Icon className="w-4 h-4 text-zinc-400 dark:text-[var(--text-muted)]" />
                </div>
                <div className="text-sm font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] break-words">{item.value}</div>
              </div>
            );
          })}
        </div>
            </div>
          )}

      {/* TAB SUB-GRID 2: Feishu Card Notification push logs */}
      {activeTab === 'push' && (
        <div className="space-y-5 animate-fade-in">
          
          <div className="flex justify-between items-center pb-2">
            <h3 className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm tracking-tight uppercase text-zinc-500 dark:text-[var(--text-muted)] font-mono">飞书 Card/Text 历史推送记录</h3>
            <span className="text-xs font-sans text-zinc-400 dark:text-[var(--text-muted)]">已记录推送日志 {pushRecords.length} 条</span>
          </div>

          {pushRecords.length === 0 ? (
            <div className="p-12 border border-dashed border-zinc-200 dark:border-[var(--surface-border)] rounded-lg text-center text-zinc-400 dark:text-[var(--text-muted)] font-sans">
              <Send className="w-8 h-8 mx-auto text-zinc-300 dark:text-[var(--text-muted)] stroke-1 mb-2" />
              <p className="text-sm">暂未保存任何飞书自动推送记录。</p>
            </div>
          ) : (
            <div className="border border-zinc-150 dark:border-[var(--surface-border)] rounded-lg overflow-hidden bg-white dark:bg-[var(--surface)]">
              <div className="divide-y divide-zinc-150 dark:divide-[var(--surface-border)]">
                {pushRecords.map((rec) => {
                  const isInspected = inspectedPushId === rec.id;

                  return (
                    <div key={rec.id} className="p-4 hover:bg-zinc-50/20 dark:hover:bg-[var(--surface-muted)] transition space-y-3">
                      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
                        <div className="space-y-0.5">
                          <div className="flex items-center space-x-2 flex-wrap">
                            <span className="text-xs font-sans font-medium text-purple-600 dark:text-[var(--accent)] bg-purple-50 dark:bg-[var(--surface-muted)] px-2 py-0.5 rounded">
                              {rec.push_type.toUpperCase()} 双工推送
                            </span>
                            <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-mono">ID: {rec.id}</span>
                            <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-mono">aweme: {rec.aweme_id}</span>
                          </div>
                          <h4 className="text-sm font-sans font-bold text-zinc-900 dark:text-[var(--text-primary)] leading-snug pt-1">{rec.title}</h4>
                        </div>

                        <div className="flex items-center space-x-3.5 shrink-0 select-none">
                          <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-mono">{rec.sent_at}</span>
                          <span className={`text-xs font-sans font-semibold px-2 py-0.5 rounded ${
                            rec.status === 'success' ? 'text-emerald-600 dark:text-[var(--success)] bg-emerald-50 dark:bg-[var(--success-bg)]' : 'text-red-650 dark:text-[var(--danger)] bg-red-50 dark:bg-[var(--danger-bg)]'
                          }`}>
                            {rec.status === 'success' ? '发送完成' : '发送失败'}
                          </span>
                          <button
                            onClick={() => setInspectedPushId(isInspected ? null : rec.id)}
                            className="p-1 text-zinc-400 dark:text-[var(--text-muted)] hover:text-zinc-900 dark:hover:text-[var(--text-primary)] transition flex items-center space-x-1 font-sans text-xs"
                          >
                            <Eye className="w-4 h-4" />
                            <span>{isInspected ? '隐藏数据' : '检视 Payload'}</span>
                          </button>
                        </div>
                      </div>

                      {isInspected && (
                        <div className="bg-zinc-950 dark:bg-[var(--surface-muted)] rounded-md p-4 border border-zinc-800 dark:border-[var(--surface-border)] font-mono text-zinc-350 dark:text-[var(--text-secondary)] text-[11px] leading-relaxed relative overflow-x-auto whitespace-pre-wrap animate-fade-in shadow-inner max-h-60">
                          <button
                            onClick={() => {
                              navigator.clipboard.writeText(rec.payload);
                              alert("飞书 Card Payload 成功复制到剪载板。");
                            }}
                            className="absolute right-3 top-3 p-1.5 bg-zinc-900 dark:bg-[var(--surface)] hover:bg-zinc-850 dark:hover:bg-[var(--surface-muted)] border border-zinc-800 dark:border-[var(--surface-border)] text-zinc-400 dark:text-[var(--text-muted)] hover:text-white dark:hover:text-[var(--text-primary)] rounded"
                            title="复制 Payload"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                          {rec.payload}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

        </div>
      )}

      {/* TAB SUB-GRID 3: Alert alerts */}
      {activeTab === 'alerts' && (
        <div className="space-y-4 animate-fade-in">
          <div className="flex justify-between items-center pb-2">
            <h3 className="font-sans font-semibold text-zinc-900 dark:text-[var(--text-primary)] text-sm tracking-tight uppercase text-zinc-500 dark:text-[var(--text-muted)] font-mono">系统核心告警汇总</h3>
            <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-sans">抓取, 转译, 飞书推送高风险故障</span>
          </div>

          {activeAlerts.length === 0 ? (
            <div className="p-16 border border-dashed border-zinc-200 dark:border-[var(--surface-border)] rounded-lg text-center text-zinc-400 dark:text-[var(--text-muted)] font-sans">
              <CheckCircle2 className="w-10 h-10 text-emerald-500 dark:text-[var(--success)] mx-auto stroke-1 mb-2.5" />
              <p className="text-sm font-semibold">暂无系统告警</p>
              <p className="text-xs text-zinc-400 dark:text-[var(--text-muted)] mt-1">当前没有需要处理的系统告警记录。</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {activeAlerts.map((alt, index) => (
                <div
                  key={index}
                  className={`p-5 rounded-lg border flex items-start space-x-4 ${
                    alt.level === 'critical'
                      ? 'bg-red-50/30 dark:bg-[var(--danger-bg)] border-red-150 dark:border-[var(--danger-border)] text-red-950 dark:text-[var(--danger)]'
                      : 'bg-amber-50/20 dark:bg-[var(--warning-bg)] border-amber-150 dark:border-[var(--warning-border)] text-amber-950 dark:text-[var(--warning)]'
                  }`}
                >
                  <AlertTriangle className={`w-5 h-5 mt-0.5 shrink-0 ${
                    alt.level === 'critical' ? 'text-red-600 dark:text-[var(--danger)]' : 'text-amber-500 dark:text-[var(--warning)]'
                  }`} />
                  <div className="space-y-1.5">
                    <div className="flex items-center space-x-2.5">
                      <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded font-black uppercase ${
                        alt.level === 'critical' ? 'bg-red-100 dark:bg-[var(--danger-bg)] text-red-700 dark:text-[var(--danger)]' : 'bg-amber-100 dark:bg-[var(--warning-bg)] text-amber-700 dark:text-[var(--warning)]'
                      }`}>
                        {alt.level === 'critical' ? '严重' : '警告'}
                      </span>
                      <span className="text-xs text-zinc-400 dark:text-[var(--text-muted)] font-mono">模块：[{alt.module}]</span>
                    </div>

                    <h4 className="font-sans font-bold text-sm text-zinc-900 dark:text-[var(--text-primary)] leading-snug">{alt.title}</h4>
                    <p className="font-mono text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-medium leading-relaxed">{alt.desc}</p>
                    <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] font-mono block">触发时刻：{alt.time}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

        </div>
      )}

      {/* TAB SUB-GRID 4: Logs terminal streams (Section 3.6) */}
      {activeTab === 'logs' && (
        <div className="space-y-4 animate-fade-in">
          
          {/* Logs terminal control panels */}
          <div className="p-4 bg-zinc-50 dark:bg-[var(--surface-muted)] border border-zinc-150 dark:border-[var(--surface-border)] rounded-lg flex flex-col sm:flex-row items-center justify-between gap-4">

            {/* Level selection option */}
            <div className="flex items-center space-x-2">
              <span className="text-xs font-mono text-zinc-400 dark:text-[var(--text-muted)]">日志等级:</span>
              <div className="flex border border-zinc-205 dark:border-[var(--surface-border)] p-0.5 rounded bg-white dark:bg-[var(--surface)]">
                {[
                  { id: 'all', name: 'ALL' },
                  { id: 'info', name: 'INFO' },
                  { id: 'warn', name: 'WARN' },
                  { id: 'error', name: 'ERROR' }
                ].map((l) => (
                  <button
                    key={l.id}
                    onClick={() => setLogLevelFilter(l.id as any)}
                    className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded-sm transition cursor-pointer ${
                      logLevelFilter === l.id
                        ? 'bg-zinc-900 dark:bg-[var(--surface-muted)] text-white dark:text-[var(--text-primary)]'
                        : 'text-zinc-500 dark:text-[var(--text-muted)] hover:text-zinc-905 dark:hover:text-[var(--text-primary)]'
                    }`}
                  >
                    {l.name}
                  </button>
                ))}
              </div>
            </div>

            {/* Micro search */}
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-zinc-400 dark:text-[var(--text-muted)]" />
              <input
                type="text"
                placeholder="检索日志包含字符..."
                value={logSearchQuery}
                onChange={(e) => setLogSearchQuery(e.target.value)}
                className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-250 dark:border-[var(--surface-border)] rounded pl-8 pr-3 py-1.5 text-xs font-mono focus:outline-none focus:border-zinc-900 dark:focus:border-[var(--text-primary)]"
              />
            </div>

          </div>

          {/* Monospace Code Editor block */}
          <div className="p-5 rounded-lg bg-zinc-950 dark:bg-[var(--surface-muted)] border border-zinc-850 dark:border-[var(--surface-border)] shadow-inner h-[500px] overflow-y-auto flex flex-col-reverse justify-end font-mono text-xs text-zinc-300 dark:text-[var(--text-secondary)] leading-relaxed select-text">
            {filteredLogs.length === 0 ? (
              <div className="py-20 text-center text-zinc-500 dark:text-[var(--text-muted)] font-mono space-y-1 select-none">
                <Terminal className="w-8 h-8 mx-auto text-zinc-700 dark:text-[var(--text-muted)] stroke-1 mb-2" />
                <p>--- NO MATCHING LOG ENTRIES FOUND ---</p>
                <p className="text-[10px] dark:text-[var(--text-muted)]">调高检索尺度或点击顶部 “全量检测” 使大盘日志更新流动。</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                {filteredLogs.map((log) => {

                  const isInfo = log.level === 'info';
                  const isWarn = log.level === 'warn';
                  const isError = log.level === 'error';

                  return (
                    <div key={log.id} className="hover:bg-zinc-900/40 dark:hover:bg-[var(--surface)] p-1 rounded font-mono flex items-start space-x-2 justify-between">
                      <div className="flex-1">
                        <span className="text-zinc-500 dark:text-[var(--text-muted)] mr-2.5">[{log.timestamp}]</span>
                        <span className={`font-bold mr-2 ${
                          isInfo ? 'text-emerald-400 dark:text-[var(--success)]' :
                          isWarn ? 'text-amber-400 dark:text-[var(--warning)]' : 'text-red-500 dark:text-[var(--danger)]'
                        }`}>
                          [{log.level.toUpperCase()}]
                        </span>
                        <span className="text-blue-400 dark:text-[var(--info)] mr-2">[{log.module}]</span>
                        <span className="text-zinc-200 dark:text-[var(--text-primary)]">{log.message}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] text-center font-mono py-1">
            * 默认限制展示最近 300 条底座运行管道。完整日志路径：{system.log_path}
          </div>

        </div>
      )}

    </div>
  );
}
