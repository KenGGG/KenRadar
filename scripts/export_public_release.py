from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts.public_release_audit import Finding, audit_tree, load_manifest
except ModuleNotFoundError:
    from public_release_audit import Finding, audit_tree, load_manifest


MARKER_NAME = ".kenradar-public-export.json"
MARKER_SCHEMA = 1


@dataclass(frozen=True)
class ExportResult:
    copied: tuple[str, ...]
    removed: tuple[str, ...]
    findings: tuple[Finding, ...]


def export_release(
    source: Path,
    destination: Path,
    manifest_path: Path,
    refresh: bool = False,
    dry_run: bool = False,
) -> ExportResult:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination or source in destination.parents:
        raise ValueError("destination must be outside the private source tree")
    if destination.exists() and any(destination.iterdir()):
        marker = destination / MARKER_NAME
        if not refresh or not marker.is_file():
            raise RuntimeError("destination is not a recognized public export")
        previous = _read_marker(marker)
    else:
        previous = {"files": []}

    tracked = _tracked_files(source)
    selected = _expand_manifest(source, manifest_path, tracked)
    staging = Path(tempfile.mkdtemp(prefix="kenradar-public-export-"))
    try:
        for relative in selected:
            source_path = source / relative
            target_path = staging / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        findings = tuple(audit_tree(staging))
        if findings or dry_run:
            return ExportResult(tuple(selected), (), findings)

        destination.mkdir(parents=True, exist_ok=True)
        old_files = {str(item) for item in previous.get("files", []) if isinstance(item, str)}
        stale = sorted(old_files - set(selected))
        for relative in stale:
            stale_path = destination / relative
            if stale_path.is_file() or stale_path.is_symlink():
                stale_path.unlink()
        for relative in selected:
            target_path = destination / relative
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / relative, target_path)
        _prune_empty_directories(destination)
        marker_payload = {
            "schema": MARKER_SCHEMA,
            "source_commit": _source_commit(source),
            "files": selected,
        }
        (destination / MARKER_NAME).write_text(
            json.dumps(marker_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return ExportResult(tuple(selected), tuple(stale), ())
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _tracked_files(source: Path) -> set[str]:
    result = subprocess.run(
        ["git", "-C", str(source), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return {item for item in result.stdout.split("\0") if item}
    return {
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(source).parts
    }


def _expand_manifest(source: Path, manifest_path: Path, tracked: set[str]) -> list[str]:
    selected: set[str] = set()
    for entry in load_manifest(manifest_path):
        if entry.endswith("/"):
            prefix = entry
            matches = {path for path in tracked if path.startswith(prefix)}
            if not matches:
                raise FileNotFoundError(f"manifest directory has no tracked files: {entry}")
            selected.update(matches)
            continue
        if entry not in tracked:
            raise FileNotFoundError(f"manifest file is not tracked: {entry}")
        selected.add(entry)
    for relative in selected:
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"manifest entry is not a regular file: {relative}")
    return sorted(selected)


def _read_marker(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("destination is not a recognized public export") from exc
    if payload.get("schema") != MARKER_SCHEMA or not isinstance(payload.get("files"), list):
        raise RuntimeError("destination is not a recognized public export")
    return payload


def _source_commit(source: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unversioned-test-source"


def _prune_empty_directories(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and path.name != ".git":
            try:
                path.rmdir()
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a sanitized KenRadar public tree")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).with_name("public_release_manifest.txt"),
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = export_release(
        args.source,
        args.destination,
        args.manifest,
        refresh=args.refresh,
        dry_run=args.dry_run,
    )
    for finding in result.findings:
        print(f"BLOCKED {finding.path}: {finding.rule}")
    print(f"copy={len(result.copied)} remove={len(result.removed)} findings={len(result.findings)}")
    return 1 if result.findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
