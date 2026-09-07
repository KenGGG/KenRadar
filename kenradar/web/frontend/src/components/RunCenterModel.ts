import { VideoContent } from '../types';

export type RunSection = 'active' | 'attention' | 'history';
export interface DurableTask {
  id: number;
  task_type: string;
  task_label: string;
  status: string;
  display_status: string;
  message: string;
  priority: number;
  attempt: number;
  max_attempts: number;
  last_error?: string;
  error_code?: string;
  created_at: string;
  updated_at: string;
  started_at?: string;
  finished_at?: string;
  available_at?: string;
  heartbeat_at?: string;
  pause_requested: boolean;
  cancel_requested: boolean;
  progress_json?: Record<string, unknown>;
}
export interface RunCenterData {
  items: DurableTask[];
  counts: Record<RunSection, number>;
  total: number;
}

export const SECTION_LABELS: Record<RunSection, string> = { active: '执行队列', attention: '待处理', history: '历史记录' };
export const STATUS_LABELS: Record<string, string> = {
  running: '执行中', queued: '排队中', retry_wait: '等待自动重试', paused: '已暂停',
  interrupted: '等待回收', failed: '执行失败', partial_failed: '部分失败',
  success: '已成功', cancelled: '已取消', retired: '已退役功能',
};
export const SECTION_STATUSES: Record<RunSection, string[]> = {
  active: ['running', 'queued', 'retry_wait'],
  attention: ['failed', 'partial_failed', 'paused', 'interrupted'],
  history: ['success', 'cancelled', 'retired'],
};

export function initialRunSection(path: string, search: string): RunSection {
  const view = new URLSearchParams(search).get('view');
  if (view === 'attention' || view === 'history') return view;
  return path === '/failures' || path.startsWith('/operations') ? 'attention' : 'active';
}

export function taskPresentation(task: Pick<DurableTask, 'status' | 'display_status' | 'pause_requested' | 'cancel_requested'> & Partial<DurableTask>): { label: string; hint: string; action?: 'pause' | 'resume' } {
  const state = task.display_status;
  const label = STATUS_LABELS[state] || '状态待确认';
  if (['running', 'queued', 'retry_wait'].includes(state)) {
    if (task.cancel_requested) return { label: '取消中', hint: '正在等待当前步骤安全退出。' };
    if (task.pause_requested) return { label: '暂停中', hint: '将在安全边界保存进度并暂停。' };
    return { label, hint: state === 'retry_wait' ? '系统会在下次尝试时间自动重试，无需重复提交。' : state === 'queued' ? '等待处理器按优先级领取。' : '处理器持有有效租约，正在执行。', action: 'pause' };
  }
  if (state === 'paused') return { label, hint: '进度已保留，继续后重新进入队列。', action: 'resume' };
  if (state === 'interrupted') return { label, hint: '没有有效执行租约，等待处理器回收；持续存在时请检查系统状态。' };
  if (state === 'retired') return { label, hint: '旧功能执行记录，仅供追溯。' };
  if (state === 'cancelled') return { label, hint: '任务已终止，不计入成功或待修复。' };
  if (state === 'failed' || state === 'partial_failed') {
    const unsupported = /不支持|unsupported/i.test(task.last_error || '');
    return { label, hint: unsupported ? '请换用支持的来源链接；重复提交相同链接无法解决。' : task.error_code === 'AUTH_REQUIRED' ? '请先更新来源授权，再重新提交任务。' : state === 'partial_failed' ? '部分内容已完成，请查看批次或内容详情，只处理失败部分。' : `自动尝试已结束（${task.attempt ?? 0}/${task.max_attempts ?? 0}）。请先排查原因，再按需重新提交。` };
  }
  return { label, hint: state === 'success' ? '本次执行已完成。' : '请查看原始状态并检查系统日志。' };
}

export function contentIssueKind(video: Partial<VideoContent>): 'degraded' | 'delivery' | 'failure' | undefined {
  if (video.status !== 'failed') return;
  const stage = video.failed_at_step || video.failure_stage;
  if (stage === 'push') return 'delivery';
  if (video.summary_path && video.summary_status === 'failed' && stage === 'ai') return 'degraded';
  return 'failure';
}
