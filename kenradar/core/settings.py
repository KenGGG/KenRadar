"""Revisioned, secret-safe configuration editing. YAML remains the only truth."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field
import yaml

from .config import AppConfig, _atomic_dump_yaml, _config_lock, _dotted_get, _dotted_set, _expand_env_vars, _validate_config


GROUPS = {
    "overview": {"app.timezone"},
    "accounts": {"app.douyin_cookie_file"},
    "transcription_ai": {"ai.transcription.enabled", "ai.funasr.enabled", "ai.funasr.managed", "ai.funasr.endpoint", "ai.whisper.enabled", "ai.whisper.model", "ai.whisper.device", "ai.whisper.compute_type", "ai.organizer.providers"},
    "automatic": {"schedule.enabled", "schedule.source_radar_enabled", "schedule.times", "download.workers"},
    "notes_storage": {"app.data_dir", "app.database_url", "download.path"},
    "delivery": {"publishing.github_pages.enabled", "publishing.github_pages.public_base_url", "publishing.github_sync.enabled", "publishing.github_sync.auto_push", "notification.enabled", "notification.channels.feishu.enabled", "notification.channels.feishu.include_full_text"},
    "backup": set(),
    "security": {"app.web_base_url"},
}
SECRET_PATHS = {
    "accounts": {"cookies.douyin"},
    "delivery": {"notification.channels.feishu.webhook_url"},
    "security": {"app.web_password"},
    "transcription_ai": set(),
}
SECRET_KEY = re.compile(r"api[_-]?key|cookie|password|webhook|authorization|access[_-]?token", re.I)
DEFAULTS = {"app.timezone": "Asia/Shanghai", "schedule.enabled": False, "schedule.source_radar_enabled": False, "schedule.times": ["09:00", "12:00", "15:00", "18:00", "21:00"], "download.workers": 2, "ai.whisper.device": "cpu", "ai.whisper.model": "large-v3-turbo", "ai.whisper.compute_type": "int8", "ai.funasr.endpoint": "http://127.0.0.1:18002/v1", "ai.organizer.providers": [], "app.web_base_url": "http://127.0.0.1:8765"}
DEFAULTS["ai.transcription.enabled"] = True
DEFAULTS.update({"ai.whisper.enabled": True, "ai.funasr.managed": True, "schedule.enabled": True, "schedule.source_radar_enabled": True, "notification.enabled": True, "notification.channels.feishu.enabled": True})


class RevisionConflict(ValueError):
    pass


class ProviderDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    endpoint: str
    model: str = ""
    api_type: str = "chat_completions"
    type: str | None = None
    env_var: str | None = None
    enabled: bool = True
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    top_k: int | None = Field(default=None, ge=0)
    rpm_limit: int | None = Field(default=None, ge=0)
    timeout: int | None = Field(default=None, gt=0, le=1800)
    retry_count: int | None = Field(default=None, ge=0, le=5)
    retry_delay: float | None = Field(default=None, ge=0, le=120)
    main_gpu: int | None = Field(default=None, ge=0)
    num_gpu: int | None = None
    num_ctx: int | None = Field(default=None, gt=0)
    max_input_chars: int | None = Field(default=None, ge=0)
    require_gpu: bool | None = None
    requires_api_key: bool | None = None
    omit_top_k: bool | None = None
    system_as_user: bool | None = None
    no_think: bool | None = None
    compact_prompt: bool | None = None


class SecretEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["keep", "replace", "delete"] = "keep"
    value: str = ""


class SettingsDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    group: str
    expected_revision: str = Field(min_length=64, max_length=64)
    values: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, SecretEdit] = Field(default_factory=dict)


def revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: (_secret_state(item) if (SECRET_KEY.search(key) and key != "douyin_cookie_file") or (key == "env_var" and item and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(item))) else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _secret_state(value):
    env = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(value or ""))
    return {"configured": bool(os.environ.get(env[1])) if env else bool(value), "source": "environment" if env else "yaml"}


def read_settings(path: str | Path) -> dict:
    path = Path(path)
    # Read bytes once so the revision corresponds to the returned snapshot.
    content = path.read_bytes()
    raw = yaml.safe_load(content) or {}
    groups = {name: {key: _redact({key.split(".")[-1]: _dotted_get(raw, key)})[key.split(".")[-1]] for key in sorted(keys)} for name, keys in GROUPS.items()}
    for fields in groups.values():
        for key, value in fields.items():
            if value is None:
                fields[key] = DEFAULTS.get(key, False if key.endswith((".enabled", ".managed", ".auto_push", ".include_full_text")) else "")
    secrets = {}
    for name, keys in SECRET_PATHS.items():
        secrets[name] = {key: _secret_state(_dotted_get(raw, key)) for key in sorted(keys)}
    for index, provider in enumerate(_dotted_get(raw, "ai.organizer.providers") or []):
        env_var = str(provider.get("env_var") or "")
        value = "${" + env_var + "}" if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_var) else env_var or provider.get("api_key")
        secrets["transcription_ai"][f"ai.organizer.providers.{index}.api_key"] = _secret_state(value)
    overrides = {}
    for fields in groups.values():
        for key in fields:
            value = _dotted_get(raw, key)
            env = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", str(value or ""))
            if env:
                overrides[key] = {"source": "environment", "variable": env[1]}
    for key, variable, group in (("app.database_url", "DATABASE_URL", None), ("app.web_password", "KENRADAR_WEB_PASSWORD", "security"), ("notification.channels.feishu.webhook_url", "FEISHU_WEBHOOK_URL", "delivery")):
        if os.environ.get(variable):
            overrides[key] = {"source": "environment", "variable": variable}
            if group:
                secrets[group][key] = {"configured": True, "source": "environment"}
    running = []
    try:
        from kenradar.storage.sqlite_database import Database
        config = AppConfig(raw=_expand_env_vars(raw), path=path.resolve())
        if config.database_type == "sqlite":
            db = Database(config.database_url)
            db.initialize()
            running = [{"task_run_id": row["id"], "revision": row["config_revision"]} for row in db.list_task_runs(limit=100, status="running")]
            db.close()
    except Exception:
        # Missing/uninitialized storage remains visible as a separate health condition.
        pass
    return {"groups": groups, "secrets": secrets, "revision": hashlib.sha256(content).hexdigest(), "running_revisions": running, "effective_revision": None, "effective_status": "running_task_revisions" if running else "no_running_tasks", "overrides": overrides}


def _candidate(path: Path, draft: SettingsDraft) -> dict:
    if draft.group not in GROUPS:
        raise ValueError("unknown settings group")
    if set(draft.values) - GROUPS[draft.group]:
        raise ValueError("unsupported field for settings group")
    for key in draft.secrets:
        provider_secret = draft.group == "transcription_ai" and re.fullmatch(r"ai\.organizer\.providers\.\d+\.api_key", key)
        if key not in SECRET_PATHS.get(draft.group, set()) and not provider_secret:
            raise ValueError("unsupported secret field")
    raw = yaml.safe_load(path.read_bytes()) or {}
    candidate = deepcopy(raw)
    for key, value in draft.values.items():
        if key.endswith((".enabled", ".managed", ".auto_push", ".include_full_text")) and type(value) is not bool:
            raise ValueError("boolean field requires a boolean")
        if key == "download.workers" and (type(value) is not int or not 1 <= value <= 16):
            raise ValueError("download.workers must be between 1 and 16")
        if key not in {"download.workers", "schedule.times", "ai.organizer.providers"} and not key.endswith((".enabled", ".managed", ".auto_push", ".include_full_text")) and not isinstance(value, str):
            raise ValueError("text field requires a string")
        if key == "app.timezone":
            ZoneInfo(value)
        if key.endswith((".endpoint", ".web_base_url", ".public_base_url")) and value and not re.fullmatch(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", value):
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("endpoint requires an HTTP URL")
        if key == "ai.organizer.providers":
            if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
                raise ValueError("providers must be objects")
            old = _dotted_get(raw, key) or []
            for index, provider in enumerate(value):
                if any(SECRET_KEY.search(field) for field in provider):
                    raise ValueError("provider secrets require a separate secret operation")
                if provider.get("env_var") and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(provider["env_var"])):
                    raise ValueError("env_var must be an environment variable name")
                ProviderDraft.model_validate(provider)
                endpoint = urlparse(provider["endpoint"])
                if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
                    raise ValueError("provider endpoint requires an HTTP URL")
                ollama = provider.get("api_type") == "ollama" or endpoint.port == 11434
                if provider.get("top_k") not in {None, 0} and not ollama and not provider.get("omit_top_k"):
                    raise ValueError("top_k is only supported by the Ollama provider")
                if endpoint.hostname and endpoint.hostname.endswith("agnes-ai.com"):
                    if provider.get("rpm_limit", 19) != 19:
                        raise ValueError("Agnes provider must retain the 19 RPM limit")
                    provider.setdefault("rpm_limit", 19)
                identity_changed = index < len(old) and any(provider.get(field) != old[index].get(field) for field in ("name", "endpoint"))
                secret_edit = draft.secrets.get(f"ai.organizer.providers.{index}.api_key")
                if identity_changed and old[index].get("api_key") and (not secret_edit or secret_edit.action == "keep" or (secret_edit.action == "replace" and not secret_edit.value)):
                    raise ValueError("changing provider identity requires an explicit credential operation")
                # Preserve existing provider credentials, without exposing them to clients.
                if index < len(old) and all(provider.get(field) == old[index].get(field) for field in ("name", "endpoint")):
                    for field, secret in old[index].items():
                        if SECRET_KEY.search(field):
                            provider[field] = secret
        _dotted_set(candidate, key, value)
    for key, edit in draft.secrets.items():
        if key.startswith("ai.organizer.providers."):
            providers = _dotted_get(candidate, "ai.organizer.providers") or []
            index = int(key.split(".")[-2])
            if index >= len(providers):
                raise ValueError("provider does not exist")
            if edit.action == "replace" and edit.value:
                providers[index]["api_key"] = edit.value
            elif edit.action == "delete":
                providers[index]["api_key"] = ""
            continue
        if edit.action == "replace" and edit.value:
            _dotted_set(candidate, key, edit.value)
        elif edit.action == "delete":
            _dotted_set(candidate, key, "")
    if "app.database_url" in draft.values and not str(draft.values["app.database_url"]).startswith("sqlite:///"):
        raise ValueError("runtime settings require a SQLite file URL")
    _validate_config(_expand_env_vars(candidate), path, reject_duplicate_bloggers=True)
    return candidate


def edit_settings(path: str | Path, payload: dict, *, save: bool = False) -> dict:
    path = Path(path)
    draft = SettingsDraft.model_validate(payload)
    with _config_lock(path):
        if revision(path) != draft.expected_revision:
            raise RevisionConflict("configuration changed; reload before saving")
        candidate = _candidate(path, draft)
        if save:
            backup = path.with_name(path.name + "." + draft.expected_revision + ".bak")
            if not backup.exists():
                with backup.open("xb") as stream:
                    stream.write(path.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
            _atomic_dump_yaml(path, candidate)
        restart = bool(set(draft.values) & {"app.database_url", "app.data_dir", "app.web_base_url"}) or "app.web_password" in draft.secrets
        return {"ok": True, "saved": save, "saved_revision": revision(path) if save else None, "validated_revision": draft.expected_revision, "effective_revision": None, "restart_required": restart, "effective_status": "restart_required" if restart else "new_tasks", "external_actions": False}
