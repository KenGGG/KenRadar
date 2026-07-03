/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect, useCallback } from 'react';
import { VideoContent, ResearchTask, MonitorSource, PushRecord, SystemLog, SystemConfig, AlertRecord, SystemInfo, NoteFile, BriefFile, LibraryStats } from '../types';
import { DEFAULT_CONFIG } from '../mockData';

type BootstrapPayload = {
  videos: VideoContent[];
  libraryStats?: LibraryStats;
  tasks: ResearchTask[];
  sources: MonitorSource[];
  sourceCategories: string[];
  pushRecords: PushRecord[];
  logs: SystemLog[];
  config: SystemConfig;
  alerts: AlertRecord[];
  system: SystemInfo;
  notes: NoteFile[];
  briefs: BriefFile[];
};

const DEFAULT_LIBRARY_STATS: LibraryStats = {
  total_items: 0,
  content_notes: 0,
  transcripts: 0,
  loaded_items: 0,
  display_limit: 5000,
};

const DEFAULT_SYSTEM: SystemInfo = {
  port: 8765,
  gpu_label: 'GPU 调度',
  gpu_status: '未知',
  gpu_percent: null,
  whisper_model: 'large-v3-turbo',
  log_path: 'data/kenradar.log',
  health: {},
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    credentials: 'same-origin',
    headers: init?.body instanceof FormData ? undefined : { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  const text = await response.text();
  const payload = text ? JSON.parse(text) : {};
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || `请求失败: ${response.status}`);
  }
  return payload as T;
}

function formBody(values: Record<string, string | number | boolean | undefined>) {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value === undefined || value === false) return;
    params.set(key, value === true ? 'on' : String(value));
  });
  return params;
}

async function requestForm<T>(url: string, values: Record<string, string | number | boolean | undefined>): Promise<T> {
  return requestJson<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: formBody(values).toString(),
  });
}

function pageFromPath(pathname: string) {
  if (pathname.startsWith('/archive') || pathname === '/items' || pathname === '/notes' || pathname === '/briefs') return 'archive';
  if (pathname.startsWith('/research')) return 'research';
  if (pathname.startsWith('/company-research')) return 'radar';
  if (pathname.startsWith('/publish')) return 'publish';
  if (pathname.startsWith('/ops')) return 'run';
  if (pathname.startsWith('/sources')) return 'sources';
  if (pathname.startsWith('/run')) return 'run';
  if (pathname.startsWith('/operations') || pathname === '/failures') return 'run';
  if (pathname.startsWith('/logs') || pathname === '/pushes') return 'run';
  if (pathname.startsWith('/config')) return 'config';
  return 'radar';
}

export function useAppState() {
  const [currentPage, setCurrentPage] = useState<string>('radar');
  const [selectedVideoId, setSelectedVideoId] = useState<string | null>(null);
  const [videos, setVideos] = useState<VideoContent[]>([]);
  const [libraryStats, setLibraryStats] = useState<LibraryStats>(DEFAULT_LIBRARY_STATS);
  const [tasks, setTasks] = useState<ResearchTask[]>([]);
  const [sources, setSources] = useState<MonitorSource[]>([]);
  const [sourceCategories, setSourceCategories] = useState<string[]>([]);
  const [pushRecords, setPushRecords] = useState<PushRecord[]>([]);
  const [logs, setLogs] = useState<SystemLog[]>([]);
  const [config, setConfig] = useState<SystemConfig>(DEFAULT_CONFIG);
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [system, setSystem] = useState<SystemInfo>(DEFAULT_SYSTEM);
  const [notes, setNotes] = useState<NoteFile[]>([]);
  const [briefs, setBriefs] = useState<BriefFile[]>([]);
  const [isInitializing, setIsInitializing] = useState(true);

  const appendLog = useCallback((level: SystemLog['level'], module: SystemLog['module'], message: string) => {
    const row: SystemLog = {
      id: `web_${Date.now()}`,
      timestamp: new Date().toISOString().replace('T', ' ').substring(0, 19),
      level,
      module,
      message,
    };
    setLogs(prev => [row, ...prev].slice(0, 200));
  }, []);

  const loadBootstrap = useCallback(async () => {
    const data = await requestJson<BootstrapPayload>('/api/bootstrap');
    setVideos(data.videos || []);
    setLibraryStats({ ...DEFAULT_LIBRARY_STATS, ...(data.libraryStats || {}), loaded_items: data.libraryStats?.loaded_items ?? (data.videos || []).length });
    setTasks(data.tasks || []);
    setSources(data.sources || []);
    setSourceCategories(data.sourceCategories || []);
    setPushRecords(data.pushRecords || []);
    setLogs((data.logs || []).map((log: SystemLog) => (
      log.module === 'Ollama' ? { ...log, module: 'AI' as const } : log
    )));
    setConfig(data.config || DEFAULT_CONFIG);
    setAlerts(data.alerts || []);
    setSystem(data.system || DEFAULT_SYSTEM);
    setNotes(data.notes || []);
    setBriefs(data.briefs || []);
  }, []);

  useEffect(() => {
    loadBootstrap()
      .catch(error => appendLog('error', 'WebUI', error.message))
      .finally(() => setIsInitializing(false));
  }, [appendLog, loadBootstrap]);

  useEffect(() => {
    const handleLocationChange = () => {
      const params = new URLSearchParams(window.location.search);
      const pathname = window.location.pathname;
      const awemeId = params.get('id');
      const pageParam = params.get('page');

      if (awemeId) {
        setSelectedVideoId(awemeId);
        setCurrentPage('detail');
        return;
      }
      setSelectedVideoId(null);
      if (pathname.startsWith('/run') && params.get('tab') === 'history') {
        setCurrentPage('publish');
        return;
      }
      setCurrentPage(pageParam || pageFromPath(pathname));
    };

    window.addEventListener('popstate', handleLocationChange);
    handleLocationChange();
    return () => window.removeEventListener('popstate', handleLocationChange);
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      requestJson<Record<string, any>>('/api/status')
        .then(taskState => {
          setSystem(prev => ({
            ...prev,
            background_task: {
              running: Boolean(taskState.running),
              message: String(taskState.message || '空闲'),
              started_at: taskState.started_at || null,
              finished_at: taskState.finished_at || null,
              status: String(taskState.status || 'idle'),
              requested_by: String(taskState.requested_by || ''),
              queue: taskState.queue || [],
              progress: taskState.progress || undefined,
            },
            runtime_timeline: taskState.runtime_timeline || prev.runtime_timeline,
          }));
        })
        .catch(() => undefined);
    }, 10000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const refreshResearchTasks = () => {
      requestJson<{ items: ResearchTask[] }>('/api/research/jobs')
        .then(data => setTasks(data.items || []))
        .catch(() => undefined);
    };
    const timer = window.setInterval(() => {
      const hasActiveTask = tasks.some(task => task.status === 'processing' || task.status === 'queued' || task.status === 'paused');
      if (currentPage === 'research' || currentPage === 'run' || hasActiveTask) {
        refreshResearchTasks();
      }
    }, 8000);
    return () => window.clearInterval(timer);
  }, [currentPage, tasks]);

  const navigateTo = useCallback((page: string, id: string | null = null) => {
    const pagePaths: Record<string, string> = {
      radar: '/',
      archive: '/archive',
      research: '/research',
      sources: '/sources',
      run: '/run',
      publish: '/run?tab=history',
      operations: '/operations',
      monitor: '/logs/status',
      config: '/config',
    };
    const newUrl = id ? `/aweme?id=${encodeURIComponent(id)}` : (pagePaths[page] || `/?page=${encodeURIComponent(page)}`);
    window.history.pushState(null, '', newUrl);
    setSelectedVideoId(id);
    setCurrentPage(id ? 'detail' : page);
  }, []);

  const refreshAfter = useCallback(async (message?: string) => {
    if (message) appendLog('info', 'WebUI', message);
    await loadBootstrap();
  }, [appendLog, loadBootstrap]);

  const rebootWebUI = useCallback(async () => {
    await requestJson('/api/restart-web', { method: 'POST', body: '{}' });
    appendLog('warn', 'WebUI', 'Web 重启指令已投递，请稍后刷新页面。');
  }, [appendLog]);

  const saveConfig = useCallback(async (newConfig: SystemConfig) => {
    await requestJson('/api/config', { method: 'POST', body: JSON.stringify(newConfig) });
    setConfig(newConfig);
    await refreshAfter('配置已保存到 config/config.yaml。');
  }, [refreshAfter]);

  const addSource = useCallback(async (url: string, category: string, platform: 'douyin' | 'xiaoyuzhou' = 'douyin') => {
    const result = await requestJson<{ source?: { name?: string } }>('/api/source/add', {
      method: 'POST',
      body: JSON.stringify({ platform, url, category, enabled: true }),
    });
    await refreshAfter(`已登记监控源：${result.source?.name || url}`);
  }, [refreshAfter]);

  const previewSource = useCallback(async (url: string, platform: 'xiaoyuzhou') => {
    const result = await requestJson<{ preview: Record<string, any> }>('/api/source/preview', {
      method: 'POST',
      body: JSON.stringify({ platform, url }),
    });
    return result.preview;
  }, []);

  const checkSourceNow = useCallback(async (id: string) => {
    const source = sources.find(item => item.id === id);
    await requestJson('/api/source/check', {
      method: 'POST',
      body: JSON.stringify({ id, publish: false, push: false }),
    });
    await refreshAfter(`已提交来源检查：${source?.name || id}`);
  }, [refreshAfter, sources]);

  const toggleSourceStatus = useCallback(async (id: string) => {
    const source = sources.find(item => item.id === id);
    if (!source) return;
    await requestJson('/api/source/toggle', { method: 'POST', body: JSON.stringify({ id }) });
    await refreshAfter(`来源状态已切换：${source.name}`);
  }, [refreshAfter, sources]);

  const updateSourceCategory = useCallback(async (id: string, category: string) => {
    const source = sources.find(item => item.id === id);
    if (!source) return;
    await requestJson('/api/source/category', { method: 'POST', body: JSON.stringify({ id, category }) });
    await refreshAfter(`来源分类已保存：${source.name}`);
  }, [refreshAfter, sources]);

  const updateSourceCategoryOption = useCallback(async (action: 'add' | 'delete', category: string) => {
    await requestJson('/api/source/categories', { method: 'POST', body: JSON.stringify({ action, category }) });
    await refreshAfter(action === 'add' ? `来源分类已新增：${category}` : `来源分类已删除：${category}`);
  }, [refreshAfter]);

  const deleteSource = useCallback(async (id: string) => {
    const source = sources.find(item => item.id === id);
    if (!source) return;
    await requestJson('/api/source/delete', { method: 'POST', body: JSON.stringify({ id }) });
    await refreshAfter(`来源已移出监控：${source.name}`);
  }, [refreshAfter, sources]);

  const triggerManualScan = useCallback(async () => {
    await requestJson('/api/run-once', { method: 'POST', body: '{}' });
    await refreshAfter('手动检测任务已加入后台队列。');
  }, [refreshAfter]);

  const testLatest = useCallback(async () => {
    await requestJson('/api/test-latest', { method: 'POST', body: '{}' });
    await refreshAfter('测试最新任务已加入后台队列。');
  }, [refreshAfter]);

  const runResearchTask = useCallback(async (type: 'single' | 'blogger', targetValue: string, forceRetry: boolean, limit = 20) => {
    const endpoint = type === 'single' ? '/api/research-video' : '/api/research-blogger';
    if (type === 'single') {
      await requestForm(endpoint, { video: targetValue, force: forceRetry, push: false });
    } else {
      await requestForm(endpoint, { blogger: targetValue.replace(/\s*\(限制前.*$/, ''), limit, force: forceRetry, push: false });
    }
    await refreshAfter('研究任务已提交。');
  }, [refreshAfter]);

  const controlResearchTask = useCallback(async (taskId: string, action: 'pause' | 'resume' | 'cancel' | 'restart') => {
    const endpoint = action === 'pause'
      ? '/api/research/pause'
      : action === 'resume'
        ? '/api/research/resume'
        : action === 'cancel'
          ? '/api/research/cancel'
          : '/api/research/restart';
    await requestJson(`${endpoint}?id=${encodeURIComponent(taskId)}`, { method: 'POST', body: '{}' });
    await refreshAfter(`研究任务 #${taskId} 已提交${action}指令。`);
  }, [refreshAfter]);

  const loadResearchJob = useCallback(async (taskId: string) => {
    return requestJson<{ job: Record<string, any>; items: Record<string, any>[]; pipeline: Record<string, any> }>(
      `/api/research/job?id=${encodeURIComponent(taskId)}`
    );
  }, []);

  const retryResearchFailed = useCallback(async (taskId: string) => {
    await requestJson(`/api/retry-research-failed?id=${encodeURIComponent(taskId)}`, { method: 'POST', body: '{}' });
    await refreshAfter(`研究任务 #${taskId} 的失败条目已加入重试队列。`);
  }, [refreshAfter]);

  const retryStage = useCallback(async (awemeId: string, stage?: 'download' | 'transcribe' | 'ai' | 'push') => {
    const endpoint = stage === 'download'
      ? '/api/retry-download'
      : stage === 'transcribe'
        ? '/api/retry-transcribe'
        : stage === 'ai'
          ? '/api/retry-summary'
          : '/api/retry-full';
    await requestJson(`${endpoint}?id=${encodeURIComponent(awemeId)}`, { method: 'POST', body: '{}' });
    await refreshAfter(`已提交重试：${awemeId}`);
  }, [refreshAfter]);

  const bulkRetryFailed = useCallback(async (step?: 'download' | 'transcribe' | 'ai' | 'push') => {
    const targets = videos.filter(video => video.status === 'failed' && (!step || video.failed_at_step === step)).map(video => video.id);
    if (!targets.length) return;
    await requestForm('/api/retry-batch', { aweme_ids: targets.join(','), retry_from: step || 'auto' });
    await refreshAfter(`已提交批量重试：${targets.length} 条`);
  }, [refreshAfter, videos]);

  const pushToFeishuManually = useCallback(async (awemeId: string) => {
    await requestJson(`/api/repush-aweme?id=${encodeURIComponent(awemeId)}`, { method: 'POST', body: '{}' });
    await refreshAfter(`已请求重新推送飞书：${awemeId}`);
  }, [refreshAfter]);

  const generateWeeklyBrief = useCallback(async () => {
    const payload = await requestJson<{ message?: string; path?: string }>('/api/generate-weekly', { method: 'POST', body: '{}' });
    await refreshAfter(payload.message || '周报已生成。');
    return payload.path || payload.message || '周报已生成。';
  }, [refreshAfter]);

  return {
    currentPage,
    navigateTo,
    selectedVideoId,
    videos,
    libraryStats,
    tasks,
    sources,
    sourceCategories,
    pushRecords,
    logs,
    config,
    alerts,
    system,
    notes,
    briefs,
    isInitializing,
    rebootWebUI,
    saveConfig,
    addSource,
    previewSource,
    checkSourceNow,
    updateSourceCategory,
    updateSourceCategoryOption,
    toggleSourceStatus,
    deleteSource,
    triggerManualScan,
    testLatest,
    runResearchTask,
    controlResearchTask,
    loadResearchJob,
    retryResearchFailed,
    retryStage,
    bulkRetryFailed,
    pushToFeishuManually,
    generateWeeklyBrief,
    setVideos,
    setTasks,
    setPushRecords,
    setLogs,
  };
}
