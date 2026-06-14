from __future__ import annotations

from contextlib import contextmanager
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.config import AppConfig
from kenradar.core.obsidian import brief_dir, obsidian_root, summary_dir
from kenradar.storage import create_database


class GithubSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class SyncCandidate:
    path: Path
    reason: str


class GithubSyncManager:
    SENSITIVE_PATTERNS = (
        re.compile(r"(^|/)\.env($|\.)"),
        re.compile(r"(^|/)config/config\.yaml$"),
        re.compile(r"cookie", re.IGNORECASE),
        re.compile(r"api[_-]?key", re.IGNORECASE),
        re.compile(r"secret", re.IGNORECASE),
        re.compile(r"password", re.IGNORECASE),
        re.compile(r"\.(mp4|m4a|mp3|wav|mov|avi|mkv|webm)$", re.IGNORECASE),
        re.compile(r"\.transcript\.(txt|json)$", re.IGNORECASE),
        re.compile(r"\.(db|sqlite|dump|sql)$", re.IGNORECASE),
        re.compile(r"(^|/)data/Downloaded/"),
        re.compile(r"(^|/)data/logs/"),
        re.compile(r"\.log$", re.IGNORECASE),
    )

    SECRET_TEXT_PATTERNS = (
        re.compile(r"AGNES_API_KEY\s*=", re.IGNORECASE),
        re.compile(r"FEISHU_WEBHOOK_URL\s*=", re.IGNORECASE),
        re.compile(r"DATABASE_URL\s*=", re.IGNORECASE),
        re.compile(r"postgresql://[^/\s:]+:[^@\s]+@", re.IGNORECASE),
        re.compile(r"open-apis/bot/v2/hook/[A-Za-z0-9_-]+"),
    )

    def __init__(self, config: AppConfig):
        self.config = config
        self.repo_dir = config.resolve_path(str(config.get("publishing.github_sync.repo_dir", ".") or ".")).resolve()

    def sync(self, dry_run: bool = False) -> dict[str, Any]:
        enabled = bool(self.config.get("publishing.github_sync.enabled", False))
        if not enabled and not dry_run:
            return {"ok": True, "enabled": False, "dry_run": dry_run, "message": "GitHub 同步未启用", "files": []}
        with self._repo_lock():
            self._ensure_git_repo()
            candidates = self.collect_candidates()
            if not candidates:
                return {"ok": True, "enabled": enabled, "dry_run": dry_run, "message": "没有需要同步的文件", "files": []}

            rel_files = [self._rel(candidate.path) for candidate in candidates]
            self._guard_sensitive_files(rel_files, candidates)
            changed_files = self._changed_files(rel_files)
            if not changed_files:
                return {"ok": True, "enabled": enabled, "dry_run": dry_run, "message": "没有需要同步的文件", "files": rel_files}

            if dry_run:
                return {
                    "ok": True,
                    "enabled": enabled,
                    "dry_run": True,
                    "message": f"将同步 {len(changed_files)} 个文件",
                    "files": changed_files,
                }

            self._run_git(["add", "--", *changed_files])
            commit_created = False
            if bool(self.config.get("publishing.github_sync.auto_commit", False)):
                message = self._commit_message()
                if self._has_staged_changes():
                    self._run_git(["commit", "-m", message])
                    commit_created = True
            if bool(self.config.get("publishing.github_sync.auto_push", False)):
                self._run_git(["push"])
            return {
                "ok": True,
                "enabled": enabled,
                "dry_run": False,
                "message": "GitHub 同步完成",
                "files": changed_files,
                "commit_created": commit_created,
                "pushed": bool(self.config.get("publishing.github_sync.auto_push", False)),
            }

    def collect_candidates(self) -> list[SyncCandidate]:
        candidates: list[SyncCandidate] = []
        if bool(self.config.get("publishing.github_sync.include_html_docs", True)):
            output_dir = self.config.resolve_path(str(self.config.get("publishing.github_pages.output_dir", "./docs") or "./docs"))
            candidates.extend(self._walk_allowed(output_dir, {".html", ".css", ".js", ".json", ".xml"}, "html_docs"))
        if bool(self.config.get("publishing.github_sync.include_markdown_notes", True)):
            note_candidates = self._walk_allowed(summary_dir(self.config), {".md"}, "markdown_notes")
            if not bool(self.config.get("publishing.github_sync.include_transcripts", True)):
                note_candidates = [candidate for candidate in note_candidates if not _markdown_contains_transcript(candidate.path)]
            candidates.extend(note_candidates)
        if bool(self.config.get("publishing.github_sync.include_briefs", True)):
            candidates.extend(self._walk_allowed(brief_dir(self.config), {".md"}, "briefs"))
        return sorted(_dedupe_candidates(candidates), key=lambda item: item.path.as_posix())

    def status_summary(self) -> dict[str, Any]:
        output_dir = self.config.resolve_path(str(self.config.get("publishing.github_pages.output_dir", "./docs") or "./docs"))
        latest_html = _latest_mtime(output_dir, ("*.html", "**/*.html"))
        log_path = obsidian_root(self.config) / "logs" / "github_sync_last.json"
        last_sync: dict[str, Any] = {}
        if log_path.exists():
            try:
                import json

                last_sync = json.loads(log_path.read_text(encoding="utf-8"))
            except Exception:
                last_sync = {}
        public_url = str(self.config.get("publishing.github_pages.public_base_url", "") or "").strip()
        return {
            "docs_exists": output_dir.exists(),
            "docs_path": str(output_dir),
            "latest_html_published_at": datetime.fromtimestamp(latest_html).strftime("%Y-%m-%d %H:%M:%S") if latest_html else "",
            "github_pages_enabled": bool(self.config.get("publishing.github_pages.enabled", False)),
            "github_pages_public_base_url_configured": bool(public_url and "${" not in public_url),
            "github_sync_enabled": bool(self.config.get("publishing.github_sync.enabled", False)),
            "github_sync_auto_commit": bool(self.config.get("publishing.github_sync.auto_commit", False)),
            "github_sync_auto_push": bool(self.config.get("publishing.github_sync.auto_push", False)),
            "last_sync": last_sync,
        }

    def write_last_sync(self, result: dict[str, Any]) -> None:
        import json

        log_dir = obsidian_root(self.config) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        payload = {**result, "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        (log_dir / "github_sync_last.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _walk_allowed(self, root: Path, suffixes: set[str], reason: str) -> list[SyncCandidate]:
        if not root.exists():
            return []
        return [SyncCandidate(path, reason) for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes]

    def _ensure_git_repo(self) -> None:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0 or "true" not in (result.stdout or ""):
            raise GithubSyncError(f"不是 Git 仓库: {self.repo_dir}")

    def _guard_sensitive_files(self, rel_files: list[str], candidates: list[SyncCandidate]) -> None:
        blocked = [path for path in rel_files if any(pattern.search(path) for pattern in self.SENSITIVE_PATTERNS)]
        for candidate in candidates:
            if candidate.path.suffix.lower() not in {".md", ".html", ".json", ".xml"}:
                continue
            try:
                text = candidate.path.read_text(encoding="utf-8", errors="ignore")[:20000]
            except Exception:
                continue
            if any(pattern.search(text) for pattern in self.SECRET_TEXT_PATTERNS):
                blocked.append(self._rel(candidate.path))
        if blocked:
            raise GithubSyncError("检测到疑似敏感文件，已阻止同步: " + ", ".join(sorted(set(blocked))[:20]))

    def _changed_files(self, rel_files: list[str]) -> list[str]:
        result = self._run_git(["status", "--porcelain=v1", "-z", "--", *rel_files])
        changed: list[str] = []
        records = result.stdout.split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            status = record[:2]
            path = record[3:] if len(record) > 3 else ""
            if ("R" in status or "C" in status) and index < len(records):
                path = records[index]
                index += 1
            if path:
                changed.append(path)
        return sorted(set(changed))

    def _has_staged_changes(self) -> bool:
        result = self._run_git(["diff", "--cached", "--quiet"], check=False)
        return result.returncode == 1

    def _commit_message(self) -> str:
        template = str(self.config.get("publishing.github_sync.commit_message_template", "chore: publish KenRadar notes {timestamp}") or "")
        return template.format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.repo_dir).as_posix()

    def _run_git(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise GithubSyncError(f"git {' '.join(args)} 失败: {result.stderr.strip() or result.stdout.strip()}")
        return result

    @contextmanager
    def _repo_lock(self):
        lock_path = self.repo_dir / ".kenradar-github-sync.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        database = None
        owner = f"github-sync:{uuid.uuid4().hex}"
        if self.config.database_type == "postgresql":
            database = create_database(self.config)
            deadline = time.monotonic() + 60.0
            while not database.acquire_resource_lease("git:repo", owner, lease_seconds=900):
                if time.monotonic() >= deadline:
                    raise GithubSyncError("等待 GitHub 同步资源锁超时")
                time.sleep(0.5)
        try:
            with lock_path.open("a+", encoding="utf-8") as handle:
                try:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except Exception as exc:
                    raise GithubSyncError(f"无法获取 Git 同步锁: {lock_path} ({exc})") from exc
                try:
                    yield
                finally:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            if database is not None:
                database.release_resource_lease("git:repo", owner)


def _dedupe_candidates(candidates: list[SyncCandidate]) -> list[SyncCandidate]:
    seen: set[Path] = set()
    result: list[SyncCandidate] = []
    for candidate in candidates:
        resolved = candidate.path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(SyncCandidate(resolved, candidate.reason))
    return result


def _latest_mtime(root: Path, patterns: tuple[str, ...]) -> float:
    if not root.exists():
        return 0
    values: list[float] = []
    for pattern in patterns:
        values.extend(path.stat().st_mtime for path in root.glob(pattern) if path.is_file())
    return max(values) if values else 0


def _markdown_contains_transcript(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return any(
        heading in text
        for heading in ("## 四、视频原始转录", "四、视频原始转录", "## 三、视频原稿", "三、视频原稿")
    )
