# Sanitized Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a history-free, sanitized, Apache-2.0 KenRadar public repository that can start with Docker Compose and preserves optional separate-repository GitHub Pages publishing.

**Architecture:** A deterministic exporter in the private repository copies an explicit allowlist into `/data/Projects/KenRadar-public`, then the public copy receives open-source packaging, a clean non-experiment database baseline, container deployment, Pages onboarding, governance docs, and CI security gates. The exporter and public audit both fail closed on sensitive paths/content; no GitHub remote or push is performed without later user authorization.

**Tech Stack:** Python 3.10+, Docker/Compose, PostgreSQL, pytest, React/Vite, GitHub Actions, Apache-2.0.

## Global Constraints

- This plan starts only after `2026-08-03-retire-experimental-research.md` is complete and verified.
- Public output directory is `/data/Projects/KenRadar-public`; it must never reuse or copy the private `.git` directory.
- Do not modify the private GitHub remote, repository visibility, production configuration, runtime data, or production Pages repository.
- Do not create a public GitHub repository, add a remote, or push without a new explicit user confirmation.
- Public source contains no company research, financial analysis, NotebookLM runtime code, or experiment tables.
- Base Compose must run without GPU, FunASR, Whisper, Ollama, Feishu, or Douyin Cookie; those capabilities are optional and diagnostically reported.
- Main code license is Apache-2.0; vendored code is included only after compatible provenance is documented.
- GitHub Actions must not run scraping, media download, ASR, local models, AI calls, Pages content generation, or content publishing.

---

## File Structure

Private repository additions:

- `scripts/public_release_manifest.txt`: exact tracked path prefixes/files allowed into public export.
- `scripts/public_release_audit.py`: fail-closed path and text scanner shared by export verification.
- `scripts/export_public_release.py`: deterministic copier; refuses unsafe or non-empty destinations unless `--refresh` targets a recognized generated copy.
- `tests/test_public_release_export.py`: unit tests for manifest, audit, copying, history exclusion, and refresh safety.

Public-copy additions/changes:

- `LICENSE`, `THIRD_PARTY_NOTICES.md`, `NOTICE`: licensing boundary.
- `Dockerfile`, `compose.yaml`, `.dockerignore`, `docker/entrypoint.sh`: container deployment.
- `config/config.example.yaml`, `.env.example`, `scripts/init_public_config.py`: safe onboarding.
- `kenradar/storage/migrations/versions/0001_public_baseline.py`: single experiment-free public baseline.
- `.github/workflows/ci.yml`, `.github/dependabot.yml`: offline build/test/security gates only.
- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `docs/installation.md`, `docs/pages.md`, `docs/providers.md`, `docs/legal.md`: public documentation.
- `scripts/init_pages_repo.py`: bind a user-owned separate Pages repository without embedding credentials.

### Task 1: Build a fail-closed public export manifest and auditor

**Files:**
- Create: `scripts/public_release_manifest.txt`
- Create: `scripts/public_release_audit.py`
- Create: `tests/test_public_release_export.py`

**Interfaces:**
- Produces: `load_manifest(path: Path) -> tuple[str, ...]`, `audit_tree(root: Path) -> list[Finding]`, and `Finding(path: str, rule: str, excerpt: str)`.
- Consumes: only paths beneath an explicit root; scanner never follows symlinks.

- [ ] **Step 1: Write failing audit tests**

```python
from pathlib import Path

from scripts.public_release_audit import audit_tree, load_manifest


def test_audit_rejects_git_history_and_real_secrets(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").write_text("private remote", encoding="utf-8")
    (tmp_path / "settings.txt").write_text(
        "AGNES_API_KEY=sk-live-example-not-placeholder\n"
        "DATABASE_URL=postgresql://user:real-password@db/app\n",
        encoding="utf-8",
    )
    rules = {(item.path, item.rule) for item in audit_tree(tmp_path)}
    assert (".git", "forbidden_path") in rules
    assert any(rule == "secret_assignment" for _, rule in rules)
    assert any(rule == "credential_url" for _, rule in rules)


def test_audit_allows_documented_placeholders(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "AGNES_API_KEY=CHANGE_ME\n"
        "DATABASE_URL=postgresql://kenradar:CHANGE_ME@postgres:5432/kenradar\n",
        encoding="utf-8",
    )
    assert audit_tree(tmp_path) == []
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `python -m pytest tests/test_public_release_export.py -q`

Expected: FAIL because `scripts.public_release_audit` does not exist.

- [ ] **Step 3: Implement manifest loading and auditing**

Implement immutable `Finding`, sorted deterministic output, no symlink traversal, a 2 MiB text scan limit, and rules for `.git`, `.env` except `.env.example`, `config/config.yaml`, cookies, backups, `data/`, logs, media, transcript artifacts, database dumps, agent/browser state, egg-info, `dist/`, private remotes, API keys, Bearer values, webhook tokens, credential-bearing PostgreSQL URLs, `/home/<user>` paths, real email addresses, real `sec_uid`/video IDs, and the private GitHub owner/repository URL. Redact findings so `excerpt` contains the rule context but never the whole secret.

Manifest entries must cover only `.github`, `config/config.example.yaml`, `docker`, `docs` public docs, `kenradar`, `scripts` selected runtime/public scripts, `tests`, frontend source/package lock, and root packaging/governance files. It must explicitly exclude `design/`, generated `docs/notes`, `docs/briefs`, `docs/batch-notes`, `.git`, runtime configuration, and data.

- [ ] **Step 4: Run audit unit tests**

Run: `python -m pytest tests/test_public_release_export.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the auditor**

```bash
git add scripts/public_release_manifest.txt scripts/public_release_audit.py tests/test_public_release_export.py
git commit -m "feat: add public release audit"
```

### Task 2: Implement deterministic, safe public export

**Files:**
- Create: `scripts/export_public_release.py`
- Modify: `tests/test_public_release_export.py`

**Interfaces:**
- Consumes: `export_release(source: Path, destination: Path, manifest_path: Path, refresh: bool = False) -> ExportResult`.
- Produces: `ExportResult(copied: tuple[str, ...], removed: tuple[str, ...], findings: tuple[Finding, ...])`; destination marker `.kenradar-public-export.json` contains schema version and source commit only, no private remote.

- [ ] **Step 1: Write failing export safety tests**

```python
def test_export_copies_allowlist_without_git_or_runtime_data(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "public"
    (source / "kenradar").mkdir(parents=True)
    (source / "kenradar/__init__.py").write_text("", encoding="utf-8")
    (source / ".git").mkdir()
    (source / "data").mkdir()
    (source / "data/private.md").write_text("private", encoding="utf-8")
    manifest = source / "manifest.txt"
    manifest.write_text("kenradar/__init__.py\n", encoding="utf-8")

    result = export_release(source, destination, manifest)

    assert result.findings == ()
    assert (destination / "kenradar/__init__.py").exists()
    assert not (destination / ".git").exists()
    assert not (destination / "data").exists()


def test_refresh_refuses_unmarked_nonempty_destination(tmp_path: Path) -> None:
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / "user-file.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a recognized public export"):
        export_release(tmp_path / "source", destination, tmp_path / "manifest", refresh=True)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_public_release_export.py -q`

Expected: FAIL because exporter interfaces are absent.

- [ ] **Step 3: Implement exporter**

Resolve every manifest path beneath `source`, reject absolute paths, `..`, symlinks, missing entries, and files not returned by `git ls-files`. Copy with `shutil.copy2`; never shell out to `cp`, `rsync`, or archive the private `.git`. Audit the staging directory before atomically renaming it to the destination. Refresh only a destination with the valid marker, preserve its public `.git` directory if present, and remove stale files that were generated by a prior export but no longer appear in the manifest.

- [ ] **Step 4: Run tests and dry-run the real manifest**

Run: `python -m pytest tests/test_public_release_export.py -q`

Run: `python scripts/export_public_release.py --destination /tmp/kenradar-public-audit --dry-run`

Expected: tests pass; dry-run prints a sorted copy list and zero audit findings without creating the destination.

- [ ] **Step 5: Commit exporter**

```bash
git add scripts/export_public_release.py tests/test_public_release_export.py
git commit -m "feat: add deterministic public release export"
```

### Task 3: Resolve third-party provenance before copying vendored code

**Files:**
- Create in public copy: `THIRD_PARTY_NOTICES.md`
- Create in public copy: `NOTICE`
- Modify in public copy: vendored source headers only when needed to preserve accurate upstream notices.
- Modify in private repo: `scripts/public_release_manifest.txt`
- Test: `tests/test_public_release_export.py`

**Interfaces:**
- Consumes: upstream repository URLs and license texts verified from authoritative upstream sources.
- Produces: an allow/deny decision for every file under `kenradar/vendor/douyin_downloader/`.

- [ ] **Step 1: Inventory vendored files and provenance markers**

Run:

```bash
git ls-files kenradar/vendor/douyin_downloader
rg -n 'github.com|copyright|license|author' kenradar/vendor/douyin_downloader
```

Record each file, upstream project, upstream path/commit if identifiable, copyright holder, and license.

- [ ] **Step 2: Verify licenses using authoritative upstream repositories**

Use upstream repository license files and file history, not third-party summaries. Apache-2.0-, MIT-, BSD-, or similarly compatible files may be included with required notices. Any file whose provenance or permission cannot be confirmed is excluded from the public manifest.

- [ ] **Step 3: Add a manifest regression test**

```python
def test_every_exported_vendor_file_has_a_notice_entry() -> None:
    exported = {
        path for path in load_manifest(ROOT / "scripts/public_release_manifest.txt")
        if path.startswith("kenradar/vendor/") and path.endswith(".py")
    }
    notices = (ROOT / "tests/fixtures/public-release/THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )
    for path in exported:
        assert f"`{path}`" in notices
```

Store the draft notices fixture in the test fixture location used by the exporter until it is copied into the public root.

- [ ] **Step 4: Apply the allow/deny decision**

Add only verified files to the manifest and document each in `THIRD_PARTY_NOTICES.md`. If a required Douyin file is excluded, update public README/provider docs to mark Douyin unavailable until the user supplies the compatible external component; do not fabricate a replacement license.

- [ ] **Step 5: Run export audit tests and commit provenance metadata**

Run: `python -m pytest tests/test_public_release_export.py -q`

Expected: PASS with every exported vendor file covered.

```bash
git add scripts/public_release_manifest.txt tests/test_public_release_export.py tests/fixtures/public-release
git commit -m "docs: record vendored dependency provenance"
```

### Task 4: Generate the public copy and create a clean database baseline

**Files in public copy:**
- Delete: `kenradar/storage/migrations/versions/0002_add_task_step.py` through `0011_backfill_douyin_sources.py`
- Replace: `kenradar/storage/migrations/versions/0001_baseline.py`
- Modify: `kenradar/storage/pg_database.py`
- Create: `tests/test_public_database_baseline.py`

**Interfaces:**
- Consumes: final non-experiment `SCHEMA_SQL` and platform seed behavior.
- Produces: a single Alembic head `0001_public_baseline` with no experiment tables and a fresh PostgreSQL schema equivalent to the supported runtime model.

- [ ] **Step 1: Export to the final public directory**

Run: `python scripts/export_public_release.py --destination /data/Projects/KenRadar-public`

Expected: copy completes with zero findings and no `.git` directory.

- [ ] **Step 2: Write failing public schema tests**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_public_schema_has_no_retired_experiment_tables() -> None:
    schema = (ROOT / "kenradar/storage/pg_database.py").read_text(encoding="utf-8")
    for token in (
        "company_research_batches",
        "company_research_jobs",
        "company_notebooks",
        "company_research_answers",
        "company_financial_analysis_jobs",
        "company_financial_analysis_reports",
    ):
        assert token not in schema


def test_public_migrations_have_one_clean_head() -> None:
    versions = list((ROOT / "kenradar/storage/migrations/versions").glob("[0-9]*.py"))
    assert [path.name for path in versions] == ["0001_public_baseline.py"]
    text = versions[0].read_text(encoding="utf-8")
    assert 'revision = "0001_public_baseline"' in text
    assert "down_revision = None" in text
```

- [ ] **Step 3: Run tests and verify failure**

Run from public copy: `python -m pytest tests/test_public_database_baseline.py -q`

Expected: FAIL because private compatibility DDL/migrations were exported.

- [ ] **Step 4: Build the clean baseline**

Remove only the retired experiment table/index DDL from the public `SCHEMA_SQL`. Replace the migration versions with one `0001_public_baseline.py` whose `upgrade()` creates every supported table, view, index, constraint, and platform seed required by the current code, and whose `downgrade()` drops only those public objects in reverse dependency order. The migration must not import application configuration or connect to external services.

- [ ] **Step 5: Test against an empty disposable PostgreSQL database**

Start a temporary PostgreSQL container on a non-production port, set a test-only `DATABASE_URL`, run `python -m alembic upgrade head`, then query `information_schema.tables` to assert core tables exist and retired tables do not. Stop the temporary container without touching the private database.

Expected core tables include `platform`, `creator`, `content_item`, `transcript`, `ai_analysis`, `content_note`, `research_job`, `task_run`, `source_subscription`, and `source_daily_metrics`.

- [ ] **Step 6: Commit in the public repository after Git initialization in Task 9**

Keep changes uncommitted until the complete public tree passes the audit; Task 9 creates the first public commit.

### Task 5: Add safe configuration initialization and generic provider defaults

**Files in public copy:**
- Create: `config/config.example.yaml`
- Modify: `.env.example`
- Create: `scripts/init_public_config.py`
- Modify: `kenradar/core/config.py`
- Modify: `README.md`
- Create: `tests/test_public_config.py`

**Interfaces:**
- Produces: `initialize_config(root: Path, force: bool = False) -> tuple[Path, Path]`; writes `.env` and `config/config.yaml` with mode `0600` and refuses overwrite unless `force=True`.
- Consumes: environment placeholders supported by `AppConfig`.

- [ ] **Step 1: Write failing initialization tests**

```python
def test_initializer_creates_private_files_without_real_secrets(tmp_path: Path) -> None:
    env_path, config_path = initialize_config(tmp_path)
    assert env_path.stat().st_mode & 0o777 == 0o600
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert "CHANGE_ME" in env_path.read_text(encoding="utf-8")
    assert "${DATABASE_URL}" in config_path.read_text(encoding="utf-8")


def test_initializer_refuses_to_overwrite(tmp_path: Path) -> None:
    initialize_config(tmp_path)
    with pytest.raises(FileExistsError):
        initialize_config(tmp_path)
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `python -m pytest tests/test_public_config.py -q`

Expected: FAIL because initializer does not exist.

- [ ] **Step 3: Implement safe templates and initialization**

Use generic OpenAI-compatible organizer provider fields (`endpoint`, `model`, `api_key_env`, `requires_api_key`) with an invalid example endpoint or disabled state. Keep Agnes and Ollama in provider documentation examples, not hard requirements. Default notification and publishing sync to disabled. Default Web binding in Compose is loopback and generated `KENRADAR_WEB_PASSWORD` uses `secrets.token_urlsafe(32)`.

- [ ] **Step 4: Run config and existing publishing tests**

Run: `python -m pytest tests/test_public_config.py tests/test_config_and_publishing.py -q`

Expected: PASS.

### Task 6: Add Docker Compose deployment

**Files in public copy:**
- Create: `Dockerfile`
- Create: `compose.yaml`
- Create: `.dockerignore`
- Create: `docker/entrypoint.sh`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`
- Create: `tests/test_container_contract.py`

**Interfaces:**
- Produces: `app` and `postgres` Compose services; app entrypoint waits for PostgreSQL, runs `alembic upgrade head`, and execs the Web/worker supervisor command without embedding secrets.
- Consumes: `.env`, `config/config.yaml`, and persistent mounts `./data:/app/data`, `./config:/app/config`.

- [ ] **Step 1: Write failing Compose contract tests**

```python
import yaml


def test_compose_has_safe_app_and_postgres_services() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"app", "postgres"}
    assert compose["services"]["app"]["ports"] == ["127.0.0.1:8765:8765"]
    assert compose["services"]["app"].get("privileged") is not True
    assert compose["services"]["postgres"]["healthcheck"]


def test_dockerfile_runs_as_non_root() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER kenradar" in text
```

- [ ] **Step 2: Run tests and verify missing files fail**

Run: `python -m pytest tests/test_container_contract.py -q`

Expected: FAIL because Compose and Dockerfile do not exist.

- [ ] **Step 3: Implement minimal container deployment**

Use a multi-stage image: Node stage builds `kenradar/web/frontend/dist`; Python stage installs the package, copies the built frontend, creates UID/GID 10001 `kenradar`, and runs as that user. Compose uses PostgreSQL 16, a named database volume, health checks, `restart: unless-stopped`, and no host database port by default. Do not include Docker socket, host network, privileged mode, GPU devices, or secrets in image layers.

- [ ] **Step 4: Build and run smoke tests**

Run:

```bash
docker compose config
docker compose build
docker compose up -d
docker compose exec -T app python -m kenradar --config config/config.yaml doctor
curl -fsS http://127.0.0.1:8765/health/live
curl -fsS http://127.0.0.1:8765/health/ready
docker compose down
```

Expected: config/build/start succeed; doctor does not reveal values; live and ready succeed; persistent database volume remains.

### Task 7: Add separate Pages repository onboarding

**Files in public copy:**
- Create: `scripts/init_pages_repo.py`
- Create: `docs/pages.md`
- Modify: `README.md`
- Modify: `tests/test_config_and_publishing.py`
- Create: `tests/test_pages_init.py`

**Interfaces:**
- Produces: `initialize_pages_repo(repo_url: str, target: Path, public_url: str, push: bool = False) -> PagesInitResult`.
- Consumes: an HTTPS or SSH Git URL without embedded credentials and an empty/nonexistent target.

- [ ] **Step 1: Write failing URL and safety tests**

```python
def test_pages_initializer_rejects_embedded_credentials(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="credentials"):
        initialize_pages_repo(
            "https://token@example.com/user/pages.git",
            tmp_path / "pages",
            "https://user.github.io/pages/",
        )


def test_pages_initializer_defaults_to_no_push() -> None:
    signature = inspect.signature(initialize_pages_repo)
    assert signature.parameters["push"].default is False
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `python -m pytest tests/test_pages_init.py -q`

Expected: FAIL because initializer does not exist.

- [ ] **Step 3: Implement Pages onboarding**

Validate URLs, clone into `data/github-pages`, create an orphan `gh-pages` branch only for an empty remote, write a non-sensitive `.gitignore`, and print the exact configuration keys the user must enable. Never write Git credentials into configuration. Do not push unless `--push` is explicitly passed; even with `--push`, rely on the user's existing Git credential helper/SSH configuration.

- [ ] **Step 4: Test with local bare repositories**

Use temporary local bare Git repositories in tests to cover clone, empty initialization, existing branch, dirty target refusal, and no-push default. Then run existing `GithubSyncManager` dry-run tests.

Run: `python -m pytest tests/test_pages_init.py tests/test_config_and_publishing.py -q`

Expected: PASS with no network access.

### Task 8: Add open-source governance, user docs, and offline CI

**Files in public copy:**
- Create: `LICENSE`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `CHANGELOG.md`
- Create: `docs/installation.md`
- Create: `docs/providers.md`
- Create: `docs/legal.md`
- Rewrite: `README.md`
- Create: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`
- Modify: `pyproject.toml`
- Create: `tests/test_public_repository_contract.py`

**Interfaces:**
- Produces: complete public onboarding and CI that performs only offline/static validation.
- Consumes: Docker/config/Pages commands defined in Tasks 5–7.

- [ ] **Step 1: Write failing governance contract tests**

```python
def test_required_public_documents_exist() -> None:
    for relative in (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "CHANGELOG.md",
        "docs/installation.md",
        "docs/pages.md",
        "docs/providers.md",
        "docs/legal.md",
    ):
        assert (ROOT / relative).is_file(), relative


def test_ci_does_not_run_production_workloads() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for token in ("run-once", "research-blogger", "publish-pages", "sync-github", "ollama", "funasr"):
        assert token not in workflow.lower()
```

- [ ] **Step 2: Run contract tests and verify failure**

Run: `python -m pytest tests/test_public_repository_contract.py -q`

Expected: FAIL on missing governance and workflow files.

- [ ] **Step 3: Write governance and user documentation**

Use the standard Apache License 2.0 text. `SECURITY.md` directs private vulnerability reports to a repository security advisory, not a personal email. README clearly separates stable Douyin support from Xiaoyuzhou/RSS MVP, documents optional external services, uses only example identities/URLs, and links to installation, providers, Pages, legal, contribution, and security docs. Legal docs cover platform terms, Cookie handling, content copyright, and user responsibility without claiming legal advice.

- [ ] **Step 4: Add CI and package metadata**

CI jobs: Python compile/pytest, frontend `npm ci` + lint/build, public audit, Docker build, and a Compose configuration check. Use no repository secrets, network credentials, production database, external API, GPU, or content publishing. Update `pyproject.toml` with Apache-2.0 license expression, README and classifiers; omit project URLs until the new GitHub repository exists, and exclude runtime/generated directories from packages.

- [ ] **Step 5: Run docs/contracts and local CI equivalents**

Run:

```bash
python scripts/public_release_audit.py .
python -m compileall kenradar scripts
python -m pytest -q
cd kenradar/web/frontend && npm ci && npm run lint && npm run build
docker build -t kenradar-public:local .
```

Expected: all pass with zero audit findings.

### Task 9: Final audit, clean Git initialization, and release report

**Files in public copy:**
- Create: `docs/release-readiness.md`
- Create: `.gitignore`

**Interfaces:**
- Consumes: completed public tree.
- Produces: one local Git repository with a clean initial commit and no remote.

- [ ] **Step 1: Run the complete public verification suite**

Run:

```bash
python scripts/public_release_audit.py .
python -m compileall kenradar scripts
python -m pytest -q
cd kenradar/web/frontend && npm ci && npm run lint && npm run build
cd /data/Projects/KenRadar-public && docker compose config && docker compose build
```

Expected: every command exits 0; audit reports zero findings.

- [ ] **Step 2: Run a clean-room Compose smoke test**

Copy only documented sample configuration into a new temporary directory or reset generated local config, then run init, Compose up, database migration, doctor, live/ready, and Compose down. Confirm logs contain no secret values and optional services are reported as disabled/unconfigured rather than fatal.

- [ ] **Step 3: Verify Pages without network or push**

Initialize against a temporary local bare repository, generate a minimal static site from test fixtures, run GitHub sync dry-run, and confirm no push occurred. Do not use the private production Pages directory or remote.

- [ ] **Step 4: Write release readiness report**

Record preserved features, retired features, Docker results, test counts, public audit rules/results, third-party license decisions, Pages dry-run, optional capabilities not tested, and exact user configuration still required. Redact all local usernames and absolute paths in the report.

- [ ] **Step 5: Initialize a history-free local repository**

Run only after confirming `/data/Projects/KenRadar-public/.git` does not exist:

```bash
cd /data/Projects/KenRadar-public
git init -b main
git add .
git status --short
git diff --cached --check
git commit -m "feat: initial public release"
```

Expected: one root commit containing only audited public files.

- [ ] **Step 6: Prove private history and remotes are absent**

Run:

```bash
git rev-list --count HEAD
git remote -v
git fsck --no-reflogs --unreachable
```

Expected: commit count is `1`, `git remote -v` prints nothing, and no private objects are reported.

- [ ] **Step 7: Stop before external publication**

Report the local public repository path and commit hash. Ask for explicit authorization to create/add a GitHub remote and push. Do not invoke `gh repo create`, `git remote add`, or `git push` in this plan.
