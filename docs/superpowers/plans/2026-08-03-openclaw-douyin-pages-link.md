# OpenClaw Douyin Pages Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenClaw’s `douyin-process` response retain its concise summary while adding a GitHub Pages link only after KenRadar has synchronized and confirmed that page is reachable.

**Architecture:** KenRadar remains the source of truth for note paths, public URL construction, Git synchronization, and remote readiness. The CLI exposes the persistent task result as JSON; the OpenClaw skill consumes that contract and never constructs a Pages URL itself.

**Tech Stack:** Python 3.12, pytest, requests, PostgreSQL task runs, GitHub Pages, Markdown OpenClaw skill.

## Global Constraints

- Only return a GitHub Pages link when `public_url_ready` is `true`.
- Default readiness polling is every 5 seconds for at most 90 seconds.
- Preserve local notes and HTML when Git synchronization or Pages readiness fails.
- Do not expose local absolute paths, credentials, Cookie values, API keys, or webhook URLs in the OpenClaw reply.
- Do not change the GitHub Pages repository, branch, Actions architecture, Feishu format, or scheduled monitoring flow.
- Do not run collection, transcription, or AI workloads in GitHub Actions.
- Preserve existing `detail_url` semantics as the local Web fallback.

---

### Task 1: KenRadar single-video publication result

**Files:**
- Modify: `kenradar/core/workflow.py:1008-1070,3410-3500`
- Test: `tests/test_config_and_publishing.py`

**Interfaces:**
- Consumes: `StaticSitePublisher.public_url_for(path)`, `Workflow._sync_github_publication(workflow_name, force=True)`, and `Workflow._public_url_ready(url)`.
- Produces: `Workflow._publish_single_video_result(summary_path: str, workflow_name: str = "research_video") -> dict[str, Any]` returning `public_url`, `public_url_ready`, `github_synced`, and `github_sync_message`.

- [ ] **Step 1: Write failing tests for successful publication and timeout**

Add tests with a lightweight `Workflow.__new__(Workflow)` fixture. Stub `publisher.public_url_for`, `_sync_github_publication`, and `_wait_public_urls` and assert the exact dictionaries:

```python
def test_publish_single_video_result_syncs_and_confirms_public_url():
    workflow = Workflow.__new__(Workflow)
    workflow.publisher = SimpleNamespace(public_url_for=lambda path: "https://example.github.io/notes/中文.html")
    workflow._sync_github_publication = lambda name, force=False: {
        "github_synced": True,
        "github_sync_message": "GitHub 同步完成",
    }
    workflow._wait_public_urls = lambda urls, timeout=None, interval=None: {urls[0]: True}

    assert workflow._publish_single_video_result("data/notes/douyin/a.md") == {
        "public_url": "https://example.github.io/notes/中文.html",
        "public_url_ready": True,
        "github_synced": True,
        "github_sync_message": "GitHub 同步完成",
    }
```

Add a second test where `_wait_public_urls` returns `False`; assert `public_url` is retained for diagnostics but `public_url_ready` is `False`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/test_config_and_publishing.py -q -k publish_single_video_result
```

Expected: FAIL because `_publish_single_video_result` does not exist.

- [ ] **Step 3: Implement publication synchronization and readiness**

Add `_publish_single_video_result`. Return empty/false fields when `summary_path` or the configured public URL is unavailable. Otherwise force one Git sync, call `_wait_public_urls` with the single URL and the single-video defaults, and merge the sync fields.

Extend `_wait_public_urls` without changing Feishu defaults:

```python
def _wait_public_urls(
    self,
    urls: list[str],
    *,
    timeout: float | None = None,
    interval: float | None = None,
) -> dict[str, bool]:
```

When arguments are supplied, use them; otherwise retain `wait_before_feishu_seconds` and `wait_before_feishu_poll_seconds`. For single-video publication read:

```text
publishing.github_pages.single_video_wait_seconds = 90
publishing.github_pages.single_video_poll_seconds = 5
```

- [ ] **Step 4: Add publication fields to both `research_video` branches**

For the already-archived branch and newly processed branch, call `_publish_single_video_result(summary_path)` and merge the returned fields into the result. Do not rerun download, transcription, or AI for an archived item.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
python -m pytest tests/test_config_and_publishing.py -q -k 'publish_single_video_result or research_video'
```

Expected: PASS.

Commit only Task 1 files:

```bash
git add kenradar/core/workflow.py tests/test_config_and_publishing.py
git commit -m "feat: confirm single-video Pages publication"
```

### Task 2: Machine-readable `research-video` CLI result

**Files:**
- Modify: `kenradar/__main__.py:80-100,295-312`
- Test: `tests/test_config_and_publishing.py`

**Interfaces:**
- Consumes: `task_run.stats_json` returned by `_submit_and_wait`.
- Produces: `research-video --json` writing one JSON object to stdout with the Task 1 result fields.

- [ ] **Step 1: Write failing parser and output tests**

Add a parser test asserting:

```python
args = build_parser().parse_args(["research-video", "https://www.douyin.com/video/123", "--json"])
assert args.json is True
```

Extract a small serializer and test it independently:

```python
assert _task_result_json({"stats_json": {"public_url_ready": True}}) == '{"public_url_ready": true}'
```

The serializer must use `ensure_ascii=False` and produce no Python `repr` syntax.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/test_config_and_publishing.py -q -k 'research_video_json or task_result_json'
```

Expected: FAIL because the flag and serializer are absent.

- [ ] **Step 3: Implement JSON output without breaking existing CLI behavior**

Add `--json` only to the `research-video` subparser. After `_submit_and_wait`, print serialized `stats_json` when requested; otherwise retain the current log message. Errors continue to exit non-zero through the existing exception path.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
python -m pytest tests/test_config_and_publishing.py -q -k 'research_video or task_result_json'
```

Expected: PASS.

Commit:

```bash
git add kenradar/__main__.py tests/test_config_and_publishing.py
git commit -m "feat: expose research-video result as JSON"
```

### Task 3: Update the OpenClaw `douyin-process` skill contract

**Files:**
- Modify: `/home/ken/.openclaw/workspace/skills/douyin-process/SKILL.md`
- Validate: `/data/ken/.codex/skills/.system/skill-creator/scripts/quick_validate.py`

**Interfaces:**
- Consumes: `research-video "{douyin_url}" --json` and fields `status`, `title`, `blogger_name`, `public_url`, `public_url_ready`, `github_synced`, `github_sync_message`, `detail_url`, and `summary_path`.
- Produces: OpenClaw reply instructions that include `public_url` only when ready and never expose `summary_path`.

- [ ] **Step 1: Create a failing contract check**

Run a temporary read-only validation command that checks the current skill for the required CLI flag and gating fields:

```bash
python - <<'PY'
from pathlib import Path
text = Path('/home/ken/.openclaw/workspace/skills/douyin-process/SKILL.md').read_text()
assert 'research-video "{douyin_url}" --json' in text
assert 'public_url_ready' in text
assert '不要向用户展示 `summary_path`' in text
PY
```

Expected: FAIL against the current skill.

- [ ] **Step 2: Rewrite the skill around the structured result**

Keep the trigger description and concise reply content. Update dependencies to the current production chain: FunASR with Whisper fallback; Agnes primary with Ollama fallback. Replace file scanning with `--json` result consumption. Require these branches:

```text
status success/skipped + public_url_ready true -> concise reply + 阅读全文 public_url
status success/skipped + public_url_ready false -> concise reply + deployment warning + detail_url
status failed/partial_failed -> truthful failed-stage response, no Pages link
```

Remove the instruction to expose the local note path. Explicitly prohibit guessing URLs or returning `public_url` when readiness is false.

- [ ] **Step 3: Validate the skill and contract**

Run:

```bash
python /data/ken/.codex/skills/.system/skill-creator/scripts/quick_validate.py /home/ken/.openclaw/workspace/skills/douyin-process
```

Then rerun the contract command from Step 1. Expected: both PASS.

- [ ] **Step 4: Record the external skill change**

The OpenClaw workspace is outside the KenRadar Git repository. Do not copy it into KenRadar. Record its absolute path and validation result in the final handoff.

### Task 4: End-to-end verification and documentation

**Files:**
- Modify: `README.md` in the `research-video` command section
- Test: `tests/test_config_and_publishing.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified CLI/skill behavior and operator documentation.

- [ ] **Step 1: Document the JSON and publication behavior**

Add a concise example:

```bash
python -m kenradar --config config/config.yaml research-video "抖音链接" --json
```

Document that `public_url_ready=true` is the only signal that a returned Pages URL is ready for user-facing replies.

- [ ] **Step 2: Run the full static and automated verification**

Run:

```bash
python -m compileall kenradar scripts
python -m pytest -q
cd kenradar/web/frontend
npm run lint
npm run build
```

Expected: all commands exit 0.

- [ ] **Step 3: Run a safe end-to-end reuse test**

Choose an already successful aweme ID from PostgreSQL and run it without `--force`:

```bash
/home/ken/miniconda3/envs/openclaw/bin/python -m kenradar \
  --config config/config.yaml \
  research-video --aweme-id "7653460652413303035" --json
```

Verify the JSON contains no local path in the proposed user reply, `public_url` uses the configured GitHub Pages base, and `public_url_ready=true`. Verify the URL with an HTTP HEAD/GET request.

- [ ] **Step 4: Restart and verify service health**

Run:

```bash
./ctl.sh restart
./ctl.sh status
curl -fsS http://127.0.0.1:8765/health/ready
```

Expected: Web and worker running; readiness response reports ready.

- [ ] **Step 5: Commit documentation and hand off**

Commit only repository files changed by this task:

```bash
git add README.md
git commit -m "docs: document OpenClaw Pages result contract"
```

Final handoff must report the tested public URL, CLI result fields, skill path, skill validation result, and any deployment latency observed.
