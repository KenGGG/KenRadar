# KenRadar Priority Hardening Verification

Date: 2026-08-15

## Outcome

The priority hardening scope is implemented without replacing the existing Douyin, Xiaoyuzhou, PostgreSQL, Obsidian, GitHub Pages, Feishu, or persistent-task production paths.

## Requirement Evidence

| Area | Implementation evidence | Runtime/test evidence |
|---|---|---|
| Web binding security | `ctl.sh` defaults to `127.0.0.1`; non-loopback startup requires a Web password | Runtime socket listens on `127.0.0.1:8765`; loopback/non-loopback/password tests pass |
| Schema gate/version | Web and task worker call `require_schema_current`; version data is dynamic | PostgreSQL current/head are both `0013_alert_aggregation`; readiness reports database/task/schema `ok` |
| Curation policy | `CurationPolicy` is consumed by analytics, Feishu, SQL filters, dashboard and archive UI | Policy/filter tests pass; failed/degraded summaries are excluded and an empty qualifying set is archived |
| Source fact source | `SourceRegistry` performs idempotent YAML import while preserving DB enable state; runtime targets read subscriptions | Config 21/21 enabled; DB 21/27 enabled; zero config-only sources, six DB-only disabled sources; monitor target count 21 |
| Task semantics | Handler results normalize to `success`, `partial_failed`, `failed`, `cancelled`; worker retries only explicit/all-item failure; public `step-worker` command removed | Task result/CLI tests pass; compatibility tables remain present and empty (`task_step`, `outbox_event`, `artifact`) |
| Bootstrap/API | Bootstrap is capped at 30 recent items; archive files and content load through separate endpoints | `/api/bootstrap`: 195,978 bytes, 0.71s; `/api/content-items`: 89,180 bytes, 0.66s; archive endpoint returns metadata only |
| Dependency health | Named probes cover PostgreSQL/schema, Agnes, FunASR, Ollama, GPU, Feishu and GitHub publishing | Required dependencies `ok`; Ollama/GPU `ok`; FunASR correctly `idle`; Agnes is truthfully `degraded` with `URLError` rather than being misidentified |
| Alert aggregation | Migration adds fingerprints, occurrence windows, notification timestamps and recovery state; historical rows are marked resolved history | Real DB verification: first notification true, duplicate false/count 2, expired window true, first recovery true, second recovery false |
| Dependencies | FastAPI, Uvicorn and python-multipart are declared; FunASR launcher discovers active Python instead of a machine path | Configured `openclaw` runtime imports all three; generic system Python lacks multipart but shipped dependency declarations now cover installation |

## Verification Commands

- `/home/ken/miniconda3/envs/openclaw/bin/python -m pytest -q` → `222 passed`
- `/home/ken/miniconda3/envs/openclaw/bin/python -m compileall -q kenradar scripts` → exit 0
- `git diff --check` → exit 0
- `npm run lint` → exit 0
- `npx tsx src/components/RunCenterModel.test.ts` → passed
- `npx tsx src/hooks/SSEPollingModel.test.ts` → passed
- `npm run build` → exit 0; application 455.06KB, vendor 421.73KB
- `python -m kenradar --config config/config.yaml doctor` → all required checks OK

## Production Validation

- Database backup: `data/backups/postgres/kenradar-pre-0013-20260815.dump` (custom format, about 102MB).
- Migration applied: `0011_backfill_douyin_sources` → `0012_hot_path_indexes` → `0013_alert_aggregation`.
- Web and worker restarted successfully with no active research/task run at restart time.
- `/health/ready`: HTTP 200, 0.09s.
- `/health/dependencies`: HTTP 200, about 1.1s; required dependencies healthy, optional Agnes reachability degraded.
- `/api/dashboard/overview?days=90`: HTTP 200, about 0.45s.
- Web/worker PIDs are active and the final startup log contains no new traceback/error entry.

## Compatibility and Data Safety

- Existing generated notes, briefs, Pages output and content data were not deleted.
- Only cache-only retired `company_research/**/__pycache__` directories were removed; they contained no source files.
- Historical alert rows remain queryable and are marked resolved rather than counted as current active fingerprints.
- Existing user worktree changes and generated artifacts remain uncommitted and were not reset or folded into an automatic commit.
