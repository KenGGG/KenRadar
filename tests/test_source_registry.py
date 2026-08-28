from __future__ import annotations

from types import SimpleNamespace

from kenradar.core.source_registry import SourceRegistry


def _config(bloggers):
    return SimpleNamespace(get=lambda key, default=None: bloggers if key == "bloggers" else default)


class FakeSourceDatabase:
    def __init__(self, subscriptions=None):
        self.subscriptions = {row["source_key"]: dict(row) for row in (subscriptions or [])}
        self.creators = {}
        self.next_id = 1

    def upsert_blogger(self, url, name, sec_uid, enabled=True, preserve_existing_enabled=False):
        current = self.creators.get(sec_uid)
        if current is None:
            current = {"id": self.next_id, "enabled": enabled}
            self.next_id += 1
        elif not preserve_existing_enabled:
            current["enabled"] = enabled
        current.update({"url": url, "name": name})
        self.creators[sec_uid] = current
        return current["id"]

    def upsert_source_subscription(self, *, preserve_existing_enabled=False, **values):
        key = values["source_key"]
        current = self.subscriptions.get(key)
        if current is None:
            current = {"id": self.next_id, **values}
            self.next_id += 1
        else:
            enabled = current["enabled"] if preserve_existing_enabled else values["enabled"]
            current.update(values)
            current["enabled"] = enabled
        self.subscriptions[key] = current
        return dict(current)

    def list_source_subscriptions(self, platform=None, enabled=None):
        rows = [dict(row) for row in self.subscriptions.values() if platform in (None, row.get("platform"))]
        if enabled is not None:
            rows = [row for row in rows if row.get("enabled") is enabled]
        return rows


def test_config_import_is_idempotent_and_preserves_db_disabled_state():
    database = FakeSourceDatabase([
        {
            "id": 8,
            "platform": "douyin",
            "source_key": "sec-1",
            "display_name": "数据库名称",
            "source_url": "https://www.douyin.com/user/sec-1",
            "enabled": False,
            "creator_id": 7,
        }
    ])
    registry = SourceRegistry(
        _config([{"sec_uid": "sec-1", "name": "配置名称", "url": "https://www.douyin.com/user/sec-1", "enabled": True}]),
        database,
    )

    first = registry.import_config_sources()
    second = registry.import_config_sources()

    assert first["imported"] == 1
    assert second["imported"] == 1
    assert len(database.subscriptions) == 1
    assert database.subscriptions["sec-1"]["enabled"] is False


def test_monitor_targets_are_loaded_from_enabled_database_subscriptions_first():
    database = FakeSourceDatabase([
        {"id": 1, "platform": "douyin", "source_key": "db-enabled", "display_name": "DB 开启", "source_url": "https://www.douyin.com/user/db-enabled", "enabled": True, "creator_id": 11},
        {"id": 2, "platform": "douyin", "source_key": "db-disabled", "display_name": "DB 停用", "source_url": "https://www.douyin.com/user/db-disabled", "enabled": False, "creator_id": 12},
    ])
    registry = SourceRegistry(
        _config([{"sec_uid": "yaml-only", "name": "YAML", "url": "https://www.douyin.com/user/yaml-only", "enabled": True}]),
        database,
    )

    targets = registry.list_monitor_targets()

    assert [(target.id, target.sec_uid) for target in targets] == [(11, "db-enabled")]
    assert "yaml-only" not in database.subscriptions


def test_empty_database_imports_config_then_returns_targets():
    database = FakeSourceDatabase()
    registry = SourceRegistry(
        _config([{"sec_uid": "sec-1", "name": "来源一", "url": "https://www.douyin.com/user/sec-1", "enabled": True}]),
        database,
    )

    targets = registry.list_monitor_targets()

    assert len(targets) == 1
    assert targets[0].sec_uid == "sec-1"
    assert database.subscriptions["sec-1"]["platform"] == "douyin"


def test_diagnostics_reports_counts_without_source_identifiers():
    database = FakeSourceDatabase([
        {"id": 1, "platform": "douyin", "source_key": "db-1", "display_name": "DB", "source_url": "", "enabled": True, "creator_id": 4}
    ])
    registry = SourceRegistry(
        _config([{"sec_uid": "config-1", "name": "配置", "url": "", "enabled": False}]),
        database,
    )

    result = registry.diagnostics()

    assert result == {
        "config_total": 1,
        "config_enabled": 0,
        "database_total": 1,
        "database_enabled": 1,
        "config_only": 1,
        "database_only": 1,
    }
