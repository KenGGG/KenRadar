from test_sqlite_v2 import sqlite_db


def test_legacy_note_links_use_database_platform_and_string_id(sqlite_db, tmp_path, monkeypatch):
    from kenradar.core.config import load_config
    from kenradar.web import queries

    db, config_path = sqlite_db
    root = tmp_path / "notes"
    path = root / "podcast" / "fixture" / "legacy.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Legacy note without frontmatter\n", encoding="utf-8")
    creator = db.upsert_creator("xiaoyuzhou", "show", "fixture", "")
    external_id = "000000000000000000000123"
    db.upsert_content_item("xiaoyuzhou", external_id, creator)
    db.upsert_summary(external_id, "summary", str(path), "fixture", "success", platform="xiaoyuzhou")
    monkeypatch.setattr(queries, "summary_dir", lambda config: root)
    notes = queries.load_note_files(load_config(config_path))
    assert len(notes) == 1
    assert notes[0]["platform"] == "xiaoyuzhou"
    assert notes[0]["external_id"] == external_id
    assert notes[0]["analysis_status"] == "success"
