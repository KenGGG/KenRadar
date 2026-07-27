# FunASR On-Demand Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start local FunASR only before a real transcription request and stop it after 300 seconds without an active transcription.

**Architecture:** A focused `FunASRServiceManager` owns local endpoint health checks, cross-process startup locking, and the existing start script invocation. The OpenAI-compatible server owns thread-safe request activity tracking and asks Uvicorn to exit after the configured idle interval. `Transcriber` composes the manager before its existing HTTP request and preserves current fallback behavior.

**Tech Stack:** Python 3, FastAPI/Uvicorn, `requests`, POSIX `fcntl`, pytest, Bash, YAML.

## Global Constraints

- Do not start or manage Ollama.
- Preserve FunASR quality checks and Whisper fallback behavior.
- Do not interrupt an active transcription to release GPU memory.
- Default idle timeout is exactly 300 seconds.
- `managed: false` must never start a local process.
- Preserve existing manual `./ctl.sh start-funasr` and related commands.
- Do not modify or commit runtime-generated `docs/notes`, `docs/briefs`, or index output.

---

### Task 1: Local FunASR Service Manager

**Files:**
- Create: `kenradar/core/funasr_service.py`
- Modify: `kenradar/core/transcriber.py`
- Test: `tests/test_funasr_lifecycle.py`

**Interfaces:**
- Consumes: `AppConfig.get(path, default)` and `ai.funasr.endpoint`.
- Produces: `FunASRServiceManager(config).ensure_available() -> None`; raises on startup failure so the existing FunASR exception path triggers Whisper fallback.

- [ ] **Step 1: Write failing manager tests**

Add tests using a temporary lock path and a local fake HTTP server/process runner that prove: healthy endpoints do not start a process; unmanaged endpoints do not start a process; unhealthy managed endpoints invoke the start script once; two concurrent manager calls share the lock and start once; and startup timeout raises an error.

- [ ] **Step 2: Verify the tests fail for the missing manager**

Run: `python -m pytest tests/test_funasr_lifecycle.py -q`

Expected: collection fails because `kenradar.core.funasr_service` does not exist.

- [ ] **Step 3: Implement the manager and integrate it**

Implement endpoint normalization from `/v1` to `/health`, loopback-only local management, `fcntl.flock` around the double health check and subprocess startup, configurable script/lock/startup timeout, and diagnostic logging. Call `ensure_available()` in `_funasr_transcribe_sync` immediately before opening/uploading the media file.

- [ ] **Step 4: Verify manager tests pass**

Run: `python -m pytest tests/test_funasr_lifecycle.py -q`

Expected: all Task 1 tests pass.

### Task 2: Server Idle Shutdown

**Files:**
- Modify: `scripts/funasr_openai_server.py`
- Test: `tests/test_funasr_lifecycle.py`

**Interfaces:**
- Consumes: `FUNASR_IDLE_TIMEOUT_SECONDS`, default `300`; Uvicorn `Server.should_exit`.
- Produces: an activity tracker whose request context protects active transcriptions and whose monitor requests shutdown only after the idle threshold.

- [ ] **Step 1: Write failing activity tracker tests**

Add deterministic tests with an injected clock proving: active request count blocks exit beyond the deadline; completing the last request starts the idle interval; another request resets the interval; timeout `0` disables automatic exit; and the monitor callback runs exactly when idle reaches 300 seconds.

- [ ] **Step 2: Verify the tests fail for missing tracker behavior**

Run: `python -m pytest tests/test_funasr_lifecycle.py -q`

Expected: failures identify missing activity tracking and idle shutdown behavior.

- [ ] **Step 3: Implement request tracking and Uvicorn shutdown**

Add a thread-safe tracker, wrap only `/v1/audio/transcriptions` work in its activity context, create Uvicorn with `uvicorn.Config`/`uvicorn.Server`, and run a daemon monitor that sets `server.should_exit = True` after the configured idle interval. Preserve lazy/preload model behavior and ensure health/model-list calls do not refresh activity.

- [ ] **Step 4: Verify lifecycle tests pass**

Run: `python -m pytest tests/test_funasr_lifecycle.py -q`

Expected: all manager and tracker tests pass.

### Task 3: Startup, Configuration, and Documentation Integration

**Files:**
- Modify: `ctl.sh`
- Modify: `scripts/start_funasr_server.sh`
- Modify: `scripts/stop_funasr_server.sh`
- Modify: `config/config.yaml`
- Modify: `README.md`
- Test: `tests/test_funasr_lifecycle.py`

**Interfaces:**
- Consumes: `ai.funasr.managed`, `idle_timeout_seconds`, `startup_timeout_seconds`.
- Produces: normal `./ctl.sh start` without FunASR startup; manual FunASR commands remain available; stale PID files are harmless.

- [ ] **Step 1: Write failing command-level tests**

Run `ctl.sh start` with fake commands/PID paths in a temporary environment and assert no FunASR PID or start-script side effect occurs. Run the stop script against a stale PID file and assert it removes the file successfully.

- [ ] **Step 2: Verify command tests fail for current eager startup behavior**

Run: `python -m pytest tests/test_funasr_lifecycle.py -q`

Expected: the eager-start assertion fails.

- [ ] **Step 3: Apply integration changes**

Remove eager FunASR startup from `ctl.sh start`, revise help text, export the 300-second idle timeout from the start script, clean stale PID files, add the three YAML keys, and update README startup/status guidance to describe on-demand behavior.

- [ ] **Step 4: Run focused and regression verification**

Run:

```bash
python -m pytest tests/test_funasr_lifecycle.py -q
python -m pytest tests/test_config_and_publishing.py -q
python -m compileall kenradar scripts
bash -n ctl.sh scripts/start_funasr_server.sh scripts/stop_funasr_server.sh
```

Expected: all tests pass, compileall exits 0, and Bash syntax checks exit 0.

### Task 4: Runtime Acceptance

**Files:**
- No source changes expected.

**Interfaces:**
- Consumes: current KenRadar processes, configured CUDA FunASR, and `nvidia-smi`.
- Produces: evidence that idle startup does not occupy GPU and the real service releases GPU memory after the timeout.

- [ ] **Step 1: Restart KenRadar safely and inspect idle state**

Run `./ctl.sh restart`, `./ctl.sh status`, `./ctl.sh status-funasr`, and `nvidia-smi`. Confirm Web/worker are healthy while FunASR is stopped and its Python process is absent from GPU consumers.

- [ ] **Step 2: Trigger a bounded real transcription when no heavy batch is active**

Use an existing safe single-video/test path, observe FunASR start and complete, then wait at least 300 seconds from request completion without new transcription activity.

- [ ] **Step 3: Confirm idle release**

Run `./ctl.sh status-funasr` and `nvidia-smi`. Confirm the FunASR process exited and its GPU allocation is gone. If an existing batch is active, report runtime acceptance as deferred rather than interrupting it.
