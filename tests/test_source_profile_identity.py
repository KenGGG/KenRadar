from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from kenradar.core.source_resolver import resolve_douyin_source


def test_canonical_profile_preserves_identity_without_redirect():
    uid = "MS4wLjABAAAAHwe0CgM38CCjWMNxHSvkydtX5zlrG38YoPTtrvkX7bRzlN2xJje0cqecaY-1jSay"
    with patch("kenradar.core.source_resolver._resolve_redirect_url") as redirect, patch(
        "kenradar.core.source_resolver._fetch_profile_from_posts",
        new=AsyncMock(return_value={"nickname": "fixture"}),
    ):
        result = resolve_douyin_source(SimpleNamespace(cookies={}), f"https://www.douyin.com/user/{uid}?from_tab_name=main&is_search=0")
    redirect.assert_not_called()
    assert result.sec_uid == uid
    assert result.url == f"https://www.douyin.com/user/{uid}"
    assert result.name == "fixture"


from test_sqlite_v2 import sqlite_db


def test_web_add_source_returns_sqlite_subscription_id(sqlite_db, monkeypatch):
    from kenradar.core.source_resolver import ResolvedDouyinSource
    from kenradar.web.app import _upsert_source_from_form
    from kenradar.core.config import load_config
    from kenradar.sources.douyin.connector import DouyinConnector
    db, config_path = sqlite_db
    uid = "MS4wLjABAAAA_fixture"
    url = f"https://www.douyin.com/user/{uid}"
    monkeypatch.setattr("kenradar.core.source_resolver.resolve_douyin_source",
                        lambda *args, **kwargs: ResolvedDouyinSource(url, uid, "fixture"))
    result = _upsert_source_from_form(str(config_path), {"url": [url], "enabled": ["on"]})
    assert result["id"].startswith("sub:")
    row = db.get_source_subscription(int(result["id"].split(":")[1]))
    assert row["source_key"] == uid and row["enabled"]
    config = load_config(config_path)
    assert any(x["sec_uid"] == uid for x in config.get("bloggers", []))
    config.raw.setdefault("download", {}).setdefault("browser_fallback", {})["enabled"] = True
    assert DouyinConnector(config)._browser_source_allowed(uid)


def test_single_video_creator_update_preserves_existing_follow(sqlite_db):
    from sqlalchemy import select
    db, _ = sqlite_db
    creator = db.upsert_blogger("https://www.douyin.com/user/fixture", "fixture", "fixture", True)
    db.upsert_blogger("https://www.douyin.com/user/fixture", "fixture", "fixture", False,
                     preserve_existing_enabled=True)
    t = db.table("creator")
    with db.connect() as conn:
        assert conn.execute(select(t.c.enabled).where(t.c.id == creator)).fetchone()[0]
