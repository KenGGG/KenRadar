from pathlib import Path

import pytest
import subprocess
import sys

from scripts.export_public_release import export_release
from scripts.public_release_audit import audit_tree, load_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_audit_rejects_git_history_and_real_secrets(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git/config").write_text("private remote", encoding="utf-8")
    (tmp_path / "settings.txt").write_text(
        "AGNES_API_KEY=" + "sk-live-" + "example-not-placeholder\n"
        "DATABASE_URL=" + "postgresql://user:" + "real-password@db/app\n",
        encoding="utf-8",
    )
    rules = {(item.path, item.rule) for item in audit_tree(tmp_path)}
    assert (".git", "forbidden_path") in rules
    assert any(rule == "secret_assignment" for _, rule in rules)
    assert any(rule == "credential_url" for _, rule in rules)


def test_audit_allows_documented_placeholders(tmp_path: Path) -> None:
    nested = tmp_path / "frontend"
    nested.mkdir()
    (nested / ".env.example").write_text(
        "AGNES_API_KEY=CHANGE_ME\n"
        "DATABASE_URL=postgresql://kenradar:CHANGE_ME@postgres:5432/kenradar\n",
        encoding="utf-8",
    )
    (tmp_path / "module.py").write_text(
        "api_key = config.get('API_KEY')\npassword = read_password()\n",
        encoding="utf-8",
    )
    (tmp_path / "backup_pg.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    assert audit_tree(tmp_path) == []


def test_audit_allows_adjacent_empty_optional_secrets(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "ORGANIZER_API_KEY=\nFEISHU_WEBHOOK_URL=\n", encoding="utf-8"
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


def test_export_copies_allowlist_without_git_or_runtime_data(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "public"
    (source / "kenradar").mkdir(parents=True)
    (source / "kenradar/__init__.py").write_text("", encoding="utf-8")
    (source / ".git").mkdir()
    (source / "data").mkdir()
    (source / "data/private.md").write_text("private", encoding="utf-8")
    manifest = source / "manifest.txt"
    manifest.write_text("kenradar/__init__.py\n", encoding="utf-8")

    result = export_release(source, destination, manifest)

    assert result.findings == ()
    assert (destination / "kenradar/__init__.py").exists()
    assert not (destination / ".git").exists()
    assert not (destination / "data").exists()


def test_refresh_refuses_unmarked_nonempty_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    manifest = source / "manifest.txt"
    manifest.write_text("README.md\n", encoding="utf-8")
    (source / "README.md").write_text("public", encoding="utf-8")
    destination = tmp_path / "public"
    destination.mkdir()
    (destination / "user-file.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="not a recognized public export"):
        export_release(source, destination, manifest, refresh=True)


def test_export_cli_runs_directly_from_repository_root(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "source"
    source.mkdir()
    (source / "README.md").write_text("public", encoding="utf-8")
    manifest = source / "manifest.txt"
    manifest.write_text("README.md\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/export_public_release.py",
            "--source",
            str(source),
            "--manifest",
            str(manifest),
            "--destination",
            str(tmp_path / "public"),
            "--dry-run",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "findings=0" in result.stdout


def test_every_exported_vendor_file_has_a_notice_entry() -> None:
    exported = {
        path
        for path in (ROOT / "kenradar/vendor/douyin_downloader").glob("*.py")
        if path.is_file()
    }
    notices = (ROOT / "tests/fixtures/public-release/THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )
    for path in exported:
        relative = path.relative_to(ROOT).as_posix()
        assert f"`{relative}`" in notices
