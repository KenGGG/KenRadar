/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useState } from 'react';
import { 
  SlidersHorizontal, 
  Settings, 
  Cpu, 
  Sparkles, 
  Send, 
  Lock, 
  Github,
  ChevronDown, 
  ChevronUp, 
  Save,
  Download
} from 'lucide-react';
import { SystemConfig } from '../types';

interface ConfigEditorProps {
  config: SystemConfig;
  saveConfig: (newConfig: SystemConfig) => void;
}

export default function ConfigEditor({
  config,
  saveConfig
}: ConfigEditorProps) {
  // Local form states synced on save
  const [schedulerEnabled, setSchedulerEnabled] = useState(config.scheduler.enabled);
  const [cronExpression, setCronExpression] = useState(config.scheduler.cronExpression);
  const [gracePeriod, setGracePeriod] = useState(config.scheduler.grace_period_mins);
  const [maxConcurrent, setMaxConcurrent] = useState(config.scheduler.max_concurrent_tasks);
  const [retryTimes, setRetryTimes] = useState(config.scheduler.retry_times);
  const [maxItemsPerBlogger, setMaxItemsPerBlogger] = useState(config.scheduler.max_items_per_blogger);
  const [manualTriggerEnabled, setManualTriggerEnabled] = useState(config.scheduler.manual_trigger_enabled);

  const [whisperModel, setWhisperModel] = useState(config.whisper.model);
  const [whisperDevice, setWhisperDevice] = useState(config.whisper.device);
  const [whisperThreads, setWhisperThreads] = useState(config.whisper.threads);
  const [useGpu, setUseGpu] = useState(config.whisper.use_gpu);
  const [vramOffload, setVramOffload] = useState(config.whisper.vram_offload_gb);
  const [stagedGpuScheduling, setStagedGpuScheduling] = useState(config.whisper.staged_gpu_scheduling);

  const [aiEndpoint, setAiEndpoint] = useState(config.ai.endpoint);
  const [aiModel, setAiModel] = useState(config.ai.model);
  const [aiApiType, setAiApiType] = useState(config.ai.api_type);
  const [aiTemp, setAiTemp] = useState(config.ai.temperature);
  const [aiTopP, setAiTopP] = useState(config.ai.top_p);
  const [aiTopK, setAiTopK] = useState(config.ai.top_k);
  const [aiTimeout, setAiTimeout] = useState(config.ai.timeout_sec);
  const [aiMaxTokens, setAiMaxTokens] = useState(config.ai.max_tokens);
  const [aiMaxInputChars, setAiMaxInputChars] = useState(config.ai.max_input_chars);
  const [aiKeepAlive, setAiKeepAlive] = useState(config.ai.keep_alive);
  const [aiNoThink, setAiNoThink] = useState(config.ai.no_think);
  const [aiCompactPrompt, setAiCompactPrompt] = useState(config.ai.compact_prompt);
  const [fallbackModel, setFallbackModel] = useState(config.ai.fallback_model);
  const [promptTemplate, setPromptTemplate] = useState(config.ai.prompt_template);

  const [downloadPath, setDownloadPath] = useState(config.download.path);
  const [downloadMaxWorkers, setDownloadMaxWorkers] = useState(config.download.max_workers);
  const [downloadBatchSize, setDownloadBatchSize] = useState(config.download.batch_size);
  const [downloadBatchCooldown, setDownloadBatchCooldown] = useState(config.download.batch_cooldown_seconds);
  const [downloadMaxDuration, setDownloadMaxDuration] = useState(config.download.max_duration_seconds);
  const [downloadRetryFailed, setDownloadRetryFailed] = useState(config.download.retry_failed);
  const [downloadCircuitFailures, setDownloadCircuitFailures] = useState(config.download.circuit_breaker_failures);
  const [downloadCircuitCooldown, setDownloadCircuitCooldown] = useState(config.download.circuit_breaker_cooldown_seconds);
  const [downloadSaveJson, setDownloadSaveJson] = useState(config.download.save_json);

  const [feishuWebhook, setFeishuWebhook] = useState(config.feishu.webhook_url);
  const [feishuType, setFeishuType] = useState(config.feishu.message_type);
  const [pushThreshold, setPushThreshold] = useState(config.feishu.push_threshold_rating);
  const [feishuRetryAttempts, setFeishuRetryAttempts] = useState(config.feishu.retry_attempts);
  const [feishuCardMaxItems, setFeishuCardMaxItems] = useState(config.feishu.card_max_items);
  const [feishuTheme, setFeishuTheme] = useState(config.feishu.card_theme);

  const [webPort, setWebPort] = useState(config.security.port);
  const [webBind, setWebBind] = useState(config.security.bind_ip);
  const [passwordAuth, setPasswordAuth] = useState(config.security.password_auth);
  const [webPassword, setWebPassword] = useState(config.security.web_password);

  const [githubPagesEnabled, setGithubPagesEnabled] = useState(config.publishing.github_pages_enabled);
  const [githubPagesOutputDir, setGithubPagesOutputDir] = useState(config.publishing.github_pages_output_dir);
  const [githubPagesPublicBaseUrl, setGithubPagesPublicBaseUrl] = useState(config.publishing.github_pages_public_base_url);
  const [githubSyncEnabled, setGithubSyncEnabled] = useState(config.publishing.github_sync_enabled);
  const [githubSyncRepoDir, setGithubSyncRepoDir] = useState(config.publishing.github_sync_repo_dir);
  const [githubSyncBranch, setGithubSyncBranch] = useState(config.publishing.github_sync_branch);
  const [githubSyncAutoCommit, setGithubSyncAutoCommit] = useState(config.publishing.github_sync_auto_commit);
  const [githubSyncAutoPush, setGithubSyncAutoPush] = useState(config.publishing.github_sync_auto_push);
  const [githubSyncIncludeHtmlDocs, setGithubSyncIncludeHtmlDocs] = useState(config.publishing.github_sync_include_html_docs);
  const [githubSyncIncludeMarkdownNotes, setGithubSyncIncludeMarkdownNotes] = useState(config.publishing.github_sync_include_markdown_notes);
  const [githubSyncIncludeBriefs, setGithubSyncIncludeBriefs] = useState(config.publishing.github_sync_include_briefs);
  const [githubSyncIncludeTranscripts, setGithubSyncIncludeTranscripts] = useState(config.publishing.github_sync_include_transcripts);

  // Accordion folds open states
  const [openSections, setOpenSections] = useState({
    sched: true,
    whisper: false,
    ollama: true,
    download: false,
    feishu: false,
    publishing: false,
    security: false
  });

  const [showSavedToast, setShowSavedToast] = useState(false);

  useEffect(() => {
    setSchedulerEnabled(config.scheduler.enabled);
    setCronExpression(config.scheduler.cronExpression);
    setGracePeriod(config.scheduler.grace_period_mins);
    setMaxConcurrent(config.scheduler.max_concurrent_tasks);
    setRetryTimes(config.scheduler.retry_times);
    setMaxItemsPerBlogger(config.scheduler.max_items_per_blogger);
    setManualTriggerEnabled(config.scheduler.manual_trigger_enabled);
    setWhisperModel(config.whisper.model);
    setWhisperDevice(config.whisper.device);
    setWhisperThreads(config.whisper.threads);
    setUseGpu(config.whisper.use_gpu);
    setVramOffload(config.whisper.vram_offload_gb);
    setStagedGpuScheduling(config.whisper.staged_gpu_scheduling);
    setAiEndpoint(config.ai.endpoint);
    setAiModel(config.ai.model);
    setAiApiType(config.ai.api_type);
    setAiTemp(config.ai.temperature);
    setAiTopP(config.ai.top_p);
    setAiTopK(config.ai.top_k);
    setAiTimeout(config.ai.timeout_sec);
    setAiMaxTokens(config.ai.max_tokens);
    setAiMaxInputChars(config.ai.max_input_chars);
    setAiKeepAlive(config.ai.keep_alive);
    setAiNoThink(config.ai.no_think);
    setAiCompactPrompt(config.ai.compact_prompt);
    setFallbackModel(config.ai.fallback_model);
    setPromptTemplate(config.ai.prompt_template);
    setDownloadPath(config.download.path);
    setDownloadMaxWorkers(config.download.max_workers);
    setDownloadBatchSize(config.download.batch_size);
    setDownloadBatchCooldown(config.download.batch_cooldown_seconds);
    setDownloadMaxDuration(config.download.max_duration_seconds);
    setDownloadRetryFailed(config.download.retry_failed);
    setDownloadCircuitFailures(config.download.circuit_breaker_failures);
    setDownloadCircuitCooldown(config.download.circuit_breaker_cooldown_seconds);
    setDownloadSaveJson(config.download.save_json);
    setFeishuWebhook(config.feishu.webhook_url);
    setFeishuType(config.feishu.message_type);
    setPushThreshold(config.feishu.push_threshold_rating);
    setFeishuRetryAttempts(config.feishu.retry_attempts);
    setFeishuCardMaxItems(config.feishu.card_max_items);
    setFeishuTheme(config.feishu.card_theme);
    setWebPort(config.security.port);
    setWebBind(config.security.bind_ip);
    setPasswordAuth(config.security.password_auth);
    setWebPassword(config.security.web_password);
    setGithubPagesEnabled(config.publishing.github_pages_enabled);
    setGithubPagesOutputDir(config.publishing.github_pages_output_dir);
    setGithubPagesPublicBaseUrl(config.publishing.github_pages_public_base_url);
    setGithubSyncEnabled(config.publishing.github_sync_enabled);
    setGithubSyncRepoDir(config.publishing.github_sync_repo_dir);
    setGithubSyncBranch(config.publishing.github_sync_branch);
    setGithubSyncAutoCommit(config.publishing.github_sync_auto_commit);
    setGithubSyncAutoPush(config.publishing.github_sync_auto_push);
    setGithubSyncIncludeHtmlDocs(config.publishing.github_sync_include_html_docs);
    setGithubSyncIncludeMarkdownNotes(config.publishing.github_sync_include_markdown_notes);
    setGithubSyncIncludeBriefs(config.publishing.github_sync_include_briefs);
    setGithubSyncIncludeTranscripts(config.publishing.github_sync_include_transcripts);
  }, [config]);

  const toggleSection = (sect: keyof typeof openSections) => {
    setOpenSections(prev => ({
      ...prev,
      [sect]: !prev[sect]
    }));
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    const updated: SystemConfig = {
      scheduler: {
        enabled: schedulerEnabled,
        cronExpression,
        grace_period_mins: gracePeriod,
        max_concurrent_tasks: maxConcurrent,
        retry_times: retryTimes,
        max_items_per_blogger: maxItemsPerBlogger,
        manual_trigger_enabled: manualTriggerEnabled
      },
      whisper: {
        model: whisperModel,
        device: whisperDevice,
        threads: whisperThreads,
        use_gpu: useGpu,
        vram_offload_gb: vramOffload,
        staged_gpu_scheduling: stagedGpuScheduling
      },
      ai: {
        ...config.ai,
        api_type: aiApiType,
        endpoint: aiEndpoint,
        model: aiModel,
        temperature: aiTemp,
        top_p: aiTopP,
        top_k: aiTopK,
        timeout_sec: aiTimeout,
        max_tokens: aiMaxTokens,
        max_input_chars: aiMaxInputChars,
        keep_alive: aiKeepAlive,
        no_think: aiNoThink,
        compact_prompt: aiCompactPrompt,
        fallback_model: fallbackModel,
        prompt_template: promptTemplate
      },
      download: {
        path: downloadPath,
        max_workers: downloadMaxWorkers,
        batch_size: downloadBatchSize,
        batch_cooldown_seconds: downloadBatchCooldown,
        max_duration_seconds: downloadMaxDuration,
        retry_failed: downloadRetryFailed,
        circuit_breaker_failures: downloadCircuitFailures,
        circuit_breaker_cooldown_seconds: downloadCircuitCooldown,
        save_json: downloadSaveJson
      },
      feishu: {
        webhook_url: feishuWebhook,
        message_type: feishuType,
        push_threshold_rating: pushThreshold,
        retry_attempts: feishuRetryAttempts,
        card_max_items: feishuCardMaxItems,
        card_theme: feishuTheme as any
      },
      security: {
        port: webPort,
        bind_ip: webBind,
        password_auth: passwordAuth,
        web_password: webPassword,
        access_token_ttl_hours: 24
      },
      publishing: {
        github_pages_enabled: githubPagesEnabled,
        github_pages_output_dir: githubPagesOutputDir,
        github_pages_public_base_url: githubPagesPublicBaseUrl,
        github_pages_public_base_url_configured: Boolean(githubPagesPublicBaseUrl.trim() && !githubPagesPublicBaseUrl.includes('${')),
        github_sync_enabled: githubSyncEnabled,
        github_sync_repo_dir: githubSyncRepoDir,
        github_sync_branch: githubSyncBranch,
        github_sync_auto_commit: githubSyncAutoCommit,
        github_sync_auto_push: githubSyncAutoPush,
        github_sync_include_html_docs: githubSyncIncludeHtmlDocs,
        github_sync_include_markdown_notes: githubSyncIncludeMarkdownNotes,
        github_sync_include_briefs: githubSyncIncludeBriefs,
        github_sync_include_transcripts: githubSyncIncludeTranscripts
      }
    };

    saveConfig(updated);
    setShowSavedToast(true);
    setTimeout(() => setShowSavedToast(false), 3000);
  };

  const fireFeishuTest = async (kind: 'card' | 'text') => {
    const response = await fetch(kind === 'card' ? '/api/test-feishu-card' : '/api/test-feishu-text', { method: 'POST', credentials: 'same-origin' });
    const payload = await response.json().catch(() => ({}));
    alert(payload.message || (response.ok ? '测试推送已发送。' : '测试推送失败。'));
  };

  return (
    <div className="space-y-8 animate-fade-in relative">
      
      {/* Toast popup alerts */}
      {showSavedToast && (
        <div className="fixed top-20 right-6 z-50 p-4 bg-white dark:bg-[var(--surface)] text-zinc-900 dark:text-[var(--text-primary)] rounded-xl flex items-center space-x-2.5 shadow-lg border border-zinc-200 dark:border-[var(--surface-border)] animate-slide-in font-sans">
          <div className="w-5 h-5 bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-600 dark:text-[var(--success)] rounded-full flex items-center justify-center font-bold">✓</div>
          <span className="text-xs font-semibold text-zinc-800 dark:text-[var(--text-primary)]">配置文件 config/config.yaml 保存并热重载成功！</span>
        </div>
      )}

      {/* Header */}
      <div className="border-b border-zinc-200 dark:border-[var(--surface-border)] pb-4">
        <h1 className="text-3xl font-sans font-semibold tracking-tight text-zinc-900 dark:text-[var(--text-primary)]">系统配置</h1>
        <p className="text-zinc-500 dark:text-[var(--text-secondary)] font-sans text-sm mt-1">控制定时调度间隔、GPU 挂起排队参数、本地大模型端点及安全端口限制</p>
      </div>

      <form onSubmit={handleSave} className="space-y-4">
        
        {/* Accordions 1: Scheduler (定时检测调度) */}
        <div className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl overflow-hidden bg-white dark:bg-[var(--surface)] shadow-2xs">
          <div
            onClick={() => toggleSection('sched')}
            className="p-4 bg-white dark:bg-[var(--surface)] border-b border-zinc-200 dark:border-[var(--surface-border)] flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-[var(--surface-muted)] transition select-none"
          >
            <div className="flex items-center space-x-3 text-zinc-900 dark:text-[var(--text-primary)]">
              <Settings className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />
              <span className="font-sans font-semibold text-sm">1. 自动化检测及调度 (Scheduler)</span>
            </div>
            {openSections.sched ? <ChevronUp className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" /> : <ChevronDown className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />}
          </div>

          {openSections.sched && (
            <div className="p-6 space-y-4 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 font-sans text-sm">
              <div className="space-y-1.5 flex flex-col justify-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase tracking-wider">启用自动定时轮询</span>
                <div className="flex items-center space-x-3 pt-1.5">
                  <input
                    type="checkbox"
                    id="sched_enabled_cb"
                    checked={schedulerEnabled}
                    onChange={(e) => setSchedulerEnabled(e.target.checked)}
                    className="rounded border-zinc-350 text-blue-600 focus:ring-blue-500 w-4 h-4 accent-blue-600 cursor-pointer"
                  />
                  <label htmlFor="sched_enabled_cb" className="text-xs text-zinc-600 dark:text-[var(--text-secondary)] font-medium select-none cursor-pointer">
                    开启（按 Cron Expression 表达周期自动唤醒爬虫）
                  </label>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase block">每日检测时间列表</label>
                <input
                  type="text"
                  value={cronExpression}
                  onChange={(e) => setCronExpression(e.target.value)}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  placeholder="10:00, 21:00"
                />
                <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] font-sans block">例如：10:00, 21:00。与当前 schedule.times 配置保持一致。</span>
              </div>

              {/* Advanced collapsed options in sched */}
              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase block">重跑宽限时间 (分钟)</label>
                <input
                  type="number"
                  value={gracePeriod}
                  onChange={(e) => setGracePeriod(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase block">每轮最大处理条数</label>
                <input
                  type="number"
                  value={maxConcurrent}
                  onChange={(e) => setMaxConcurrent(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase block">失败重试次数</label>
                <input
                  type="number"
                  min="0"
                  value={retryTimes}
                  onChange={(e) => setRetryTimes(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase block">单博主最大拉取条数</label>
                <input
                  type="number"
                  min="0"
                  value={maxItemsPerBlogger}
                  onChange={(e) => setMaxItemsPerBlogger(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="space-y-1.5 flex flex-col justify-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase">允许 Web 手动触发</span>
                <div className="flex items-center space-x-3 pt-1.5">
                  <input
                    type="checkbox"
                    id="manual_trigger_cb"
                    checked={manualTriggerEnabled}
                    onChange={(e) => setManualTriggerEnabled(e.target.checked)}
                    className="rounded border-zinc-350 text-blue-600 focus:ring-blue-500 w-4 h-4 accent-blue-600 cursor-pointer"
                  />
                  <label htmlFor="manual_trigger_cb" className="text-xs text-zinc-600 dark:text-[var(--text-secondary)] font-medium select-none cursor-pointer">
                    写入 schedule.manual_trigger_enabled
                  </label>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Accordions 2: Whisper/GPU (语音与设备加速) */}
        <div className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl overflow-hidden bg-white dark:bg-[var(--surface)] shadow-2xs">
          <div
            onClick={() => toggleSection('whisper')}
            className="p-4 bg-white dark:bg-[var(--surface)] border-b border-zinc-200 dark:border-[var(--surface-border)] flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-[var(--surface-muted)] transition select-none"
          >
            <div className="flex items-center space-x-3 text-zinc-900 dark:text-[var(--text-primary)]">
              <Cpu className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />
              <span className="font-sans font-semibold text-sm">2. Whisper 语音转录与 GPU 阶段排程</span>
            </div>
            {openSections.whisper ? <ChevronUp className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" /> : <ChevronDown className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />}
          </div>

          {openSections.whisper && (
            <div className="p-6 space-y-4 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 font-sans text-sm">
              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">模型尺寸等级 (Whisper Model)</label>
                <select
                  value={whisperModel}
                  onChange={(e) => setWhisperModel(e.target.value as any)}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs focus:outline-none transition"
                >
                  <option value="tiny">tiny (极轻、多方言较一般)</option>
                  <option value="base">base (折中、中文适配度完美推荐)</option>
                  <option value="small">small (高品质)</option>
                  <option value="medium">medium (超高品质、需4G以上显存)</option>
                  <option value="large-v3-turbo">large-v3-turbo (当前生产推荐)</option>
                  <option value="large-v3">large-v3 (顶级离线精度、运行慢)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">运行物理设备 (Device Type)</label>
                <select
                  value={whisperDevice}
                  onChange={(e) => setWhisperDevice(e.target.value as any)}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs focus:outline-none font-mono transition"
                >
                  <option value="cpu">CPU (无 CUDA 独卡硬解推荐)</option>
                  <option value="cuda">英伟达独立显卡 CUDA 加速</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">并发分析 CPU 线程数 (Threads)</label>
                <input
                  type="number"
                  value={whisperThreads}
                  onChange={(e) => setWhisperThreads(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="space-y-1.5 flex flex-col justify-center">
                <span className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold font-mono uppercase">排它锁阶段性 GPU 调度控制</span>
                <div className="flex items-center space-x-3 pt-1.5">
                  <input
                    type="checkbox"
                    id="staged_gpu_cb"
                    checked={stagedGpuScheduling}
                    onChange={(e) => setStagedGpuScheduling(e.target.checked)}
                    className="rounded border-zinc-350 text-blue-600 focus:ring-blue-500 w-4 h-4 accent-blue-600 cursor-pointer"
                  />
                  <label htmlFor="staged_gpu_cb" className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-medium select-none cursor-pointer">
                    开启 GPU 排队锁（协调 Whisper 与本地 Ollama 后备推理）
                  </label>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Whisper GPU 最小空闲显存 (GB)</label>
                <input
                  type="number"
                  min="1"
                  max="48"
                  value={vramOffload}
                  onChange={(e) => setVramOffload(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
                <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] block font-sans">写入 gpu_scheduler.memory_check.min_free_vram_mb_for_whisper_gpu。</span>
              </div>
            </div>
          )}
        </div>

        {/* Accordions 3: AI provider configuration */}
        <div className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl overflow-hidden bg-white dark:bg-[var(--surface)] shadow-2xs">
          <div
            onClick={() => toggleSection('ollama')}
            className="p-4 bg-white dark:bg-[var(--surface)] border-b border-zinc-200 dark:border-[var(--surface-border)] flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-[var(--surface-muted)] transition select-none"
          >
            <div className="flex items-center space-x-3 text-zinc-900 dark:text-[var(--text-primary)]">
              <Sparkles className="w-4 h-4 text-blue-500 dark:text-[var(--info)]" />
              <span className="font-sans font-semibold text-sm">3. AI 智能整理与 Prompt 编辑</span>
            </div>
            {openSections.ollama ? <ChevronUp className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" /> : <ChevronDown className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />}
          </div>

          {openSections.ollama && (
            <div className="p-6 space-y-4 font-sans text-sm">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">AI Provider Endpoint</label>
                  <input
                    type="text"
                    value={aiEndpoint}
                    onChange={(e) => setAiEndpoint(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                  <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] block font-sans">这里配置主 AI 引擎，当前为 Agnes AI；Ollama 是 providers 列表中的本地后备引擎。</span>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">推理模型 (Base Model Target)</label>
                  <input
                    type="text"
                    value={aiModel}
                    onChange={(e) => setAiModel(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Provider API Type</label>
                  <select
                    value={aiApiType}
                    onChange={(e) => setAiApiType(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  >
                    <option value="chat_completions">chat_completions</option>
                    <option value="ollama">ollama</option>
                    <option value="openai">openai-compatible</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">模型多样采度 (Temperature)</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="1"
                    value={aiTemp}
                    onChange={(e) => setAiTemp(parseFloat(e.target.value))}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Top P</label>
                  <input
                    type="number"
                    step="0.05"
                    min="0"
                    max="1"
                    value={aiTopP}
                    onChange={(e) => setAiTopP(parseFloat(e.target.value))}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Top K</label>
                  <input
                    type="number"
                    min="0"
                    value={aiTopK}
                    onChange={(e) => setAiTopK(parseInt(e.target.value))}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">网络超时限制 timeout (秒)</label>
                  <input
                    type="number"
                    value={aiTimeout}
                    onChange={(e) => setAiTimeout(parseInt(e.target.value))}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Max Tokens</label>
                  <input
                    type="number"
                    min="256"
                    value={aiMaxTokens}
                    onChange={(e) => setAiMaxTokens(parseInt(e.target.value))}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Max Input Chars</label>
                  <input
                    type="number"
                    min="1000"
                    value={aiMaxInputChars}
                    onChange={(e) => setAiMaxInputChars(parseInt(e.target.value))}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Provider Keep Alive</label>
                  <input
                    type="text"
                    value={aiKeepAlive}
                    onChange={(e) => setAiKeepAlive(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                    placeholder="10m"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">备选 Fallback 被动避让模型</label>
                  <input
                    type="text"
                    value={fallbackModel}
                    onChange={(e) => setFallbackModel(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <label className="flex items-center space-x-3 pt-6">
                  <input
                    type="checkbox"
                    checked={aiNoThink}
                    onChange={(e) => setAiNoThink(e.target.checked)}
                    className="rounded border-zinc-350 dark:border-[var(--surface-border)] text-blue-600 dark:text-[var(--info)] focus:ring-blue-500 dark:focus:ring-[var(--info)] w-4 h-4 accent-blue-600 dark:accent-[var(--info)] cursor-pointer"
                  />
                  <span className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-medium">启用 no_think</span>
                </label>

                <label className="flex items-center space-x-3 pt-6">
                  <input
                    type="checkbox"
                    checked={aiCompactPrompt}
                    onChange={(e) => setAiCompactPrompt(e.target.checked)}
                    className="rounded border-zinc-350 dark:border-[var(--surface-border)] text-blue-600 dark:text-[var(--info)] focus:ring-blue-500 dark:focus:ring-[var(--info)] w-4 h-4 accent-blue-600 dark:accent-[var(--info)] cursor-pointer"
                  />
                  <span className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-medium">启用 compact_prompt</span>
                </label>
              </div>

              {/* Obsidian note prompt template */}
              <div className="space-y-1.5 pt-2">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Obsidian 知识提炼 System Prompt 指令</label>
                <textarea
                  value={promptTemplate}
                  onChange={(e) => setPromptTemplate(e.target.value)}
                  rows={6}
                  className="w-full bg-zinc-950 dark:bg-[var(--surface)] text-zinc-250 dark:text-zinc-200 border border-zinc-800 dark:border-[var(--surface-border)] rounded-lg p-4 text-xs font-mono leading-relaxed focus:ring-1 focus:ring-zinc-700 dark:focus:ring-[var(--surface-border)] focus:outline-none transition"
                />
              </div>
            </div>
          )}
        </div>

        {/* Accordions 4: Download (下载与素材缓存) */}
        <div className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl overflow-hidden bg-white dark:bg-[var(--surface)] shadow-2xs">
          <div
            onClick={() => toggleSection('download')}
            className="p-4 bg-white dark:bg-[var(--surface)] border-b border-zinc-200 dark:border-[var(--surface-border)] flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-[var(--surface-muted)] transition select-none"
          >
            <div className="flex items-center space-x-3 text-zinc-900 dark:text-[var(--text-primary)]">
              <Download className="w-4 h-4 text-emerald-600 dark:text-[var(--success)]" />
              <span className="font-sans font-semibold text-sm">4. 下载与素材缓存策略</span>
            </div>
            {openSections.download ? <ChevronUp className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" /> : <ChevronDown className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />}
          </div>

          {openSections.download && (
            <div className="p-6 space-y-4 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 font-sans text-sm">
              {[
                ['下载目录', downloadPath, setDownloadPath, 'text'],
                ['最大下载 Worker', downloadMaxWorkers, setDownloadMaxWorkers, 'number'],
                ['批量大小', downloadBatchSize, setDownloadBatchSize, 'number'],
                ['批次冷却秒数', downloadBatchCooldown, setDownloadBatchCooldown, 'number'],
                ['单视频最长秒数', downloadMaxDuration, setDownloadMaxDuration, 'number'],
                ['熔断失败次数', downloadCircuitFailures, setDownloadCircuitFailures, 'number'],
                ['熔断冷却秒数', downloadCircuitCooldown, setDownloadCircuitCooldown, 'number']
              ].map(([label, value, setter, type]) => (
                <div className="space-y-1.5" key={String(label)}>
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">{label as string}</label>
                  <input
                    type={type as string}
                    value={value as string | number}
                    onChange={(e) => {
                      const next = type === 'number' ? parseInt(e.target.value) : e.target.value;
                      (setter as React.Dispatch<React.SetStateAction<any>>)(next);
                    }}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>
              ))}

              <label className="flex items-center space-x-3 pt-6">
                <input
                  type="checkbox"
                  checked={downloadRetryFailed}
                  onChange={(e) => setDownloadRetryFailed(e.target.checked)}
                  className="rounded border-zinc-350 dark:border-[var(--surface-border)] text-blue-600 dark:text-[var(--info)] focus:ring-blue-500 dark:focus:ring-[var(--info)] w-4 h-4 accent-blue-600 dark:accent-[var(--info)] cursor-pointer"
                />
                <span className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-medium">允许下载失败后重试</span>
              </label>

              <label className="flex items-center space-x-3 pt-6">
                <input
                  type="checkbox"
                  checked={downloadSaveJson}
                  onChange={(e) => setDownloadSaveJson(e.target.checked)}
                  className="rounded border-zinc-350 dark:border-[var(--surface-border)] text-blue-600 dark:text-[var(--info)] focus:ring-blue-500 dark:focus:ring-[var(--info)] w-4 h-4 accent-blue-600 dark:accent-[var(--info)] cursor-pointer"
                />
                <span className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-medium">保存作品 JSON 元数据</span>
              </label>
            </div>
          )}
        </div>

        {/* Accordions 5: Feishu (飞书Webhook与推送) */}
        <div className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl overflow-hidden bg-white dark:bg-[var(--surface)] shadow-2xs">
          <div
            onClick={() => toggleSection('feishu')}
            className="p-4 bg-white dark:bg-[var(--surface)] border-b border-zinc-200 dark:border-[var(--surface-border)] flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-[var(--surface-muted)] transition select-none"
          >
            <div className="flex items-center space-x-3 text-zinc-900 dark:text-[var(--text-primary)]">
              <Send className="w-4 h-4 text-purple-500 dark:text-[var(--info)]" />
              <span className="font-sans font-semibold text-sm">5. 飞书监控推送群机器人联调与阈值限制</span>
            </div>
            {openSections.feishu ? <ChevronUp className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" /> : <ChevronDown className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />}
          </div>

          {openSections.feishu && (
            <div className="p-6 space-y-4 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 font-sans text-sm">
              <div className="space-y-1.5 md:col-span-2">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">飞书群自定义 Bot 链接 Webhook URL</label>
                <input
                  type="text"
                  value={feishuWebhook}
                  onChange={(e) => setFeishuWebhook(e.target.value)}
                  placeholder="已配置时此处留空不会覆盖现有 Webhook；填入新 URL 才会更新"
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
                <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] block font-sans">为保护密钥，后端不会把现有 Webhook 明文回传到浏览器。</span>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">推送体形式</label>
                <select
                  value={feishuType}
                  onChange={(e) => setFeishuType(e.target.value as any)}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs focus:outline-none transition"
                >
                  <option value="auto">自动选择（推荐）</option>
                  <option value="card">优雅大卡片模式 (Lark Card Component)</option>
                  <option value="text">原始纯字符流模式 (Raw Markdown Text)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">自动推送评分合格门槛</label>
                <input
                  type="number"
                  step="0.5"
                  min="0"
                  max="10"
                  value={pushThreshold}
                  onChange={(e) => setPushThreshold(parseFloat(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
                <span className="text-[10px] text-zinc-400 dark:text-[var(--text-muted)] block font-sans">评分高于此分数自动推送至群。低于此则安静归档等待人工筛选。</span>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">推送失败重试次数</label>
                <input
                  type="number"
                  min="0"
                  value={feishuRetryAttempts}
                  onChange={(e) => setFeishuRetryAttempts(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">卡片最多展示条数</label>
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={feishuCardMaxItems}
                  onChange={(e) => setFeishuCardMaxItems(parseInt(e.target.value))}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">卡片推送视觉底板主题色</label>
                <select
                  value={feishuTheme}
                  onChange={(e) => setFeishuTheme(e.target.value as any)}
                  className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs focus:outline-none font-sans transition"
                >
                  <option value="blue">蓝色优雅 (Blue)</option>
                  <option value="turquoise">青绿活力 (Turquoise)</option>
                  <option value="violet">紫色精睿 (Violet)</option>
                  <option value="orange">橙黄预警 (Orange)</option>
                  <option value="red">绯红高位 (Red)</option>
                </select>
              </div>

              <div className="flex items-end pt-3">
                <button
                  type="button"
                  onClick={() => fireFeishuTest('card')}
                  className="w-full py-1.5 border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] text-zinc-700 dark:text-[var(--text-primary)] rounded-lg font-sans text-xs font-semibold shadow-2xs transition cursor-pointer flex items-center justify-center space-x-1.5"
                >
                  <Send className="w-3.5 h-3.5 text-blue-550 dark:text-[var(--info)]" />
                  <span>调试发送联通测试 Card</span>
                </button>
              </div>
              <div className="flex items-end pt-3">
                <button
                  type="button"
                  onClick={() => fireFeishuTest('text')}
                  className="w-full py-1.5 border border-zinc-200 dark:border-[var(--surface-border)] bg-white dark:bg-[var(--surface)] hover:bg-zinc-50 dark:hover:bg-[var(--surface-muted)] text-zinc-700 dark:text-[var(--text-primary)] rounded-lg font-sans text-xs font-semibold shadow-2xs transition cursor-pointer flex items-center justify-center space-x-1.5"
                >
                  <Send className="w-3.5 h-3.5 text-purple-600 dark:text-[var(--info)]" />
                  <span>调试发送联通测试 Text</span>
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Accordions 6: GitHub publishing */}
        <div className="border border-zinc-200 dark:border-[var(--surface-border)] rounded-xl overflow-hidden bg-white dark:bg-[var(--surface)] shadow-2xs">
          <div
            onClick={() => toggleSection('publishing')}
            className="p-4 bg-white dark:bg-[var(--surface)] border-b border-zinc-200 dark:border-[var(--surface-border)] flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 dark:hover:bg-[var(--surface-muted)] transition select-none"
          >
            <div className="flex items-center space-x-3 text-zinc-900 dark:text-[var(--text-primary)]">
              <Github className="w-4 h-4 text-zinc-600 dark:text-[var(--text-secondary)]" />
              <span className="font-sans font-semibold text-sm">6. GitHub Pages 发布与 Markdown 同步</span>
            </div>
            {openSections.publishing ? <ChevronUp className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" /> : <ChevronDown className="w-4 h-4 text-zinc-500 dark:text-[var(--text-secondary)]" />}
          </div>

          {openSections.publishing && (
            <div className="p-6 space-y-4 font-sans text-sm">
              <div className={`rounded-lg border px-4 py-3 text-xs leading-5 ${githubPagesPublicBaseUrl.trim() && !githubPagesPublicBaseUrl.includes('${') ? 'border-emerald-100 dark:border-[var(--success-border)] bg-emerald-50 dark:bg-[var(--success-bg)] text-emerald-800 dark:text-[var(--success)]' : 'border-amber-100 dark:border-[var(--warning-border)] bg-amber-50 dark:bg-[var(--warning-bg)] text-amber-800 dark:text-[var(--warning)]'}`}>
                {githubPagesPublicBaseUrl.trim() && !githubPagesPublicBaseUrl.includes('${')
                  ? 'GitHub Pages public_base_url 已配置，飞书“阅读全文”将优先指向线上 HTML。'
                  : '尚未配置 KENRADAR_GITHUB_PAGES_URL，飞书“阅读全文”会回退本地 Web 链接。'}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={githubPagesEnabled}
                    onChange={(e) => setGithubPagesEnabled(e.target.checked)}
                    className="rounded border-zinc-350 text-blue-600 focus:ring-blue-500 w-4 h-4 accent-blue-600 cursor-pointer"
                  />
                  <span className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-medium">启用 GitHub Pages HTML 发布</span>
                </label>

                <label className="flex items-center space-x-3">
                  <input
                    type="checkbox"
                    checked={githubSyncEnabled}
                    onChange={(e) => setGithubSyncEnabled(e.target.checked)}
                    className="rounded border-zinc-350 dark:border-[var(--surface-border)] text-blue-600 dark:text-[var(--info)] focus:ring-blue-500 dark:focus:ring-[var(--info)] w-4 h-4 accent-blue-600 dark:accent-[var(--info)] cursor-pointer"
                  />
                  <span className="text-xs text-zinc-650 dark:text-[var(--text-secondary)] font-medium">启用 GitHub Sync 命令</span>
                </label>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">HTML 输出目录</label>
                  <input
                    type="text"
                    value={githubPagesOutputDir}
                    onChange={(e) => setGithubPagesOutputDir(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">GitHub Pages Public Base URL</label>
                  <input
                    type="text"
                    value={githubPagesPublicBaseUrl}
                    onChange={(e) => setGithubPagesPublicBaseUrl(e.target.value)}
                    placeholder="${KENRADAR_GITHUB_PAGES_URL}"
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">Git 仓库目录</label>
                  <input
                    type="text"
                    value={githubSyncRepoDir}
                    onChange={(e) => setGithubSyncRepoDir(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs text-zinc-500 dark:text-[var(--text-secondary)] font-semibold block font-mono uppercase">同步分支</label>
                  <input
                    type="text"
                    value={githubSyncBranch}
                    onChange={(e) => setGithubSyncBranch(e.target.value)}
                    className="w-full bg-white dark:bg-[var(--surface)] border border-zinc-200 dark:border-[var(--surface-border)] focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 rounded-lg border border-zinc-150 dark:border-[var(--surface-border)] bg-zinc-50 dark:bg-[var(--surface-muted)] p-4">
                {[
                  ['同步 HTML docs', githubSyncIncludeHtmlDocs, setGithubSyncIncludeHtmlDocs],
                  ['同步 Markdown 笔记', githubSyncIncludeMarkdownNotes, setGithubSyncIncludeMarkdownNotes],
                  ['同步简报/周报/研究报告', githubSyncIncludeBriefs, setGithubSyncIncludeBriefs],
                  ['允许包含视频原始转录', githubSyncIncludeTranscripts, setGithubSyncIncludeTranscripts],
                  ['自动 commit', githubSyncAutoCommit, setGithubSyncAutoCommit],
                  ['自动 push', githubSyncAutoPush, setGithubSyncAutoPush],
                ].map(([label, checked, setter]) => (
                  <label key={String(label)} className="flex items-center space-x-3">
                    <input
                      type="checkbox"
                      checked={Boolean(checked)}
                      onChange={(e) => (setter as React.Dispatch<React.SetStateAction<boolean>>)(e.target.checked)}
                      className="rounded border-zinc-350 text-blue-600 focus:ring-blue-500 w-4 h-4 accent-blue-600 cursor-pointer"
                    />
                    <span className="text-xs text-zinc-650 font-medium">{String(label)}</span>
                  </label>
                ))}
              </div>

              <p className="text-[10px] leading-5 text-zinc-400">
                GitHub Sync 不会上传视频、下载中转文件、日志、Cookie、.env 或 API Key；同步命令会在 git add 前做敏感文件检查。
              </p>
            </div>
          )}
        </div>

        {/* Accordions 7: Security / Web (安全监控配置) */}
        <div className="border border-zinc-200 rounded-xl overflow-hidden bg-white shadow-2xs">
          <div
            onClick={() => toggleSection('security')}
            className="p-4 bg-white border-b border-zinc-200 flex items-center justify-between cursor-pointer hover:bg-zinc-50/50 transition select-none"
          >
            <div className="flex items-center space-x-3 text-zinc-900">
              <Lock className="w-4 h-4 text-zinc-550" />
              <span className="font-sans font-semibold text-sm">7. Web 控制台端口与安全阻断</span>
            </div>
            {openSections.security ? <ChevronUp className="w-4 h-4 text-zinc-500" /> : <ChevronDown className="w-4 h-4 text-zinc-500" />}
          </div>

          {openSections.security && (
            <div className="p-6 space-y-4 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4 font-sans text-sm">
              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 font-semibold block font-mono uppercase">服务托管本地侦听端口 (Web Port)</label>
                <input
                  type="number"
                  disabled
                  value={webPort}
                  className="w-full bg-zinc-50 text-zinc-400 border border-zinc-200 cursor-not-allowed rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
                <span className="text-[10px] text-zinc-400 block font-sans">端口由 KenRadar 启动命令与 app.web_base_url 控制，当前页面仅展示运行值。</span>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs text-zinc-500 font-semibold block font-mono uppercase">安全绑定外部宿主 IP (Bind IP)</label>
                <input
                  type="text"
                  value={webBind}
                  onChange={(e) => setWebBind(e.target.value)}
                  className="w-full bg-white border border-zinc-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
              </div>

              <div className="flex items-center space-x-3 pt-3.5 md:col-span-2">
                <input
                  type="checkbox"
                  id="pwd_auth_cb"
                  checked={passwordAuth}
                  onChange={(e) => setPasswordAuth(e.target.checked)}
                  className="rounded border-zinc-350 text-blue-600 focus:ring-blue-500 w-4 h-4 accent-blue-600 cursor-pointer"
                />
                <label htmlFor="pwd_auth_cb" className="text-xs text-zinc-650 font-medium select-none cursor-pointer">
                  开启密码校验 (非内网地址访问强制校验 access_token 安全卡哨码)
                </label>
              </div>

              <div className="space-y-1.5 md:col-span-2">
                <label className="text-xs text-zinc-500 font-semibold block font-mono uppercase">更新 Web 访问密码</label>
                <input
                  type="password"
                  value={webPassword}
                  onChange={(e) => setWebPassword(e.target.value)}
                  placeholder="留空保留现有密码；关闭密码校验并保存会清空 app.web_password"
                  className="w-full bg-white border border-zinc-200 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 rounded px-3 py-1.5 text-xs font-mono focus:outline-none transition"
                />
                <span className="text-[10px] text-zinc-400 block font-sans">后端不会回传现有密码明文；只在此处填入新密码时更新。</span>
              </div>
            </div>
          )}
        </div>

        {/* Global form submit actions */}
        <div className="pt-4 flex items-center justify-end">
          <button
            type="submit"
            className="flex items-center space-x-2 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-sans text-sm font-semibold shadow-xs transition cursor-pointer hover:shadow-sm"
          >
            <Save className="w-4 h-4 text-white" />
            <span>立即应用保存配置并重启内核 (Hotload config.yaml)</span>
          </button>
        </div>

      </form>
    </div>
  );
}
