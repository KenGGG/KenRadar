import assert from 'node:assert/strict';
import { taskPresentation, contentIssueKind, initialRunSection } from './RunCenterModel';

const base = { status: 'running', display_status: 'running', pause_requested: false, cancel_requested: false };
assert.equal(taskPresentation(base).action, 'pause');
assert.equal(taskPresentation({ ...base, pause_requested: true }).action, undefined);
assert.equal(taskPresentation({ ...base, cancel_requested: true }).label, '取消中');
assert.equal(taskPresentation({ ...base, status: 'paused', display_status: 'paused' }).action, 'resume');
assert.equal(taskPresentation({ ...base, display_status: 'interrupted' }).action, undefined);
assert.equal(taskPresentation({ ...base, status: 'failed', display_status: 'failed', last_error: '不支持的链接来源: Firstory' }).hint.includes('链接'), true);
assert.equal(taskPresentation({ ...base, status: 'failed', display_status: 'retired' }).label, '已退役功能');
assert.equal(contentIssueKind({ status: 'failed', summary_path: 'note.md', summary_status: 'success', failed_at_step: 'push' }), 'delivery');
assert.equal(contentIssueKind({ status: 'failed', summary_path: 'note.md', summary_status: 'failed', failed_at_step: 'ai' }), 'degraded');
assert.equal(contentIssueKind({ status: 'failed', summary_path: 'note.md', summary_status: 'pending', failed_at_step: 'download' }), 'failure');
assert.equal(contentIssueKind({ status: 'completed', summary_status: 'success' }), undefined);
assert.equal(initialRunSection('/failures', ''), 'attention');
assert.equal(initialRunSection('/run', '?view=history'), 'history');
assert.equal(initialRunSection('/run', ''), 'active');
console.log('RunCenter V2 classification passed');
