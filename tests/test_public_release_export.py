from pathlib import Path

from scripts.public_release_audit import audit_tree, load_manifest


def test_audit_rejects_git_history_and_real_secrets(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").write_text("private remote", encoding="utf-8")
    (tmp_path / "settings.txt").write_text(
        "AGNES_API_KEY=sk-live-example-not-placeholder\n"
        "DATABASE_URL=postgresql://user:real-password@db/app\n",
        encoding="utf-8",
    )
    rules = {(item.path, item.rule) for item in audit_tree(tmp_path)}
    assert (".git", "forbidden_path") in rules
    assert any(rule == "secret_assignment" for _, rule in rules)
    assert any(rule == "credential_url" for _, rule in rules)


def test_audit_allows_documented_placeholders(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "AGNES_API_KEY=CHANGE_ME\n"
        "DATABASE_URL=postgresql://kenradar:CHANGE_ME@postgres:5432/kenradar\n",
        encoding="utf-8",
    )
    assert audit_tree(tmp_path) == []


def test_manifest_ignores_comments_and_rejects_parent_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.txt"
    manifest.write_text("# public files\nkenradar/\n../private\n", encoding="utf-8")
    try:
        load_manifest(manifest)
    except ValueError as exc:
        assert "unsafe manifest path" in str(exc)
    else:
        raise AssertionError("parent traversal must be rejected")
