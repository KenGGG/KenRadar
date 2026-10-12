from __future__ import annotations

import os
import subprocess
import urllib.request
from urllib.error import HTTPError
from typing import Any, Callable

from kenradar.core.config import AppConfig


def _entry(status: str, *, detail: str = "") -> dict[str, str]:
    result = {"status": status}
    if detail:
        result["detail"] = detail
    return result


def _probe_http(
    urlopen: Callable[..., Any],
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 1.0,
) -> bool:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        return int(exc.code) < 500
    try:
        status = int(getattr(response, "status", 200) or 200)
        return status < 500
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _provider_list(config: AppConfig | Any) -> list[dict[str, Any]]:
    providers = config.get("ai.organizer.providers", []) or []
    return [item for item in providers if isinstance(item, dict) and item.get("enabled", True)]


def dependency_status(
    config: AppConfig | Any,
    *,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
    process_runner: Callable[..., Any] = subprocess.run,
    database_probe: Callable[[], Any] | None = None,
    schema_probe: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return side-effect-free dependency health; optional failures only degrade."""
    dependencies: dict[str, dict[str, str]] = {}
    database_key = "sqlite" if getattr(config, "database_type", "") == "sqlite" else "postgres"

    if database_probe is None:
        def database_probe() -> Any:
            from kenradar.storage import create_database
            database = create_database(config)
            if database_key == "sqlite":
                return database.diagnostic()
            with database.connect() as conn:
                conn.execute("SELECT 1").fetchone()
    try:
        diagnostic = database_probe()
        dependencies[database_key] = _entry("ok")
        if database_key == "sqlite" and isinstance(diagnostic, dict):
            dependencies[database_key]["diagnostic"] = diagnostic
            if diagnostic["integrity"] != "ok" or diagnostic["foreign_key_errors"] or diagnostic["journal_mode"].lower() != "wal":
                dependencies[database_key]["status"] = "unavailable"
    except Exception as exc:
        dependencies[database_key] = _entry("unavailable", detail=type(exc).__name__)

    if schema_probe is None:
        def schema_probe() -> dict[str, Any]:
            from kenradar.storage.migrate import schema_status
            return schema_status(str(getattr(config, "path", "config/config.yaml")))
    try:
        schema = schema_probe()
        dependencies["schema"] = _entry("ok" if schema.get("up_to_date") else "degraded")
    except Exception as exc:
        dependencies["schema"] = _entry("unavailable", detail=type(exc).__name__)

    providers = _provider_list(config)
    agnes = next((item for item in providers if str(item.get("api_type") or "") != "ollama"), None)
    if not agnes:
        dependencies["agnes"] = _entry("disabled")
    else:
        endpoint = str(agnes.get("endpoint") or "").rstrip("/")
        env_var = str(agnes.get("env_var") or "AGNES_API_KEY")
        api_key = os.getenv(env_var, "").strip()
        if bool(agnes.get("requires_api_key", True)) and not api_key:
            dependencies["agnes"] = _entry("unavailable", detail=f"missing {env_var}")
        elif not endpoint:
            dependencies["agnes"] = _entry("unavailable", detail="missing endpoint")
        else:
            try:
                headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
                timeout = float(config.get("dependency_health.agnes_timeout_seconds", 5.0) or 5.0)
                ok = _probe_http(urlopen, f"{endpoint}/models", headers=headers, timeout=max(1.0, timeout))
                dependencies["agnes"] = _entry("ok" if ok else "degraded")
            except Exception as exc:
                dependencies["agnes"] = _entry("degraded", detail=type(exc).__name__)

    ollama = next((item for item in providers if str(item.get("api_type") or "").lower() == "ollama"), None)
    if not ollama:
        dependencies["ollama"] = _entry("disabled")
    else:
        endpoint = str(ollama.get("endpoint") or "").rstrip("/")
        base = endpoint[:-3] if endpoint.endswith("/v1") else endpoint
        try:
            ok = bool(base) and _probe_http(urlopen, f"{base}/api/version")
            dependencies["ollama"] = _entry("ok" if ok else "unavailable")
        except Exception as exc:
            dependencies["ollama"] = _entry("unavailable", detail=type(exc).__name__)

    if not bool(config.get("ai.funasr.enabled", False)):
        dependencies["funasr"] = _entry("disabled")
    else:
        endpoint = str(config.get("ai.funasr.endpoint", "")).rstrip("/")
        try:
            ok = bool(endpoint) and _probe_http(urlopen, f"{endpoint}/models")
            dependencies["funasr"] = _entry("ok" if ok else "unavailable")
        except Exception as exc:
            status = "idle" if bool(config.get("ai.funasr.managed", False)) else "unavailable"
            dependencies["funasr"] = _entry(status, detail=type(exc).__name__)

    try:
        query_tool = str(config.get("gpu_scheduler.memory_check.command") or ("n" + "vidia-smi"))
        result = process_runner(
            [query_tool, "--query-gpu=name,utilization.gpu", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
        dependencies["gpu"] = _entry("ok" if result.returncode == 0 and str(result.stdout).strip() else "unavailable")
    except Exception as exc:
        dependencies["gpu"] = _entry("unavailable", detail=type(exc).__name__)

    dependencies["feishu"] = _entry("configured" if str(getattr(config, "feishu_webhook_url", "")) else "disabled")
    github_enabled = bool(config.get("publishing.github_pages.enabled", False))
    github_sync = bool(config.get("publishing.github_sync.enabled", False))
    dependencies["github_publishing"] = _entry("configured" if github_enabled or github_sync else "disabled")

    required_ok = all(dependencies[name]["status"] == "ok" for name in (database_key, "schema"))
    optional_degraded = any(
        entry["status"] in {"degraded", "unavailable"}
        for name, entry in dependencies.items()
        if name not in {database_key, "schema"}
    )
    return {
        "dependencies": dependencies,
        **{name: entry["status"] for name, entry in dependencies.items()},
        "all_ok": required_ok,
        "degraded": optional_degraded,
    }
