# Retire Experimental Research Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove company research, financial analysis, and NotebookLM product/runtime functionality from the private KenRadar repository without deleting historical PostgreSQL tables or disrupting the production media radar and Pages pipeline.

**Architecture:** Remove the experiment dependency closure from the outside in: contract tests first, then HTTP/worker entry points, persistence facade, frontend, and finally implementation files and documentation. Historical Alembic revisions 0003–0005 and their table DDL remain as inert compatibility artifacts so existing and fresh private databases keep a valid migration chain.

**Tech Stack:** Python 3.10+, pytest, PostgreSQL/psycopg, Alembic, React 19, TypeScript 5.8, Vite 6.

## Global Constraints

- Do not delete, truncate, export, or modify existing company research PostgreSQL data.
- Keep migrations `0003_company_research.py`, `0004_company_notice_attempts.py`, and `0005_fin_analysis_mvp.py` in the private repository.
- Preserve migration chain `0002 -> 0003 -> 0004 -> 0005 -> 0006`.
- Preserve Douyin, Xiaoyuzhou/RSS, transcription, organizer fallback, PostgreSQL, Web, Feishu, scheduling, and separate GitHub Pages publishing.
- Do not include existing `kenradar.egg-info/SOURCES.txt`, `.playwright-mcp/`, `.superpowers/`, runtime content, or unrelated user changes in commits.
- Use test-driven changes and one focused commit per task.

---

## File Structure

- `tests/test_experimental_features_retired.py`: repository-level retirement contract; asserts forbidden runtime paths, imports, API prefixes, task types, and frontend symbols are absent while compatibility migrations remain.
- `kenradar/web/app.py`: remove company HTTP GET/POST routes and helper functions.
- `kenradar/jobs/handlers.py`: remove experiment task dispatch.
- `kenradar/web/queries.py`: remove experiment task display labels.
- `kenradar/storage/pg_database.py`: remove experiment repository construction and public runtime methods; keep compatibility DDL unchanged.
- `kenradar/web/frontend/src/`: remove experiment workspace/components/types and legacy route mapping.
- `kenradar/company_research/`, `kenradar/web/company_research_api.py`, `kenradar/storage/repositories/company_research.py`: delete retired implementation.
- `tests/test_config_and_publishing.py`: remove experiment-only imports/tests; update SPA fallback expectation.
- `README.md`, `AGENTS.md`, `design/`: remove claims and internal experiment artifacts that no longer describe the product.

### Task 1: Add the retirement contract

**Files:**
- Create: `tests/test_experimental_features_retired.py`

**Interfaces:**
- Consumes: repository root and tracked source tree.
- Produces: a regression contract that every later task must satisfy.

- [ ] **Step 1: Write the failing repository contract**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOTS = (ROOT / "kenradar", ROOT / "scripts")
FORBIDDEN_TEXT = (
    "company_research",
    "company-research",
    "CompanyResearch",
    "CompanyFinancialAnalysis",
    "NotebookLM",
    "notebooklm",
    "company_financial_analysis",
)


def test_experimental_runtime_modules_are_removed() -> None:
    assert not (ROOT / "kenradar/company_research").exists()
    assert not (ROOT / "kenradar/web/company_research_api.py").exists()
    assert not (ROOT / "kenradar/storage/repositories/company_research.py").exists()


def test_runtime_and_frontend_have_no_experimental_symbols() -> None:
    offenders: list[str] = []
    for base in RUNTIME_ROOTS:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            relative = path.relative_to(ROOT).as_posix()
            if relative == "kenradar/storage/pg_database.py":
                continue
            if relative.startswith("kenradar/storage/migrations/versions/0003_"):
                continue
            if relative.startswith("kenradar/storage/migrations/versions/0004_"):
                continue
            if relative.startswith("kenradar/storage/migrations/versions/0005_"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(token in text for token in FORBIDDEN_TEXT):
                offenders.append(relative)
    assert offenders == []


def test_retired_migrations_remain_for_private_database_compatibility() -> None:
    versions = ROOT / "kenradar/storage/migrations/versions"
    assert (versions / "0003_company_research.py").exists()
    assert (versions / "0004_company_notice_attempts.py").exists()
    assert (versions / "0005_fin_analysis_mvp.py").exists()
    assert 'down_revision = "0005_fin_analysis_mvp"' in (
        versions / "0006_add_xiaoyuzhou_platform.py"
    ).read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the contract and verify it fails**

Run: `python -m pytest tests/test_experimental_features_retired.py -q`

Expected: failures list the existing experiment modules and runtime/frontend references; the migration compatibility assertion passes.

- [ ] **Step 3: Commit the failing contract**

```bash
git add tests/test_experimental_features_retired.py
git commit -m "test: define retired experiment boundary"
```

### Task 2: Remove backend HTTP and worker entry points

**Files:**
- Modify: `kenradar/web/app.py`
- Modify: `kenradar/jobs/handlers.py`
- Modify: `kenradar/web/queries.py`
- Modify: `tests/test_config_and_publishing.py`
- Test: `tests/test_experimental_features_retired.py`
- Test: `tests/test_api_contract.py`

**Interfaces:**
- Consumes: existing `RequestHandler` routing and `execute_task_run(workflow, task)` dispatch.
- Produces: `/api/company-research/*` falls through to normal 404 handling; experiment task types are no longer dispatchable.

- [ ] **Step 1: Add API and dispatch assertions**

Add to `tests/test_experimental_features_retired.py`:

```python
def test_company_api_prefix_is_not_registered() -> None:
    app_text = (ROOT / "kenradar/web/app.py").read_text(encoding="utf-8")
    assert '"/api/company-research' not in app_text
    assert '"/company-research"' not in app_text


def test_company_task_types_are_not_dispatched() -> None:
    handlers = (ROOT / "kenradar/jobs/handlers.py").read_text(encoding="utf-8")
    for task_type in (
        "company_research_batch",
        "company_research_cleanup_notebooks",
        "company_research_cleanup_local_pdfs",
        "company_financial_analysis",
    ):
        assert task_type not in handlers
```

- [ ] **Step 2: Run targeted tests and verify the new assertions fail**

Run: `python -m pytest tests/test_experimental_features_retired.py tests/test_api_contract.py -q`

Expected: retirement assertions fail before route removal; existing API contract tests remain otherwise green.

- [ ] **Step 3: Remove the backend entry points**

In `kenradar/web/app.py`, remove:

- imports from `kenradar.company_research` and `kenradar.web.company_research_api`;
- SPA special case for `/company-research`;
- all GET and POST branches whose path begins `/api/company-research`;
- `_resolve_company_symbol`, `_company_answers_with_placeholders`, `_company_stock_summary`, and helpers used only by those branches.

In `kenradar/jobs/handlers.py`, remove the four experiment dispatch branches. In `kenradar/web/queries.py`, remove their four display labels. In `tests/test_config_and_publishing.py`, change the SPA fallback test to assert `/company-research` uses the generic SPA behavior only if generic client routes are supported; otherwise assert it returns 404, matching the actual router contract.

- [ ] **Step 4: Run backend contracts**

Run: `python -m pytest tests/test_experimental_features_retired.py tests/test_api_contract.py tests/test_config_and_publishing.py -q`

Expected: API and task assertions pass; failures may remain only for modules/persistence/frontend not removed in later tasks.

- [ ] **Step 5: Commit backend entry-point removal**

```bash
git add kenradar/web/app.py kenradar/jobs/handlers.py kenradar/web/queries.py tests/test_config_and_publishing.py tests/test_experimental_features_retired.py
git commit -m "refactor: retire experimental research entry points"
```

### Task 3: Detach runtime persistence while preserving schema compatibility

**Files:**
- Modify: `kenradar/storage/pg_database.py`
- Modify: `kenradar/storage/repositories/__init__.py`
- Delete: `kenradar/storage/repositories/company_research.py`
- Test: `tests/test_experimental_features_retired.py`
- Test: `tests/test_config_and_publishing.py`

**Interfaces:**
- Consumes: `PostgresDatabase` initialization and core repository APIs.
- Produces: `PostgresDatabase` without `company_research` runtime repository or company/financial methods; compatibility schema strings and Alembic revisions remain intact.

- [ ] **Step 1: Add persistence boundary assertions**

```python
def test_postgres_runtime_facade_has_no_experiment_repository() -> None:
    text = (ROOT / "kenradar/storage/pg_database.py").read_text(encoding="utf-8")
    assert "CompanyResearchRepository" not in text
    assert "self.company_research" not in text
    assert "def create_company_research" not in text
    assert "def create_financial_analysis" not in text
    assert "CREATE TABLE IF NOT EXISTS company_research_batches" in text
```

- [ ] **Step 2: Run the assertion and verify it fails**

Run: `python -m pytest tests/test_experimental_features_retired.py::test_postgres_runtime_facade_has_no_experiment_repository -q`

Expected: FAIL on repository import/construction or runtime methods.

- [ ] **Step 3: Remove only runtime persistence APIs**

Remove the repository import, `self.company_research` initialization, all company research proxy methods, and all financial analysis CRUD/query methods from `PostgresDatabase`. Delete the repository file and any export from `repositories/__init__.py`. Do not edit the experiment `CREATE TABLE`/index clauses in private `SCHEMA_SQL`, and do not edit migrations 0003–0005.

- [ ] **Step 4: Run storage and migration tests**

Run: `python -m pytest tests/test_experimental_features_retired.py tests/test_config_and_publishing.py tests/test_api_contract.py -q`

Expected: persistence boundary passes; core database/config/API tests pass.

- [ ] **Step 5: Commit persistence detachment**

```bash
git add kenradar/storage/pg_database.py kenradar/storage/repositories tests/test_experimental_features_retired.py
git commit -m "refactor: detach retired research persistence"
```

### Task 4: Remove the frontend experiment workspace

**Files:**
- Delete: `kenradar/web/frontend/src/components/CompanyResearchWorkspace.tsx`
- Delete: `kenradar/web/frontend/src/components/CompanyFinancialAnalysisMVP.tsx`
- Delete: `kenradar/web/frontend/src/components/company-research/`
- Modify: `kenradar/web/frontend/src/types.ts`
- Modify: `kenradar/web/frontend/src/hooks/useAppState.ts`
- Test: `tests/test_experimental_features_retired.py`

**Interfaces:**
- Consumes: current SPA navigation and view selection.
- Produces: no `/company-research` view, fetch call, type, or navigation item.

- [ ] **Step 1: Extend the repository contract for frontend files**

```python
def test_experimental_frontend_files_are_removed() -> None:
    frontend = ROOT / "kenradar/web/frontend/src"
    assert not (frontend / "components/CompanyResearchWorkspace.tsx").exists()
    assert not (frontend / "components/CompanyFinancialAnalysisMVP.tsx").exists()
    assert not (frontend / "components/company-research").exists()
```

- [ ] **Step 2: Run the assertion and verify it fails**

Run: `python -m pytest tests/test_experimental_features_retired.py::test_experimental_frontend_files_are_removed -q`

Expected: FAIL because the components exist.

- [ ] **Step 3: Delete components and remove references**

Delete the files/directories above. Remove `CompanyResearchJob`, `CompanyResearchAnswer`, notice/NotebookLM/financial types used only by the workspace from `types.ts`. Remove the `/company-research` mapping from `useAppState.ts`, plus any remaining imports, view branches, or navigation entries found by:

```bash
rg -n 'CompanyResearch|CompanyFinancial|company-research|company_research|NotebookLM|财务分析|公司研究' kenradar/web/frontend/src
```

The command must return no matches after removal.

- [ ] **Step 4: Run frontend checks and retirement tests**

Run: `cd kenradar/web/frontend && npm run lint && npm run build`

Run: `python -m pytest tests/test_experimental_features_retired.py -q`

Expected: TypeScript and Vite build pass; only implementation/document cleanup assertions may remain.

- [ ] **Step 5: Commit frontend removal**

```bash
git add kenradar/web/frontend/src tests/test_experimental_features_retired.py
git commit -m "refactor: remove experimental research UI"
```

### Task 5: Delete experiment implementation and dedicated tests

**Files:**
- Delete: `kenradar/company_research/`
- Delete: `kenradar/web/company_research_api.py`
- Modify: `tests/test_config_and_publishing.py`
- Modify: `tests/test_experimental_features_retired.py`

**Interfaces:**
- Consumes: runtime entry points and persistence already detached by Tasks 2–4.
- Produces: source tree with no importable experiment implementation.

- [ ] **Step 1: Identify exact experiment-only tests before deletion**

Run:

```bash
rg -n '^def test_(company_research|notice_downloader|validate_pdf)|CompanyResearchService|NoticeDownloader|akshare_provider|pdf_validator' tests/test_config_and_publishing.py
```

Expected: the company cleanup, PDF validation, and notice downloader tests plus their imports are listed.

- [ ] **Step 2: Delete implementation and experiment-only tests**

Delete `kenradar/company_research/` and `kenradar/web/company_research_api.py`. Remove only tests/imports whose subject was deleted; retain scheduler, workflow, config, publishing, organizer, transcription, Feishu, and cleanup tests in the same file.

- [ ] **Step 3: Run compile and focused tests**

Run: `python -m compileall -q kenradar scripts`

Run: `python -m pytest tests/test_experimental_features_retired.py tests/test_config_and_publishing.py tests/test_api_contract.py -q`

Expected: all pass.

- [ ] **Step 4: Commit implementation deletion**

```bash
git add -A kenradar/company_research kenradar/web/company_research_api.py tests/test_config_and_publishing.py
git commit -m "refactor: delete retired research implementation"
```

### Task 6: Remove stale product documentation and personal experiment artifacts

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Delete: `design/financial_analysis_mvp_plan.md`
- Delete: `design/implementation_plan_stock_1.md`
- Delete: `design/run_all_stock_notice_stats.py`
- Delete: `design/stock.md`
- Delete or edit after inspection: `design/frontend_restructure_plan.md`
- Delete or edit after inspection: `design/frontend_restructure_phase2_plan.md`
- Test: `tests/test_experimental_features_retired.py`

**Interfaces:**
- Consumes: approved product scope.
- Produces: repository documentation that describes only supported runtime features; historical migration names are the sole permitted experiment references.

- [ ] **Step 1: Add documentation boundary assertion**

```python
def test_product_docs_do_not_advertise_retired_experiments() -> None:
    for relative in ("README.md", "AGENTS.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "NotebookLM" not in text
        assert "公司研究" not in text
        assert "财务分析" not in text
```

- [ ] **Step 2: Run the assertion and verify it fails**

Run: `python -m pytest tests/test_experimental_features_retired.py::test_product_docs_do_not_advertise_retired_experiments -q`

Expected: FAIL where current docs mention experiments.

- [ ] **Step 3: Rewrite docs and remove experiment artifacts**

Remove retired feature descriptions, commands, architecture entries, dependencies, routes, and status claims. Delete dedicated stock/company research design files. For the two frontend restructure plans, retain them only if all experiment-specific sections can be removed without making the document misleading; otherwise delete them as internal obsolete artifacts.

- [ ] **Step 4: Verify reference boundaries**

Run:

```bash
rg -n 'company_research|company-research|CompanyResearch|CompanyFinancial|NotebookLM|notebooklm|公司研究|财务分析' \
  README.md AGENTS.md design kenradar tests \
  --glob '!kenradar/storage/migrations/versions/0003_company_research.py' \
  --glob '!kenradar/storage/migrations/versions/0004_company_notice_attempts.py' \
  --glob '!kenradar/storage/migrations/versions/0005_fin_analysis_mvp.py' \
  --glob '!tests/test_experimental_features_retired.py'
```

Expected: no output. The compatibility migrations and retirement contract are the only allowed references.

- [ ] **Step 5: Commit documentation cleanup**

```bash
git add README.md AGENTS.md design tests/test_experimental_features_retired.py
git commit -m "docs: remove retired experiment documentation"
```

### Task 7: Verify the private production application

**Files:**
- Modify only if verification exposes a regression: files directly responsible for that regression.
- Record: `docs/superpowers/reports/2026-08-03-experiment-retirement-verification.md`

**Interfaces:**
- Consumes: experiment-free private application.
- Produces: evidence that core production behavior and separate Pages publishing still work.

- [ ] **Step 1: Run static, backend, and frontend verification**

Run:

```bash
python -m compileall kenradar scripts
python -m pytest -q
cd kenradar/web/frontend && npm run lint && npm run build
```

Expected: all commands exit 0.

- [ ] **Step 2: Verify migration compatibility without destructive SQL**

Run: `python -m alembic -c alembic.ini current`

Run: `python -m alembic -c alembic.ini heads`

Expected: current revision is valid and the single head is `0011_backfill_douyin_sources`. Do not run downgrade or any SQL that drops experiment tables.

- [ ] **Step 3: Restart and check the private runtime**

Run:

```bash
./ctl.sh restart
./ctl.sh status
curl -fsS http://127.0.0.1:8765/health/live
curl -fsS http://127.0.0.1:8765/health/ready
curl -fsS http://127.0.0.1:8765/health/dependencies
curl -fsS http://127.0.0.1:8765/api/dashboard/overview
curl -fsS 'http://127.0.0.1:8765/api/content-items?limit=1'
```

Expected: service and worker run; live/ready succeed; dashboard and content APIs return JSON. If password auth is enabled, use the existing authenticated test helper rather than printing credentials in shell history or logs.

- [ ] **Step 4: Verify Pages locally and dry-run synchronization**

Run: `python -m kenradar --config config/config.yaml publish-pages`

Run: `python -m kenradar --config config/config.yaml sync-github --dry-run`

Expected: static generation succeeds and dry-run reports allowed candidates without pushing. If the CLI uses a different existing sync flag, confirm it with `python -m kenradar --help` and use that documented command; do not enable push.

- [ ] **Step 5: Write the verification report**

Create the report with exact commands, exit status, test counts, health results with secrets redacted, migration head, Pages dry-run summary, and any unverified external dependency. Do not paste cookies, URLs containing tokens, database URLs, or content transcripts.

- [ ] **Step 6: Commit the report and any focused regression fix separately**

```bash
git add docs/superpowers/reports/2026-08-03-experiment-retirement-verification.md
git commit -m "docs: record experiment retirement verification"
```
