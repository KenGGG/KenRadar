# Agnes 2.5 Flash Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the active Agnes 2.0 Flash integration with Agnes 2.5 Flash and prove that KenRadar can call it successfully.

**Architecture:** Keep the existing OpenAI-compatible Chat Completions provider, endpoint, rate limit, request shape, and Ollama fallback. Change only the Agnes model identifier in runtime configuration and active defaults, with regression coverage for configuration and Web fallbacks.

**Tech Stack:** Python, pytest, YAML, React/TypeScript, Vite, Agnes OpenAI-compatible API

**Spec:** User-approved design in the 2026-08-16 conversation, based on the official Agnes 2.5 Flash documentation.

## Global Constraints

- The primary model is exactly `agnes-2.5-flash`.
- Base URL remains exactly `https://apihub.agnes-ai.com/v1`.
- The integration remains `chat_completions` and uses `AGNES_API_KEY`.
- Agnes rate limiting remains `rpm_limit: 19`.
- The `qwen3.5:9b` Ollama fallback remains enabled and unchanged.
- Historical notes and generated content are not rewritten.
- API credentials must never be printed.

---

### Task 1: Lock the upgraded defaults with regression tests

**Files:**
- Modify: `tests/test_config_and_publishing.py`
- Test: `tests/test_config_and_publishing.py`

**Interfaces:**
- Consumes: `load_config()`, `kenradar.web.helpers._frontend_config()`
- Produces: Regression assertions for active YAML and empty-config Web defaults.

- [x] Add a test that loads `config/config.yaml` and asserts both organizer and Agnes provider models equal `agnes-2.5-flash`, while endpoint, rate limit, and Ollama fallback remain unchanged.
- [x] Add a test that constructs an empty organizer config and asserts the Web-facing fallback model is `agnes-2.5-flash`.
- [x] Run the focused tests and confirm they fail specifically because the repository still returns `agnes-2.0-flash`.

### Task 2: Update active configuration and defaults

**Files:**
- Modify: `config/config.yaml`
- Modify: `kenradar/core/classifier.py`
- Modify: `kenradar/web/helpers.py`
- Modify: `kenradar/web/app.py`
- Modify: `kenradar/web/templates.py`
- Modify: `kenradar/web/frontend/src/components/RunCenter.tsx`
- Modify: `kenradar/web/frontend/src/mockData.ts`
- Modify: `AGENTS.md`
- Modify: `tests/test_config_and_publishing.py`

**Interfaces:**
- Consumes: Existing OpenAI-compatible provider settings.
- Produces: `agnes-2.5-flash` as the active and fallback model identifier everywhere runtime code can originate it.

- [x] Replace active `agnes-2.0-flash` defaults with `agnes-2.5-flash` without changing endpoints or fallback-provider settings.
- [x] Update the fixture that records an explicit Agnes model to the new identifier.
- [x] Run the focused regression tests and confirm they pass.
- [x] Scan active source paths and confirm no `agnes-2.0-flash` references remain outside historical/generated artifacts.

### Task 3: Verify integration and reload the running system

**Files:**
- No new production files.

**Interfaces:**
- Consumes: `AGNES_API_KEY`, `config/config.yaml`, existing Chat Completions request path.
- Produces: Sanitized evidence of HTTP success, returned model, non-empty content, and healthy restarted services.

- [x] Run Python compile checks, focused pytest, frontend lint, and frontend build.
- [x] Send a minimal non-streaming request to `/v1/chat/completions` using `agnes-2.5-flash`; print only status, returned model, finish reason, token counts, and a content-presence boolean.
- [x] Restart KenRadar so the new YAML configuration is loaded.
- [x] Check process status and the health/status endpoints.
- [x] Review the final diff to ensure no secret or unrelated generated content is included.
