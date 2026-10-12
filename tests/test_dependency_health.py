from __future__ import annotations

from types import SimpleNamespace
from contextlib import contextmanager
from urllib.error import HTTPError

from kenradar.web.dependency_health import dependency_status


def _config(values):
    return SimpleNamespace(
        get=lambda key, default=None: values.get(key, default),
        feishu_webhook_url=values.get("feishu_webhook_url", ""),
    )


def test_dependency_health_discovers_agnes_and_ollama_across_all_providers(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", "test-key")
    visited = []
    timeouts = []

    def urlopen(request, timeout=0):
        visited.append(str(getattr(request, "full_url", request)))
        timeouts.append(timeout)
        return SimpleNamespace(status=200, close=lambda: None)

    result = dependency_status(
        _config({
            "ai.organizer.providers": [
                {"name": "agnes", "enabled": True, "api_type": "chat_completions", "endpoint": "https://agnes.example/v1", "env_var": "AGNES_API_KEY", "requires_api_key": True},
                {"name": "fallback", "enabled": True, "api_type": "ollama", "endpoint": "http://127.0.0.1:11434/v1"},
            ],
            "ai.funasr.enabled": False,
        }),
        urlopen=urlopen,
        process_runner=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
        database_probe=lambda: None,
        schema_probe=lambda: {"up_to_date": True},
    )

    assert result["dependencies"]["agnes"]["status"] == "ok"
    assert result["dependencies"]["ollama"]["status"] == "ok"
    assert any("agnes.example" in url for url in visited)
    assert any("11434" in url for url in visited)
    assert timeouts[0] >= 3.0


def test_managed_on_demand_funasr_is_idle_when_not_running():
    def unavailable(*args, **kwargs):
        raise OSError("connection refused")

    result = dependency_status(
        _config({
            "ai.organizer.providers": [],
            "ai.funasr.enabled": True,
            "ai.funasr.managed": True,
            "ai.funasr.endpoint": "http://127.0.0.1:18002/v1",
        }),
        urlopen=unavailable,
        process_runner=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
        database_probe=lambda: None,
        schema_probe=lambda: {"up_to_date": True},
    )

    assert result["dependencies"]["funasr"]["status"] == "idle"
    assert result["all_ok"] is True


def test_http_404_from_capability_probe_still_proves_provider_is_reachable(monkeypatch):
    monkeypatch.setenv("AGNES_API_KEY", "test-key")

    def reachable_without_models(request, timeout=0):
        raise HTTPError(str(request.full_url), 404, "not found", {}, None)

    result = dependency_status(
        _config({
            "ai.organizer.providers": [{"name": "agnes", "enabled": True, "api_type": "chat_completions", "endpoint": "https://agnes.example/v1", "env_var": "AGNES_API_KEY"}],
            "ai.funasr.enabled": False,
        }),
        urlopen=reachable_without_models,
        process_runner=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
        database_probe=lambda: None,
        schema_probe=lambda: {"up_to_date": True},
    )

    assert result["dependencies"]["agnes"]["status"] == "ok"


def test_disabled_optional_dependencies_are_not_reported_as_failures():
    result = dependency_status(
        _config({"ai.organizer.providers": [], "ai.funasr.enabled": False}),
        urlopen=lambda *args, **kwargs: None,
        process_runner=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
        database_probe=lambda: None,
        schema_probe=lambda: {"up_to_date": True},
    )

    assert result["dependencies"]["agnes"]["status"] == "disabled"
    assert result["dependencies"]["ollama"]["status"] == "disabled"
    assert result["dependencies"]["funasr"]["status"] == "disabled"
    assert result["all_ok"] is True


def test_readiness_rejects_stale_schema(monkeypatch):
    from kenradar.web import helpers

    class Connection:
        def execute(self, sql):
            value = "task_run" if "to_regclass" in sql else 1
            return SimpleNamespace(fetchone=lambda: [value])

    class Database:
        @contextmanager
        def connect(self):
            yield Connection()

    monkeypatch.setattr(helpers, "load_config", lambda path: SimpleNamespace(database_type="sqlite"))
    monkeypatch.setattr(helpers, "create_database", lambda config: Database())
    monkeypatch.setattr("kenradar.storage.migrate.schema_status", lambda path: {"up_to_date": False, "current": "0011", "head": "0012"})

    result = helpers._readiness_status("config.yaml")

    assert result["ok"] is False
    assert result["checks"]["schema"] == "stale: 0011 -> 0012"
