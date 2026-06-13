/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState } from 'react';
import { 
  Database, 
  ChevronDown,
  ChevronUp,
  Cpu,
  FileText,
  Loader2,
  Pause,
  Play,
  RotateCcw,
  Tags,
  XCircle
} from 'lucide-react';
import { BriefFile, ResearchTask } from '../types';

type ResearchJobPayload = {
  job?: Record<string, any> | null;
  items?: Record<string, any>[];
  pipeline?: Record<string, any>;
};

interface ResearchWorkspaceProps {
  tasks: ResearchTask[];
  runResearchTask: (type: 'single' | 'blogger', targetValue: string, forceRetry: boolean, limit?: number) => Promise<void>;
  controlResearchTask: (taskId: string, action: 'pause' | 'resume' | 'cancel' | 'restart') => void;
  loadResearchJob: (taskId: string) => Promise<ResearchJobPayload>;
  retryResearchFailed: (taskId: string) => void;
  briefs: BriefFile[];
}

export default function ResearchWorkspace({
  tasks,
  runResearchTask,
  controlResearchTask,
  loadResearchJob,
  retryResearchFailed,
  briefs
}: ResearchWorkspaceProps) {
  const [activeCenterTab, setActiveCenterTab] = useState<'tasks' | 'reports' | 'topics'>('tasks');
  // Tabs: single vs blogger inputs
  const [researchType, setResearchType] = useState<'single' | 'blogger'>('single');

  // Input states
  const [singleUrl, setSingleUrl] = useState('');
  const [bloggerHandle, setBloggerHandle] = useState('');
  const [scrapeLimit, setScrapeLimit] = useState(20);
  const [forceRetry, setForceRetry] = useState(false);

  // Accordion list open states
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>("task_1002"); // default expand 1002
  const [jobDetails, setJobDetails] = useState<Record<string, ResearchJobPayload>>({});
  const [loadingJobId, setLoadingJobId] = useState<string | null>(null);

  // Aggregated quantities
  const totalCount = tasks.length;
  const processingCount = tasks.filter(t => t.status === 'processing').length;
  const completedCount = tasks.filter(t => t.status === 'completed').length;
  const failedCount = tasks.filter(t => t.status === 'failed').length;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (researchType === 'single') {
      if (!singleUrl.trim()) return;
      runResearchTask('single', singleUrl, forceRetry);
      setSingleUrl('');
    } else {
      if (!bloggerHandle.trim()) return;
      const targetStr = `${bloggerHandle} (限制前 ${scrapeLimit} 条视频)`;
      runResearchTask('blogger', targetStr, forceRetry, scrapeLimit);
      setBloggerHandle('');
    }
  };

  const getStageColor = (currentStage: string | undefined, nodeStage: string, taskStatus: string) => {
    if (taskStatus === 'failed' && currentStage === nodeStage) return 'bg-red-50 text-red-655 border-red-200';
    if (taskStatus === 'completed') return 'bg-emerald-50 text-emerald-650 border-emerald-200';

    const stages = ['downloading', 'transcribing', 'summarizing', 'pushing', 'completed'];
    const currentIndex = stages.indexOf(currentStage || '');
    const nodeIndex = stages.indexOf(nodeStage);

    if (currentIndex > nodeIndex) {
      return 'bg-emerald-50 text-emerald-650 border-emerald-200'; // passed
    } else if (currentIndex === nodeIndex) {
      return 'bg-blue-50 text-blue-600 border-blue-200 font-semibold'; // active
    } else {
      return 'bg-zinc-50 text-zinc-400 border-zinc-150'; // queued
    }
  };

  const getStageLabel = (stage: string) => {
    switch(stage) {
      case 'downloading': return '视频抓取下载';
      case 'transcribing': return 'GPU 语音转录';
      case 'summarizing': return 'AI 内容整理';
      case 'pushing': return '飞书 Webhook';
      case 'completed': return '成功归档';
      default: return '等待调度';
    }
  };

  const showJobDetail = async (taskId: string) => {
    setExpandedTaskId(taskId);
    if (jobDetails[taskId]) return;
    setLoadingJobId(taskId);
    try {
      const detail = await loadResearchJob(taskId);
      setJobDetails(prev => ({ ...prev, [taskId]: detail }));
    } finally {
      setLoadingJobId(null);
    }
  };

  return (
    <div className="space-y-8 animate-fade-in">
      
      {/* Title block */}
      <div className="border-b border-zinc-200 pb-4 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900">研究中心</h1>
          <p className="text-zinc-500 font-sans text-sm mt-1">
            单视频快速分析、博主历史作品归档，以及后续研究报告和主题库管理。
          </p>
        </div>
        
      </div>

      <div className="flex border-b border-zinc-200 gap-6">
        {[
          { id: 'tasks', label: '研究任务', icon: Cpu },
          { id: 'reports', label: '研究报告', icon: FileText },
          { id: 'topics', label: '主题库', icon: Tags },
        ].map(tab => {
          const Icon = tab.icon;
          const active = activeCenterTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveCenterTab(tab.id as typeof activeCenterTab)}
              className={`pb-3 inline-flex items-center gap-1.5 text-sm font-sans font-semibold transition relative outline-none cursor-pointer ${
                active ? 'text-zinc-950' : 'text-zinc-400 hover:text-zinc-700'
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              <span>{tab.label}</span>
              {active && <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-zinc-950 rounded" />}
            </button>
          );
        })}
      </div>

      {activeCenterTab === 'reports' && (
        <section className="rounded-xl border border-zinc-200 bg-white shadow-2xs overflow-hidden">
          <div className="border-b border-zinc-100 px-5 py-4">
            <h2 className="text-sm font-semibold text-zinc-900">研究报告</h2>
            <p className="mt-1 text-xs text-zinc-500">只读展示已生成的研究简报和归档报告，不额外伪造数据。</p>
          </div>
          {briefs.length === 0 ? (
            <div className="p-16 text-center text-zinc-400 font-sans">
              <FileText className="w-10 h-10 mx-auto text-zinc-300 stroke-1 mb-3" />
              <p className="text-sm font-semibold text-zinc-900">暂无研究报告</p>
              <p className="text-xs mt-1">完成研究任务后，相关简报会出现在这里。</p>
            </div>
          ) : (
            <div className="divide-y divide-zinc-100">
              {briefs.map(brief => (
                <a key={brief.path} href={`/file?path=${encodeURIComponent(brief.path)}`} className="block px-5 py-4 hover:bg-zinc-50 transition">
                  <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                    <div className="min-w-0">
                      <div className="line-clamp-1 text-sm font-semibold text-zinc-950">{brief.title || brief.name}</div>
                      <div className="mt-1 text-xs text-zinc-500">{brief.item_count} 条内容 · {brief.status}</div>
                    </div>
                    <div className="shrink-0 text-xs font-mono text-zinc-400">{brief.created_at}</div>
                  </div>
                </a>
              ))}
            </div>
          )}
        </section>
      )}

      {activeCenterTab === 'topics' && (
        <div className="p-16 border border-dashed border-zinc-200 bg-white rounded-xl text-center text-zinc-400 font-sans shadow-2xs">
          <Tags className="w-10 h-10 mx-auto text-zinc-300 stroke-1 mb-3" />
          <p className="text-sm font-semibold text-zinc-900">暂无主题库数据</p>
          <p className="text-xs mt-1">主题库入口已预留，后续可承载从内容笔记沉淀出的长期主题资产。</p>
        </div>
      )}

      {/* Grid: Inputs Form Left, Tasks Monitor Right */}
      {activeCenterTab === 'tasks' && (
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* LEFT COLUMN: Input Control panel */}
        <div className="space-y-6">
          <div className="p-6 border border-zinc-200 rounded-xl bg-white space-y-5 shadow-2xs">
            <h3 className="font-sans font-semibold text-zinc-900 text-sm tracking-tight uppercase">创建研判任务</h3>
            
            {/* Form category picker */}
            <div className="grid grid-cols-2 gap-1 p-0.5 border border-zinc-200 rounded-lg bg-zinc-100">
              <button
                type="button"
                onClick={() => setResearchType('single')}
                className={`py-1.5 rounded-md text-xs font-sans font-semibold transition cursor-pointer ${
                  researchType === 'single' ? 'bg-white text-zinc-950 shadow-xs' : 'text-zinc-500 hover:text-zinc-900'
                }`}
              >
                单视频深度分析
              </button>
              <button
                type="button"
                onClick={() => setResearchType('blogger')}
                className={`py-1.5 rounded-md text-xs font-sans font-semibold transition cursor-pointer ${
                  researchType === 'blogger' ? 'bg-white text-zinc-950 shadow-xs' : 'text-zinc-500 hover:text-zinc-900'
                }`}
              >
                博主作品批量分析
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              {researchType === 'single' ? (
                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 font-sans block">输入目标抖音地址 / 短链 / awemeID</label>
                  <input
                    type="text"
                    required
                    placeholder="例如：https://v.douyin.com/xyzB/"
                    value={singleUrl}
                    onChange={(e) => setSingleUrl(e.target.value)}
                    className="w-full bg-white border border-zinc-200 rounded-lg px-3.5 py-2 text-sm font-sans focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                  />
                  <span className="text-[10px] text-zinc-450 font-sans block leading-relaxed">
                    系统将自动解析包含的短链，并由 Downloader 抓取无水印源流。
                  </span>
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <label className="text-xs text-zinc-500 font-sans block">博主主页分享地址 / 博主唯一代号</label>
                    <input
                      type="text"
                      required
                      placeholder="例如：AI创投派峰哥"
                      value={bloggerHandle}
                      onChange={(e) => setBloggerHandle(e.target.value)}
                      className="w-full bg-white border border-zinc-200 rounded-lg px-3.5 py-2 text-sm font-sans focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs text-zinc-500 font-sans block">抓取篇数限制</label>
                    <input
                      type="number"
                      min={0}
                      value={scrapeLimit}
                      onChange={(e) => setScrapeLimit(Math.max(0, Number.parseInt(e.target.value || '0', 10) || 0))}
                      className="w-full bg-white border border-zinc-200 rounded-lg px-3.5 py-2 text-sm font-sans focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition"
                    />
                    <span className="text-[10px] text-zinc-450 font-sans block leading-relaxed">
                      输入 0 表示不限制抓取篇数。成功识别博主后会自动加入持续监控，后续更新将按调度生成笔记并发布目录。
                    </span>
                  </div>
                </div>
              )}

              {/* Force overwrite parameter */}
              <div className="flex items-center space-x-2.5 pt-1.5">
                <input
                  type="checkbox"
                  id="force_retry_checkbox"
                  checked={forceRetry}
                  onChange={(e) => setForceRetry(e.target.checked)}
                  className="rounded border-zinc-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
                />
                <label htmlFor="force_retry_checkbox" className="text-xs text-zinc-650 font-sans select-none cursor-pointer">
                  强制重新跑 (覆盖已存在排队缓存)
                </label>
              </div>

              <button
                type="submit"
                className="w-full bg-blue-600 text-white hover:bg-blue-700 rounded-lg font-sans py-2.5 text-xs font-semibold transition cursor-pointer flex items-center justify-center space-x-2 shadow-xs"
              >
                <Cpu className="w-4 h-4 text-white" />
                <span>立即启动 AI 研判任务</span>
              </button>
            </form>
          </div>

          {/* Guidelines info card */}
          <div className="p-5 border border-zinc-200 rounded-xl bg-white shadow-2xs font-sans space-y-3 text-zinc-500 text-xs leading-relaxed">
            <h4 className="font-semibold text-zinc-800">批量研究与资源调度说明</h4>
            <p>
              视频下载后会进入 FunASR 转录，质量不足或服务失败时回退 Whisper；转录成功的条目会立即排队交给 Agnes AI 整理。
            </p>
            <p>
              Ollama 仅在 Agnes AI 不可用时作为本地后备引擎，并继续服从现有 GPU 锁与显存调度。
            </p>
          </div>
        </div>

        {/* RIGHT COLUMN: Tasks execution monitors */}
        <div className="lg:col-span-2 space-y-6">
          
          {/* Statistical counters strip */}
          <div className="grid grid-cols-4 p-4 bg-white border border-zinc-200 rounded-xl text-center divide-x divide-zinc-100 shadow-2xs">
            <div>
              <span className="text-xs text-zinc-455 font-sans block">总调度任务</span>
              <span className="text-lg font-bold font-sans text-zinc-900 mt-1 block">{totalCount} 项</span>
            </div>
            <div>
              <span className="text-xs text-zinc-455 font-sans block">正在运行</span>
              <span className="text-lg font-bold font-sans mt-1 block flex items-center justify-center space-x-1">
                {processingCount > 0 && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin shrink-0" />}
                <span className={processingCount > 0 ? "text-blue-600 font-semibold animate-pulse" : "text-zinc-650"}>{processingCount} 运行</span>
              </span>
            </div>
            <div>
              <span className="text-xs text-zinc-455 font-sans block">圆满归纳</span>
              <span className="text-lg font-bold font-sans text-emerald-600 mt-1 block">{completedCount} 篇</span>
            </div>
            <div>
              <span className="text-xs text-zinc-455 font-sans block">异常中止</span>
              <span className="text-lg font-bold font-sans text-red-650 mt-1 block">{failedCount} 处</span>
            </div>
          </div>

          <div className="space-y-4">
            <h3 className="font-sans font-semibold text-zinc-900 text-sm tracking-tight">任务流水线列表</h3>

            {tasks.length === 0 ? (
              <div className="p-16 border border-dashed border-zinc-200 bg-white rounded-xl text-center text-zinc-400 font-sans shadow-2xs">
                <Database className="w-10 h-10 mx-auto text-zinc-300 stroke-1 mb-3" />
                <p className="text-sm">暂无任务调度痕迹，试下发布一则新研判任务吧！</p>
              </div>
            ) : (
              <div className="space-y-4">
                {tasks.map((task) => {
                  const isExpanded = expandedTaskId === task.id;
                  
                  return (
                    <div
                      key={task.id}
                      id={`task_card_${task.id}`}
                      className="border border-zinc-200 rounded-xl bg-white overflow-hidden shadow-2xs"
                    >
                      {/* Accordion header line */}
                      <div
                        onClick={() => setExpandedTaskId(isExpanded ? null : task.id)}
                        className={`p-4.5 cursor-pointer hover:bg-zinc-50 transition flex items-center justify-between gap-4 ${
                          isExpanded ? 'bg-zinc-50/50' : ''
                        }`}
                      >
                        <div className="flex-1 min-w-0 space-y-1">
                          <div className="flex items-center space-x-2.5">
                            <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm font-semibold ${
                              task.type === 'single' ? 'bg-blue-50 text-blue-700' : 'bg-purple-50 text-purple-700'
                            }`}>
                              {task.type === 'single' ? '单视频解构' : '博主多篇'}
                            </span>
                            <span className="text-[10px] text-zinc-400 font-mono">ID: {task.id}</span>
                            <span className="text-[10px] text-zinc-400 font-mono">{task.created_at}</span>
                          </div>
                          <h4 className="text-sm font-sans font-bold text-zinc-900 truncate">
                            目标: {task.target}
                          </h4>
                        </div>

                        <div className="flex items-center space-x-3 shrink-0">
                          {/* Progress number */}
                          <div className="text-right">
                            <span className={`text-xs font-mono font-bold block ${
                              task.status === 'completed' ? 'text-emerald-600' :
                              task.status === 'failed' ? 'text-red-650 font-semibold' : 'text-blue-600 font-semibold'
                            }`}>
                              {task.pipeline_progress}%
                            </span>
                          </div>
                          {isExpanded ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
                        </div>
                      </div>

                      {/* Accordion body expander panel */}
                      {isExpanded && (
                        <div className="border-t border-zinc-150 p-5 bg-zinc-50/30 space-y-6 animate-fade-in">
                          
                          {/* Big pipelines strip indicator */}
                          <div className="space-y-3">
                            <div className="flex justify-between items-center text-xs font-sans text-zinc-500">
                            <span>当前状态: {task.status === 'completed' ? '处理完成' : task.status === 'failed' ? '调度故障' : task.status === 'paused' ? '已暂停' : '数据计算中'}</span>
                              <span className="font-mono text-zinc-700 font-medium">{getStageLabel(task.pipeline_stage)}</span>
                            </div>

                            {/* Solid visual slider meter */}
                            <div className="w-full h-2 bg-zinc-150 rounded-full overflow-hidden">
                              <div
                                className={`h-full transition-all duration-300 rounded-full ${
                                  task.status === 'completed' ? 'bg-emerald-500' :
                                  task.status === 'failed' ? 'bg-red-500' : 'bg-blue-600'
                                }`}
                                style={{ width: `${task.pipeline_progress}%` }}
                              />
                            </div>

                            {/* Stage nodes indicators blocks */}
                            <div className="grid grid-cols-4 gap-2 pt-2 text-center text-[10px]">
                              <div className={`border p-2 rounded-lg ${getStageColor(task.pipeline_stage, 'downloading', task.status)}`}>
                                <div className="font-bold">1. 抓取下载</div>
                                <div className="font-mono text-[9px] mt-0.5">DOWNLOADING</div>
                              </div>
                              <div className={`border p-2 rounded-lg ${getStageColor(task.pipeline_stage, 'transcribing', task.status)}`}>
                                <div className="font-bold">2. 语音转录</div>
                                <div className="font-mono text-[9px] mt-0.5">TRANSCRIPTION</div>
                              </div>
                              <div className={`border p-2 rounded-lg ${getStageColor(task.pipeline_stage, 'summarizing', task.status)}`}>
                                <div className="font-bold">3. AI 整理</div>
                                <div className="font-mono text-[9px] mt-0.5">AGNES · OLLAMA FALLBACK</div>
                              </div>
                              <div className={`border p-2 rounded-lg ${getStageColor(task.pipeline_stage, 'pushing', task.status)}`}>
                                <div className="font-bold">4. 飞书通知</div>
                                <div className="font-mono text-[9px] mt-0.5">FEISHU PUSH</div>
                              </div>
                            </div>
                          </div>

                          {/* Extra tabular stats for batch jobs */}
                          {task.type === 'blogger' && (
                            <div className="p-4 border border-zinc-200 bg-white rounded-lg space-y-2.5">
                              <div className="text-xs font-sans font-semibold text-zinc-900">批量抓取增量明细 (汇总)</div>
                              <div className="grid grid-cols-4 gap-2 text-center text-xs font-mono">
                                <div className="p-1 bg-zinc-50 rounded text-zinc-650">检测件: {task.total_items}</div>
                                <div className="p-1 bg-emerald-50 rounded text-emerald-600 font-semibold">成功: {task.completed_items}</div>
                                <div className="p-1 bg-red-50 rounded text-red-500 font-semibold">失败: {task.failed_items}</div>
                                <div className="p-1 bg-zinc-50 rounded text-zinc-450">跳过/略: {task.skipped_items}</div>
                              </div>
                            </div>
                          )}

                          {/* Operational button overrides inside collapsible view */}
                          <div className="flex items-center space-x-2.5 pt-2">
                            {task.status === 'processing' && (
                              <button
                                type="button"
                                onClick={() => controlResearchTask(task.id, 'pause')}
                                className="px-3.5 py-1.5 border border-zinc-200 hover:border-zinc-900 rounded-lg text-xs text-zinc-700 bg-white font-sans transition cursor-pointer"
                              >
                                <Pause className="w-3.5 h-3.5 inline mr-1" />
                                暂停调度
                              </button>
                            )}
                            {task.status === 'paused' && (
                              <button
                                type="button"
                                onClick={() => controlResearchTask(task.id, 'resume')}
                                className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-sans font-semibold transition cursor-pointer"
                              >
                                <Play className="w-3.5 h-3.5 inline mr-1" />
                                继续任务
                              </button>
                            )}
                            {(task.status === 'completed' || task.status === 'failed') && (
                              <button
                                type="button"
                                onClick={() => controlResearchTask(task.id, 'restart')}
                                className="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-sans font-semibold transition cursor-pointer"
                              >
                                <RotateCcw className="w-3.5 h-3.5 inline mr-1" />
                                重新拉取
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => showJobDetail(task.id)}
                              className="px-3.5 py-1.5 border border-zinc-200 hover:border-zinc-900 rounded-lg text-xs text-zinc-700 bg-white font-sans transition cursor-pointer"
                            >
                              查看详情
                            </button>
                            {Number(task.failed_items || 0) > 0 && (
                              <button
                                type="button"
                                onClick={() => retryResearchFailed(task.id)}
                                className="px-3.5 py-1.5 bg-red-600 hover:bg-red-700 text-white rounded-lg text-xs font-sans font-semibold transition cursor-pointer"
                              >
                                重试失败项
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => controlResearchTask(task.id, 'cancel')}
                              className="px-3.5 py-1.5 text-xs font-sans text-red-655 hover:text-red-700 hover:bg-red-50 rounded-lg transition cursor-pointer font-semibold"
                            >
                              <XCircle className="w-3.5 h-3.5 inline mr-1" />
                              取消任务
                            </button>
                          </div>

                          {(loadingJobId === task.id || jobDetails[task.id]) && (
                            <div className="p-4 border border-zinc-200 bg-white rounded-lg space-y-4">
                              {loadingJobId === task.id ? (
                                <div className="flex items-center space-x-2 text-xs text-zinc-500 font-sans">
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  <span>正在读取研究任务详情...</span>
                                </div>
                              ) : (
                                <>
                                  <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-center text-xs font-mono">
                                    {[
                                      ['下载队列', jobDetails[task.id]?.pipeline?.counts?.download],
                                      ['转录队列', jobDetails[task.id]?.pipeline?.counts?.transcript],
                                      ['AI 队列', jobDetails[task.id]?.pipeline?.counts?.ai],
                                      ['完成/失败', `${jobDetails[task.id]?.pipeline?.counts?.done ?? 0}/${jobDetails[task.id]?.pipeline?.counts?.failed ?? 0}`],
                                      ['ETA', jobDetails[task.id]?.pipeline?.eta_text]
                                    ].map(([label, value]) => (
                                      <div key={String(label)} className="p-2 bg-zinc-50 rounded border border-zinc-100">
                                        <div className="text-[10px] text-zinc-400">{label as string}</div>
                                        <div className="text-zinc-900 font-semibold mt-1">{value ?? '暂无'}</div>
                                      </div>
                                    ))}
                                  </div>

                                  <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs font-mono">
                                    <div className="p-2 bg-zinc-50 rounded border border-zinc-100">下载目录：{jobDetails[task.id]?.pipeline?.download_dir_size || '暂无'}</div>
                                    <div className="p-2 bg-zinc-50 rounded border border-zinc-100">笔记目录：{jobDetails[task.id]?.pipeline?.notes_dir_size || '暂无'}</div>
                                    <div className="p-2 bg-zinc-50 rounded border border-zinc-100">任务状态：{String(jobDetails[task.id]?.job?.status || task.status)}</div>
                                  </div>

                                  <div className="max-h-60 overflow-auto border border-zinc-150 rounded">
                                    <table className="w-full text-xs font-sans">
                                      <thead className="bg-zinc-50 text-zinc-500 sticky top-0">
                                        <tr>
                                          <th className="text-left p-2 font-semibold">作品</th>
                                          <th className="text-left p-2 font-semibold">状态</th>
                                          <th className="text-left p-2 font-semibold">阶段</th>
                                          <th className="text-left p-2 font-semibold">错误</th>
                                        </tr>
                                      </thead>
                                      <tbody className="divide-y divide-zinc-100">
                                        {(jobDetails[task.id]?.items || []).slice(0, 40).map((item, index) => (
                                          <tr key={`${task.id}-${index}`}>
                                            <td className="p-2 font-mono text-zinc-600">{String(item.aweme_id || item.url || item.id || '-')}</td>
                                            <td className="p-2">{String(item.status || '-')}</td>
                                            <td className="p-2">{String(item.stage || item.current_stage || '-')}</td>
                                            <td className="p-2 text-red-600">{String(item.error_message || item.last_error || '')}</td>
                                          </tr>
                                        ))}
                                      </tbody>
                                    </table>
                                  </div>
                                </>
                              )}
                            </div>
                          )}

                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

        </div>

      </div>
      )}
    </div>
  );
}
