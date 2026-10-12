import json
import yaml
import pytest
from kenradar.core.settings import RevisionConflict, edit_settings, read_settings
from test_sqlite_v2 import sqlite_db


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"app": {"database_url": "sqlite:///data/test.sqlite3", "web_password": "private-password"}, "cookies": {"douyin": "private-cookie"}, "schedule": {"enabled": False, "times": ["09:00"]}, "ai": {"organizer": {"providers": [{"name": "agnes", "endpoint": "https://example.com/v1", "api_key": "private-key"}]}}, "notification": {"channels": {"feishu": {"webhook_url": "https://example.com/private-webhook"}}}}), encoding="utf-8")
    return path


def draft(path, group="automatic", **values):
    return {"group": group, "expected_revision": read_settings(path)["revision"], "values": values}


def test_snapshot_and_validation_never_expose_or_write_secrets(config):
    encoded = json.dumps(read_settings(config))
    for secret in ("private-password", "private-cookie", "private-key", "private-webhook"):
        assert secret not in encoded
    before = config.read_bytes()
    result = edit_settings(config, draft(config, **{"schedule.enabled": True}))
    assert result["saved"] is False and not result["external_actions"]
    assert config.read_bytes() == before


def test_revision_conflict_backup_and_failed_draft(config):
    initial = draft(config, **{"schedule.enabled": True})
    saved = edit_settings(config, initial, save=True)
    assert saved["saved"] and saved["effective_status"] == "new_tasks"
    assert saved["effective_revision"] is None
    assert len(list(config.parent.glob("*.bak"))) == 1
    with pytest.raises(RevisionConflict):
        edit_settings(config, initial, save=True)
    before = config.read_bytes()
    with pytest.raises(ValueError):
        edit_settings(config, draft(config, **{"schedule.enabled": "false"}), save=True)
    assert config.read_bytes() == before


def test_secret_keep_replace_delete_and_group_boundary(config):
    item = draft(config, "security")
    item["secrets"] = {"app.web_password": {"action": "replace", "value": ""}}
    edit_settings(config, item, save=True)
    assert yaml.safe_load(config.read_text())["app"]["web_password"] == "private-password"
    item = draft(config, "security")
    item["secrets"] = {"app.web_password": {"action": "delete"}}
    assert edit_settings(config, item, save=True)["restart_required"]
    assert yaml.safe_load(config.read_text())["app"]["web_password"] == ""
    with pytest.raises(ValueError):
        edit_settings(config, draft(config, "automatic", **{"app.database_url": "sqlite:///other.sqlite3"}), save=True)


def test_external_probe_requires_confirmation_and_never_saves(config, monkeypatch):
    from kenradar.core.settings_tests import probe
    import requests
    def forbidden(*args, **kwargs):
        pytest.fail("unconfirmed probe must not call network")
    monkeypatch.setattr(requests.Session, "get", forbidden)
    monkeypatch.setattr(requests.Session, "post", forbidden)
    before = config.read_bytes()
    result = probe(config, {"draft": draft(config, "delivery"), "kind": "feishu_send"})
    assert result["confirmation_required"] and not result["network"]
    assert config.read_bytes() == before


def test_task_revision_matches_loaded_snapshot(sqlite_db):
    from kenradar.storage import create_database
    from kenradar.core.config import load_config
    db, path = sqlite_db
    config = load_config(path)
    database = create_database(config)
    database.enqueue_task_run("system_health_check", {}, "snapshot")
    path.write_text(path.read_text() + "\n# later config version\n", encoding="utf-8")
    task = database.claim_next_task_run("snapshot-owner")
    assert task["config_revision"] == config.source_revision
    assert task["config_revision"] != read_settings(path)["revision"]
