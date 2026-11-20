import json
from pathlib import Path
from kenradar.core.config import AppConfig
from kenradar.web.public_archive import archive_entries, archive_file


def test_public_archive_keeps_history_and_refuses_private_and_escape(tmp_path):
    root = tmp_path / "public"
    note = root / "notes" / "douyin" / "creator" / "123.html"
    note.parent.mkdir(parents=True)
    note.write_text("<h1>Historical article</h1>", encoding="utf-8")
    secret = note.with_name("private.html")
    secret.write_text("hermes_private: true", encoding="utf-8")
    (root / "content-index.json").write_text(json.dumps({"items": [{"relative_url": "notes/douyin/creator/123.html", "title": "History"}, {"relative_url": "../escape.html"}, {"relative_url": "notes/missing.html"}]}), encoding="utf-8")
    (tmp_path / "escape.html").write_text("secret", encoding="utf-8")
    config = AppConfig({"publishing": {"github_pages": {"output_dir": str(root)}}}, tmp_path / "config.yaml")
    assert len(archive_entries(config)) == 1
    assert b"Historical article" in archive_file(config, "notes/douyin/creator/123.html")[0]
    for path in ("../escape.html", "%2e%2e/escape.html", "..\\escape.html", "notes/douyin/creator/private.html", ".git/config"):
        assert archive_file(config, path) is None
