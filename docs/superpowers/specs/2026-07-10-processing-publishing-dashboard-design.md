# Processing And Publishing Dashboard Reset

## Context

The current “处理与发布” area has grown into a mixed operations surface: pipeline status, retry management, publishing history, alerts, logs, model/GPU details, and Web restart actions all compete for attention. The original purpose was simpler: show how the KenRadar system is running, and provide a repair window when something fails.

## Product Goal

Reset “处理与发布” into a single-page operations dashboard.

The page should answer three questions in the first screen:

1. What is the system doing now?
2. What is waiting or recently completed?
3. What needs manual repair?

Repair is the only prominent manual operation. Publishing records, logs, model service status, and Web restart remain available, but become supporting details rather than primary tabs.

## User Model

The user should not need to decide which tab to open during normal use.

The default flow is:

1. Open “处理与发布”.
2. Read the system state banner.
3. Scan the pipeline progress and queue.
4. If failures exist, use the repair window.
5. Open secondary details only when investigating.

## Interface Structure

The page becomes a single dashboard with these sections:

1. **State Banner**
   - Shows one of three states: idle, running, needs repair.
   - Includes next scheduled run, active count, queued count, and repair count.
   - Keeps “手动检测” as a secondary action.

2. **Pipeline Progress**
   - Shows the main lifecycle: source check, download, transcription, AI note, HTML publish, Feishu push.
   - Uses current runtime timeline and task progress data when available.
   - Shows an idle message when there is no active work.

3. **Current Work And Queue**
   - Shows the active background task, active research jobs, and queued work.
   - Keeps counts compact and scan-friendly.

4. **Repair Window**
   - Appears prominently only when failed content or actionable alerts exist.
   - Default primary action is automatic retry from the appropriate stage.
   - Per-stage retry actions remain available behind an expanded “高级重试” control.
   - Each failed item shows title, source, failed stage, last error, and a link to the content detail.

5. **Supporting Details**
   - Publishing history, alerts, logs, model/GPU state, and Web restart move into compact disclosure panels or secondary buttons.
   - These details should not look like the main purpose of the page.

## Behavior

- `/run`, `/operations`, `/failures`, `/publish`, and existing tab URLs should still land on the same page.
- Existing retry APIs remain unchanged:
  - Auto/full retry: `/api/retry-full`
  - Stage retry: `/api/retry-download`, `/api/retry-transcribe`, `/api/retry-summary`
  - Batch retry: `/api/retry-batch`
- Existing data sources remain unchanged: `/api/bootstrap`, `/api/status`, `/api/research/jobs`.
- The “发布通知” navigation entry can continue linking to the page, but should no longer create a separate primary tab experience.

## Out Of Scope

- No backend workflow rewrite.
- No PostgreSQL schema changes.
- No new queue system.
- No large visual redesign of the whole Web UI.
- No changes to Obsidian note generation, GitHub Pages publishing, or Feishu payload logic.

## Testing

Implementation should include focused frontend tests or type-level checks where practical, then run:

```bash
cd kenradar/web/frontend
npm run lint
npm run build
```

Also run the existing backend smoke checks if the implementation touches shared types or API assumptions:

```bash
python -m compileall kenradar scripts
python -m pytest tests/test_config_and_publishing.py -q
```

## Self-Review

- No placeholders remain.
- Scope is limited to the Web “处理与发布” experience.
- The design preserves existing APIs and runtime behavior.
- The main UI goal is explicit: observe progress first, repair failures second, investigate details third.
