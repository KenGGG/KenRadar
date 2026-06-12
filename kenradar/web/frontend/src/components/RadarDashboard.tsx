/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { 
  Plus, 
  RotateCw, 
  ChevronRight, 
  Sparkles, 
  Play, 
  CheckCircle2, 
  AlertTriangle, 
  Inbox,
  ArrowRight
} from 'lucide-react';
import { VideoContent, ResearchTask, MonitorSource } from '../types';

interface RadarDashboardProps {
  videos: VideoContent[];
  tasks: ResearchTask[];
  sources: MonitorSource[];
  navigateTo: (page: string, id: string | null) => void;
  triggerManualScan: () => void;
  testLatest: () => void;
}

function conclusionFor(video: VideoContent) {
  if (video.one_sentence_conclusion) return video.one_sentence_conclusion;
  const lines = (video.summary_markdown || '').split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    if (/^>\s*\[!summary\]/i.test(lines[index].trim())) {
      const parts: string[] = [];
      const inline = lines[index].replace(/^>\s*\[!summary\]\s*/i, '').trim();
      if (inline) parts.push(inline);
      while (index + 1 < lines.length && lines[index + 1].trim().startsWith('>')) {
        index += 1;
        parts.push(lines[index].trim().replace(/^>\s?/, ''));
      }
      return parts.join(' ').trim();
    }
  }
  return '';
}

function summaryFor(video: VideoContent) {
  if (video.brief_summary) return video.brief_summary;
  return (video.summary_markdown || '')
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
    .replace(/^#+\s+/gm, '')
    .replace(/^>\s*\[![^\]]+\]\s*/gm, '')
    .replace(/^>\s?/gm, '')
    .trim()
    .slice(0, 180);
}

function relativeTime(value?: string) {
  if (!value) return '未检查';
  const date = new Date(String(value).replace(/-/g, '/'));
  if (Number.isNaN(date.getTime())) return String(value);
  const diff = Date.now() - date.getTime();
  if (diff < 60 * 1000) return '刚刚';
  const minutes = Math.floor(diff / (60 * 1000));
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function isToday(value?: string) {
  if (!value) return false;
  const date = new Date(String(value).replace(/-/g, '/'));
  if (Number.isNaN(date.getTime())) return false;
  const now = new Date();
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
}

export default function RadarDashboard({
  videos,
  tasks,
  sources,
  navigateTo,
  triggerManualScan,
  testLatest
}: RadarDashboardProps) {

  // Logic to calculate stats
  const todayVideos = videos.filter(v => isToday(v.created_at) || isToday(v.updated_at));
  const todayReadable = todayVideos.filter(v => v.status === 'completed').length;
  const failedCount = videos.filter(v => v.status === 'failed').length;
  
  const highPriorityVideos = videos
    .filter(v => v.status === 'completed' && (v.rating >= 7.5 || v.recommend_action === 'push' || v.recommend_action === 'research'))
    .slice(0, 8);
  const failedOverviewList = videos.filter(v => v.status === 'failed').slice(0, 3);
  const activeSources = sources.filter(s => s.status === 'enabled').length;

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Upper Welcome Header banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-zinc-200 pb-5 gap-4">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900">今日雷达</h1>
          <p className="text-zinc-500 font-sans text-sm mt-1">今天新增、值得阅读和必须处理的内容入口。</p>
        </div>
        <div className="flex items-center space-x-3">
          <button
            id="test_latest_btn"
            onClick={testLatest}
            className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white hover:bg-blue-700 rounded-lg font-sans text-sm font-semibold transition cursor-pointer shadow-xs"
          >
            <Sparkles className="w-4 h-4 text-white" />
            <span>测试最新</span>
          </button>
          <button
            id="manual_scan_btn"
            onClick={triggerManualScan}
            className="flex items-center space-x-2 px-4 py-2 border border-zinc-200 bg-white hover:bg-zinc-50 rounded-lg font-sans text-sm font-semibold text-zinc-700 transition cursor-pointer shadow-2xs"
          >
            <RotateCw className="w-4 h-4 text-zinc-500" />
            <span>手动检测</span>
          </button>
        </div>
      </div>

      {/* Grid Layout conforming to Section 3.1 (Left Core, Right Controls) */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        
        {/* Left Hand Core Information: High Value Queue & Stats */}
        <div className="xl:col-span-2 space-y-8">
          
          {/* Internal Stats Counter widgets */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <div className="p-3 bg-white rounded-lg border border-zinc-150 shadow-2xs flex flex-col justify-between">
              <span className="text-zinc-500 text-xs font-sans">今日新增</span>
              <span className="text-xl font-semibold font-sans text-zinc-900 mt-2">{todayVideos.length} 条</span>
            </div>
            <div className="p-3 bg-white rounded-lg border border-zinc-150 shadow-2xs flex flex-col justify-between">
              <span className="text-zinc-500 text-xs font-sans">今日可读</span>
              <span className="text-xl font-semibold font-sans text-emerald-600 mt-2">{todayReadable} 篇</span>
            </div>
            <div className={`p-3 rounded-lg border flex flex-col justify-between ${failedCount > 0 ? 'bg-red-50/40 border-red-150' : 'bg-white border-zinc-150 shadow-2xs'}`}>
              <span className={`text-xs font-sans ${failedCount > 0 ? 'text-red-700' : 'text-zinc-500'}`}>必须处理</span>
              <span className={`text-xl font-semibold font-sans mt-2 ${failedCount > 0 ? 'text-red-600' : 'text-zinc-900'}`}>{failedCount} 处</span>
            </div>
            <div className="p-3 bg-white rounded-lg border border-zinc-150 shadow-2xs flex flex-col justify-between">
              <span className="text-zinc-500 text-xs font-sans">活跃监控博主</span>
              <span className="text-xl font-semibold font-sans text-zinc-900 mt-2">{activeSources} 家</span>
            </div>
          </div>

          {/* Core high-value video highlight cards */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-sans font-medium text-zinc-900 flex items-center space-x-2">
                <span className="w-1.5 h-6 bg-blue-600 rounded-sm inline-block"></span>
                <span>今日重点内容</span>
              </h2>
              <button 
                onClick={() => navigateTo('archive', null)}
                className="text-xs text-zinc-500 hover:text-zinc-950 flex items-center space-x-1 transition font-sans"
              >
                <span>进入阅读库</span>
                <ChevronRight className="w-3 h-3" />
              </button>
            </div>

            {highPriorityVideos.length === 0 ? (
              <div className="p-8 border border-dashed border-zinc-200 bg-white rounded-xl text-center text-zinc-500 font-sans">
                <Inbox className="w-8 h-8 mx-auto text-zinc-300 stroke-1 mb-2" />
                <p className="text-sm">暂无重点推荐推送，试下“测试最新”快速模拟！</p>
              </div>
            ) : (
              <div className="space-y-3.5">
                {highPriorityVideos.map((video) => {
                  const conclusion = conclusionFor(video);
                  const summary = summaryFor(video);
                  return (
                  <div
                    key={video.id}
                    id={`high_priority_card_${video.id}`}
                    onClick={() => navigateTo('detail', video.id)}
                    className="group border border-zinc-200 p-5 rounded-xl bg-white hover:border-zinc-900 shadow-2xs hover:shadow-sm transition duration-200 cursor-pointer flex flex-col gap-4"
                  >
                    <div className="space-y-2 flex-1 animate-fade-in">
                      <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                        <span className="text-xs font-mono px-2 py-0.5 rounded-sm bg-zinc-100 text-zinc-650 font-medium">
                          {video.blogger}
                        </span>
                        <span className="text-xs font-sans font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-sm flex items-center space-x-1">
                          <span>★</span>
                          <span>{video.rating.toFixed(1)}分</span>
                        </span>
                        <span className="text-xs font-mono text-zinc-400">
                          {video.duration}
                        </span>
                      </div>
                      <h3 className="text-base font-sans font-semibold text-zinc-900 group-hover:text-blue-600 transition leading-snug">
                        {video.title}
                      </h3>
                      {conclusion && (
                        <p className="rounded-lg border border-blue-100 bg-blue-50/70 px-3 py-2 text-sm leading-6 text-blue-950 line-clamp-2">
                          {conclusion}
                        </p>
                      )}
                      {summary && (
                        <p className="text-sm leading-6 text-zinc-600 line-clamp-2">
                          {summary}
                        </p>
                      )}
                      <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
                        {video.tags.slice(0, 8).map((tag, idx) => (
                          <span key={idx} className="text-[10px] font-sans px-1.5 py-0.5 bg-zinc-50 text-zinc-500 rounded-sm border border-zinc-100">
                            #{tag}
                          </span>
                        ))}
                      </div>
                    </div>

                    <div className="flex items-center justify-end space-x-2 text-zinc-400 group-hover:text-zinc-900 transition shrink-0">
                      <span className="text-xs font-sans font-medium">查看 Obsidian 笔记</span>
                      <ArrowRight className="w-4 h-4 translate-x-0 group-hover:translate-x-1 transition-all" />
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Pending errors warning layout block */}
          <div className="space-y-4">
            <h2 className="text-lg font-sans font-medium text-zinc-900 flex items-center space-x-2">
              <span className="w-1.5 h-6 bg-red-600 rounded-sm inline-block"></span>
              <span>待处理失败任务概览</span>
            </h2>

            {failedOverviewList.length === 0 ? (
              <div className="p-5 bg-emerald-50/20 border border-emerald-150 rounded-xl flex items-center space-x-3 text-emerald-800 shadow-2xs">
                <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
                <span className="text-sm font-sans font-medium">一切正常！当前无积压失败或挂起中断的调度工序。</span>
              </div>
            ) : (
              <div className="border border-zinc-200 rounded-xl overflow-hidden bg-white shadow-2xs">
                <div className="divide-y divide-zinc-200">
                  {failedOverviewList.map((video) => (
                    <div 
                      key={video.id}
                      onClick={() => navigateTo('run', null)}
                      className="p-4 hover:bg-zinc-50 cursor-pointer transition flex items-start justify-between gap-4"
                    >
                      <div className="space-y-1 flex-1">
                        <div className="flex items-center space-x-2.5">
                          <span className="text-xs font-sans font-medium text-red-600 bg-red-50 px-2 py-0.5 rounded">
                            {video.failed_at_step === 'download' ? '下载阶段失败' :
                             video.failed_at_step === 'transcribe' ? 'Whisper 转写故障' :
                             video.failed_at_step === 'ai' ? 'Ollama 整理中断' : '飞书推送积企'}
                          </span>
                          <span className="text-xs text-zinc-500 font-mono">ID: {video.id}</span>
                        </div>
                        <h4 className="text-sm font-sans font-medium text-zinc-850 line-clamp-1">{video.title}</h4>
                        <p className="text-xs text-zinc-400 font-mono bg-zinc-50 px-2 py-1 rounded border border-zinc-100 mt-1.5 line-clamp-1 break-all">
                          {video.error_message}
                        </p>
                      </div>
                      <button className="text-xs text-zinc-500 hover:text-zinc-950 font-sans font-medium flex items-center shrink-0 pt-0.5 transition">
                        <span>去重试</span>
                        <ChevronRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
                <div className="bg-zinc-50 border-t border-zinc-100 px-4 py-2.5 text-center">
                  <button 
                    onClick={() => navigateTo('run', null)}
                    className="text-xs text-zinc-650 hover:text-zinc-950 font-sans font-semibold flex items-center justify-center mx-auto space-x-1.5 transition"
                  >
                    <span>进入运行中心处理失败</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            )}
          </div>

        </div>

        {/* Right Hand Column: Quick Actions & Navigation Shortcuts */}
        <div className="space-y-6">
          
          {/* Quick Tasks Control board */}
          <div className="p-6 border border-zinc-200 rounded-xl bg-white shadow-2xs space-y-4">
            <h3 className="font-sans font-semibold text-zinc-900 text-sm tracking-tight uppercase text-zinc-400 font-bold font-mono">快捷操作面板</h3>
            
            <div className="space-y-2.5 pt-1.5">
              <button
                id="quick_research_single_btn"
                onClick={() => navigateTo('research', null)}
                className="w-full flex items-center justify-between p-3.5 rounded-lg bg-neutral-50/50 border border-zinc-200 hover:border-zinc-950 transition duration-150 text-left cursor-pointer hover:shadow-2xs"
              >
                <div>
                  <span className="font-sans font-semibold text-zinc-900 text-sm block">单视频快速分析</span>
                  <span className="text-zinc-500 text-xs mt-0.5 block font-sans">输入短链或awemeID单线重跑</span>
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400" />
              </button>

              <button
                id="quick_research_blogger_btn"
                onClick={() => navigateTo('research', null)}
                className="w-full flex items-center justify-between p-3.5 rounded-lg bg-neutral-50/50 border border-zinc-200 hover:border-zinc-950 transition duration-150 text-left cursor-pointer hover:shadow-2xs"
              >
                <div>
                  <span className="font-sans font-semibold text-zinc-900 text-sm block">批量博主作品分析</span>
                  <span className="text-zinc-500 text-xs mt-0.5 block font-sans">按博主提取历史50条精细总结</span>
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400" />
              </button>

              <button
                id="quick_log_monitor_btn"
                onClick={() => navigateTo('run', null)}
                className="w-full flex items-center justify-between p-3.5 rounded-lg bg-neutral-50/50 border border-zinc-200 hover:border-zinc-950 transition duration-150 text-left cursor-pointer hover:shadow-2xs"
              >
                <div>
                  <span className="font-sans font-semibold text-zinc-900 text-sm block">运行中心</span>
                  <span className="text-zinc-500 text-xs mt-0.5 block font-sans">查看队列、异常和模型状态</span>
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-400" />
              </button>
            </div>
          </div>

          {/* Quick Source Checklist panel */}
          <div className="p-6 border border-zinc-200 rounded-xl bg-white shadow-2xs space-y-4">
            <h3 className="font-sans font-semibold text-zinc-900 text-sm tracking-tight uppercase text-zinc-400 font-bold font-mono">来源健康摘要</h3>
            
            <div className="space-y-3">
              {sources.slice(0, 3).map((src) => (
                <div key={src.id} className="flex items-center justify-between">
                  <div className="space-y-0.5 flex-1 min-w-0 pr-2">
                    <span className="font-sans font-medium text-zinc-800 text-sm block truncate">{src.name}</span>
                    <span className="text-zinc-400 text-xs font-mono block">已捕获 {src.total_captured} 内容 · {relativeTime(src.last_checked)}</span>
                  </div>
                  <span className={`text-[10px] font-sans px-2 py-0.5 rounded-full shrink-0 ${
                    src.status === 'enabled' 
                      ? 'bg-emerald-50 text-emerald-700 font-semibold md:px-2.5' 
                      : 'bg-zinc-100 text-zinc-400 font-medium'
                  }`}>
                    {src.status === 'enabled' ? '监控中' : '已暂停'}
                  </span>
                </div>
              ))}
              
              <div className="border-t border-zinc-100 pt-3 text-center">
                <button 
                  onClick={() => navigateTo('sources', null)}
                  className="text-xs text-zinc-500 hover:text-zinc-900 font-sans font-semibold flex items-center justify-center mx-auto space-x-1 transition"
                >
                  <span>管理全部监控来源</span>
                  <ChevronRight className="w-3 h-3" />
                </button>
              </div>
            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
