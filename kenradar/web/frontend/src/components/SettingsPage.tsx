import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';

type SecretState = { configured: boolean; source: string };
type Snapshot = { groups: Record<string, Record<string, unknown>>; secrets: Record<string, Record<string, SecretState>>; revision: string; running_revisions: {task_run_id: number; revision: string}[]; overrides: Record<string, { source: string; variable: string }> };
const labels: Record<string, string> = { overview: '配置概览', accounts: '来源账号', transcription_ai: '转录与 AI', automatic: '自动处理', notes_storage: '笔记与存储', delivery: '发布与通知', backup: '备份与恢复', security: '访问保护' };
const fieldLabels: Record<string, string> = { 'app.timezone': '时区', 'app.douyin_cookie_file': '抖音 Cookie 文件', 'ai.funasr.enabled': '启用 FunASR', 'ai.funasr.managed': '托管 FunASR 服务', 'ai.funasr.endpoint': 'FunASR 地址', 'ai.whisper.enabled': '启用 Whisper 兜底', 'ai.whisper.model': 'Whisper 模型', 'ai.whisper.device': 'Whisper 计算设备', 'ai.whisper.compute_type': 'Whisper 精度', 'ai.organizer.providers': 'AI 服务列表（高级 JSON）', 'schedule.enabled': '定时检测', 'schedule.source_radar_enabled': '来源订阅监控', 'schedule.times': '每日检测时间（用逗号分隔）', 'download.workers': '同时下载数量', 'app.data_dir': '数据目录', 'app.database_url': 'SQLite 数据库文件 URL', 'download.path': '下载中转目录', 'publishing.github_pages.enabled': '生成公共 HTML', 'publishing.github_pages.public_base_url': '公开站点地址', 'publishing.github_sync.enabled': 'GitHub 同步', 'publishing.github_sync.auto_push': '允许自动推送', 'notification.enabled': '通知总开关', 'notification.channels.feishu.enabled': '飞书通知', 'notification.channels.feishu.include_full_text': '通知包含全文', 'app.web_base_url': 'Web 访问地址' };
const schema = z.object({ fields: z.record(z.string(), z.string()), secrets: z.record(z.string(), z.object({ action: z.enum(['keep', 'replace', 'delete']), value: z.string() })) });
type Form = z.infer<typeof schema>;
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const value = await response.json();
  if (!response.ok || value.ok === false) throw new Error(response.status === 409 ? '配置已被其他窗口修改。草稿已保留，请刷新后合并。' : value.message || '操作未通过或结果未知，配置尚未保存。');
  return value as T;
}

function buildDraft(data: Form, group: string, revision: string) {
  const values = Object.fromEntries(Object.entries(data.fields).map(([key, value]) => {
    const parsed: unknown = JSON.parse(value);
    if (key === 'ai|organizer|providers' && Array.isArray(parsed)) {
      for (const provider of parsed) if (provider && typeof provider === 'object') for (const field of Object.keys(provider)) if (/api[_-]?key|password|cookie|authorization/i.test(field)) delete provider[field];
    }
    return [key.replaceAll('|', '.'), parsed];
  }));
  const secrets = Object.fromEntries(Object.entries(data.secrets).map(([key, value]) => [key.replaceAll('|', '.'), {...value, value: value.action === 'replace' ? value.value : ''}]));
  return { group, expected_revision: revision, values, secrets };
}

function fieldText(key: string, value: unknown): string {
  if (key === 'ai.organizer.providers' && Array.isArray(value)) value = value.map(provider => Object.fromEntries(Object.entries(provider).filter(([field]) => !/api[_-]?key|cookie|password|authorization/i.test(field))));
  return JSON.stringify(value, null, 2);
}

export default function SettingsPage() {
  const cache = useQueryClient();
  const snapshot = useQuery({ queryKey: ['settings'], queryFn: () => request<Snapshot>('/api/settings'), refetchOnWindowFocus: false });
  const [group, setGroup] = useState('overview');
  const [message, setMessage] = useState('');
  const [dirty, setDirty] = useState(false);
  if (snapshot.isPending) return <p role="status">正在读取设置…</p>;
  if (snapshot.isError) return <div role="alert">{snapshot.error.message}<button onClick={() => snapshot.refetch()}>重试</button></div>;
  return <section className="space-y-6 max-w-5xl mx-auto p-4 text-[var(--text-primary)]">
    <header><h1 className="text-2xl font-semibold">设置</h1><p className="text-sm text-[var(--text-secondary)] mt-2">保存与校验不会发布或发送消息。联网测试单独确认。</p></header>
    <div className="flex flex-wrap gap-2">{Object.entries(labels).map(([id, label]) => <button key={id} className={`px-3 py-2 rounded border ${group === id ? 'bg-blue-600 text-white' : ''}`} onClick={() => { if (id !== group && (!dirty || window.confirm('本组有未保存草稿，放弃后切换？'))) { setGroup(id); setMessage(''); setDirty(false); } }}>{label}</button>)}</div>
    {message && <p role="status">{message}</p>}
    <GroupForm key={group} group={group} snapshot={snapshot.data} onDirty={setDirty} onSaved={async () => { await cache.invalidateQueries({ queryKey: ['settings'] }); }} report={setMessage} />
  </section>;
}

function GroupForm({ group, snapshot, onSaved, report, onDirty }: { group: string; snapshot: Snapshot; onSaved: () => Promise<void>; report: (value: string) => void; onDirty: (value: boolean) => void }) {
  const [baseline, setBaseline] = useState(snapshot);
  const values = baseline.groups[group];
  const secretStates = baseline.secrets[group] || {};
  const form = useForm<Form>({ resolver: zodResolver(schema), defaultValues: { fields: Object.fromEntries(Object.entries(values).map(([key, value]) => [key.replaceAll('.', '|'), fieldText(key,value)])), secrets: Object.fromEntries(Object.keys(secretStates).map(key => [key.replaceAll('.', '|'), { action: 'keep', value: '' }])) } });
  const dirty = form.formState.isDirty;
  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => { const leave = (event: Event) => { if (dirty && !window.confirm('设置有未保存草稿，放弃后离开？')) event.preventDefault(); }; window.addEventListener('kenradar:navigate', leave); return () => window.removeEventListener('kenradar:navigate', leave); }, [dirty]);
  useEffect(() => { const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn); }, [dirty]);
  const operation = useMutation({ mutationFn: async ({ data, save }: { data: Form; save: boolean }) => {
    return request<{ restart_required: boolean }>('/api/settings' + (save ? '' : '/validate'), { method: save ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(buildDraft(data, group, baseline.revision)) });
  }, onError: error => report(error.message), onSuccess: async (result, input) => {
    if (input.save) { const fresh = await request<Snapshot>('/api/settings'); setBaseline(fresh); form.reset({...input.data,secrets:Object.fromEntries(Object.keys(fresh.secrets[group] || {}).map(key => [key.replaceAll('.', '|'),{action:'keep',value:''}]))}); await onSaved(); report(result.restart_required ? '已保存，需重启后生效。' : '已保存，后续任务使用新配置；运行中任务保持原配置。'); }
    else report('草稿校验通过，尚未保存。');
  } });
  const test = useMutation({ mutationFn: async ({data, kind}: {data: Form; kind: 'ai_readonly' | 'github_dry_run' | 'feishu_send'}) => {
    return request<{scope?: string; sent_message: boolean}>('/api/settings/test', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({draft:buildDraft(data,group,baseline.revision),kind,confirmed_external:kind !== 'github_dry_run'})});
  }, onError: error => report(error.message), onSuccess: result => report(result.sent_message ? '测试消息已确认送达；草稿尚未保存。' : result.scope === 'local_git_only' ? '本地 Git 检查通过；尚未验证 GitHub 远端，未推送、未保存。' : '模型列表连接检查通过；尚未验证实际整理，草稿未保存。')});
  const busy = operation.isPending || test.isPending;
  const mergeLatest = async () => {
    try {
      const fresh = await request<Snapshot>('/api/settings');
        const secretEdits = Object.values(form.getValues('secrets')).some(edit => edit.action !== 'keep');
        if (group === 'transcription_ai' && secretEdits && fieldText('ai.providers', fresh.groups[group]['ai.providers']) !== fieldText('ai.providers', baseline.groups[group]['ai.providers'])) {
          report('服务器的 AI 服务列表已变化。密钥草稿仍保留，请先核对服务顺序，取消密钥修改后再合并。');
          return;
        }
      for (const [key,value] of Object.entries(fresh.groups[group])) {
        const encoded = key.replaceAll('.', '|');
        if (!form.formState.dirtyFields.fields?.[encoded]) form.setValue(`fields.${encoded}`,fieldText(key,value));
      }
      setBaseline(fresh);
      report('已加载最新版本，保留你修改的字段。请核对后再保存。');
      await onSaved();
    } catch (error) { report(error instanceof Error ? error.message : '读取最新版本失败，草稿保留。'); }
  };
  const runProbe = (kind: 'ai_readonly' | 'github_dry_run' | 'feishu_send') => form.handleSubmit(data => {
    const disclosure = kind === 'feishu_send' ? '会使用本次草稿的 Webhook，真实发送一条测试消息。确认发送？' : '会使用本次草稿联网读取 AI 模型列表，可能计入服务请求额度。不会上传研究内容。确认测试？';
    if (kind === 'github_dry_run' || window.confirm(disclosure)) test.mutate({data,kind});
  });
  // Snapshot refresh deliberately does not reset a draft. A changed revision is visible.
  return <form className="space-y-4" onSubmit={form.handleSubmit(data => operation.mutate({ data, save: true }))}>
    {snapshot.revision !== baseline.revision && <p role="alert">服务器配置版本已变化；当前草稿仍保留。</p>}
    <button type="button" className="text-sm underline" disabled={busy} onClick={mergeLatest}>加载最新配置，保留已编辑字段</button>
    {group === 'backup' && <p>离线备份和恢复工具已提供；此页的备份操作尚未接入。恢复仅写入独立演练目录。</p>}
    {Object.entries(values).map(([key, value]) => {
      const name = `fields.${key.replaceAll('.', '|')}` as const;
      const inputClass = 'block w-full rounded border p-2 bg-[var(--surface)] text-sm';
      return <label key={key} className="block space-y-1"><span className="text-sm">{key === 'ai.transcription.enabled' ? '启用转录' : fieldLabels[key] || key}{snapshot.overrides[key] && `（由 ${snapshot.overrides[key].variable} 环境变量覆盖）`}</span>
        {typeof value === 'boolean' ? <select aria-label={key} className={inputClass} {...form.register(name)}><option value="false">关闭</option><option value="true">开启</option></select>
          : key === 'schedule.times' ? <input aria-label={key} className={inputClass} value={(JSON.parse(form.watch(name) || '[]') as string[]).join(', ')} onChange={event => form.setValue(name, JSON.stringify(event.target.value.split(',').map(item => item.trim())), { shouldDirty: true })} />
          : typeof value === 'number' ? <input aria-label={key} type="number" min={1} max={16} className={inputClass} {...form.register(name)} />
          : typeof value === 'string' ? <input aria-label={key} className={inputClass} value={JSON.parse(form.watch(name) || '""') as string} onChange={event => form.setValue(name, JSON.stringify(event.target.value), { shouldDirty: true })} />
          : <textarea aria-label={key} className={`${inputClass} font-mono`} rows={6} {...form.register(name)} />}</label>;
    })}
    {Object.entries(secretStates).map(([key, state]) => <fieldset key={key} className="rounded border p-3 min-w-0"><legend className="text-sm break-all">{key.endsWith('.api_key') ? `AI 密钥 ${Number(key.split('.').at(-2)) + 1}` : key === 'cookies.douyin' ? '抖音 Cookie' : key === 'app.web_password' ? '访问密码' : '飞书 Webhook'}：{state.configured ? '已配置' : '未配置'}（{state.source === 'environment' ? '环境变量' : '本地配置'}）</legend><select aria-label={`${key} 操作`} {...form.register(`secrets.${key.replaceAll('.', '|')}.action`)}><option value="keep">保留</option><option value="replace">替换</option><option value="delete">删除</option></select><input type="password" autoComplete="new-password" aria-label={`${key} 新值`} className="block mt-2 w-full rounded border p-2 bg-[var(--surface)]" {...form.register(`secrets.${key.replaceAll('.', '|')}.value`)} />{state.source === 'environment' && <p className="text-xs mt-2">环境变量优先于本地配置；替换本地值不会清除环境变量。</p>}</fieldset>)}
    <p className="text-xs text-[var(--text-secondary)]">配置版本：{baseline.revision.slice(0, 12)}。{snapshot.running_revisions?.length ? snapshot.running_revisions.map(row => `任务 #${row.task_run_id} 使用 ${row.revision.slice(0,12)}`).join('；') : '当前没有运行中的任务。'}</p>
    <div className="flex flex-wrap gap-3"><button type="button" disabled={busy} className="rounded border px-4 py-2" onClick={form.handleSubmit(data => operation.mutate({ data, save: false }))}>校验草稿</button><button disabled={busy || group === 'backup'} className="rounded bg-blue-600 text-white px-4 py-2">{busy ? '处理中…' : '保存本组'}</button>
      {group === 'transcription_ai' && <button type="button" disabled={busy} className="rounded border px-4 py-2" onClick={runProbe('ai_readonly')}>测试 AI 连接</button>}
      {group === 'delivery' && <><button type="button" disabled={busy} className="rounded border px-4 py-2" onClick={runProbe('github_dry_run')}>GitHub 本地检查</button><button type="button" disabled={busy} className="rounded border px-4 py-2" onClick={runProbe('feishu_send')}>发送飞书测试消息</button></>}
    </div>
  </form>;
}
