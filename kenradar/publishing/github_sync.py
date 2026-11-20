from __future__ import annotations

import logging
import os
from contextlib import contextmanager
import hashlib
import re
import shutil
import stat
import subprocess
import tempfile
import time
import uuid

logger = logging.getLogger(__name__)
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
    _last_sync_time: float = 0
    DEFAULT_DEBOUNCE_SECONDS: int = 300

    SENSITIVE_PATTERNS = (
        re.compile(r"(^|/)hermes-private/", re.IGNORECASE),
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

    TRANSIENT_PUSH_PATTERNS = (
        re.compile(r"Empty reply from server", re.IGNORECASE),
        re.compile(r"Bad packet length", re.IGNORECASE),
        re.compile(r"Connection corrupted", re.IGNORECASE),
        re.compile(r"unexpected disconnect", re.IGNORECASE),
        re.compile(r"remote end hung up unexpectedly", re.IGNORECASE),
        re.compile(r"Connection reset", re.IGNORECASE),
        re.compile(r"Connection timed out", re.IGNORECASE),
        re.compile(r"Operation timed out", re.IGNORECASE),
        re.compile(r"Could not resolve hostname", re.IGNORECASE),
        re.compile(r"Network is unreachable", re.IGNORECASE),
        re.compile(r"unexpected eof while reading", re.IGNORECASE),
        re.compile(r"TLS connect error", re.IGNORECASE),
        re.compile(r"Internal Server Error", re.IGNORECASE),
        re.compile(r"HTTP[^\n]*\b50[234]\b", re.IGNORECASE),
    )

    def __init__(self, config: AppConfig):
        self.config = config
        default_repo = "./data/github-pages"
        self.repo_dir = config.resolve_path(str(config.get("publishing.github_sync.repo_dir", default_repo) or default_repo)).resolve()

    def sync(self, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
        enabled = bool(self.config.get("publishing.github_sync.enabled", False))
        if not enabled and not dry_run:
            return {"ok": True, "enabled": False, "dry_run": dry_run, "message": "GitHub 同步未启用", "files": []}
        now = time.time()
        elapsed = now - self._last_sync_time
        if not force and elapsed < self.DEFAULT_DEBOUNCE_SECONDS:
            logger.info("GitHub sync debounced (%.0fs since last sync, threshold %ds)", elapsed, self.DEFAULT_DEBOUNCE_SECONDS)
            return {"ok": True, "status": "debounced", "elapsed_seconds": elapsed}
        self._last_sync_time = now
        with self._repo_lock():
            self._ensure_git_repo()
            candidates = self.collect_candidates()
            deleted_files = self._deleted_allowed_files()
            if not candidates and not deleted_files:
                return {"ok": True, "enabled": enabled, "dry_run": dry_run, "message": "没有需要同步的文件", "files": []}

            rel_files = sorted({*[self._rel(candidate.path) for candidate in candidates], *deleted_files})
            self._guard_sensitive_files(rel_files, candidates)
            changed_files = self._changed_files(rel_files)
            if not changed_files:
                pushed = bool(not dry_run and self.config.get('publishing.github_sync.auto_push',False))
                if pushed:
                    # A previous commit may exist after a transient failed push.
                    self._guard_outgoing_scope()
                    self._run_git_push_with_retry()
                return {"ok": True, "enabled": enabled, "dry_run": dry_run, "message": "没有需要同步的文件", "files": rel_files,
                        'pushed':pushed,'committed':False}

            if dry_run:
                return {
                    "ok": True,
                    "enabled": enabled,
                    "dry_run": True,
                    "message": f"将同步 {len(changed_files)} 个文件",
                    "files": changed_files,
                }

            for batch in self._path_batches(changed_files):
                self._run_git(["add", "--", *batch])
            commit_created = False
            if bool(self.config.get("publishing.github_sync.auto_commit", False)):
                message = self._commit_message()
                if self._has_staged_changes():
                    self._guard_staged_snapshot()
                    self._run_git(["commit", "-m", message])
                    commit_created = True
            if bool(self.config.get("publishing.github_sync.auto_push", False)):
                self._guard_outgoing_scope()
                self._run_git_push_with_retry()
            return {
                "ok": True,
                "enabled": enabled,
                "dry_run": False,
                "message": "GitHub 同步完成",
                "files": changed_files,
                "commit_created": commit_created,
                "pushed": bool(self.config.get("publishing.github_sync.auto_push", False)),
            }

    def sync_single_article(self, article_path: Path, title: str = "") -> dict[str, Any]:
        """Project one rendered article onto fresh origin, never push local ancestry.

        Keep the source checkout/index untouched. Retain failed projections for diagnosis.
        """
        import copy
        import html
        from urllib.parse import quote

        if not self.config.get('publishing.github_sync.enabled', False):
            return {'ok': True, 'enabled': False, 'pushed': False}
        if not self.config.get('publishing.github_sync.auto_commit', False) or not self.config.get('publishing.github_sync.auto_push', False):
            raise GithubSyncError('PUBLICATION_SCOPE: single article requires commit/push authorization')
        article_path = Path(article_path).resolve()
        rel = self._rel(article_path)
        if not rel.startswith('notes/') or article_path.suffix != '.html' or article_path.name == 'index.html':
            raise GithubSyncError('PUBLICATION_SCOPE: expected one note HTML article')
        author_index = str(Path(rel).parent.as_posix()) + '/index.html'
        scope = [rel, author_index, 'index.html']
        if any(not self._scope_allows(p) for p in scope):
            raise GithubSyncError('PUBLICATION_SCOPE: single article outside configured scope')
        article = article_path.read_bytes()
        self._guard_sensitive_files([rel], [SyncCandidate(article_path, 'single_article')])
        with self._repo_lock():
            branch = str(self.config.get('publishing.github_sync.branch', 'gh-pages'))
            origin = self._run_git(['remote', 'get-url', 'origin']).stdout.strip()
            projection = self.repo_dir.parent / 'publication-projections' / uuid.uuid4().hex
            projection.parent.mkdir(parents=True, exist_ok=True)
            self._run_git(['clone', '--no-hardlinks', '--no-checkout', str(self.repo_dir), str(projection)])
            raw = copy.deepcopy(self.config.raw)
            raw.setdefault('publishing', {}).setdefault('github_sync', {}).update(repo_dir=str(projection), allowed_paths=scope, branch=branch)
            raw['publishing'].setdefault('github_pages', {}).update(output_dir=str(projection), preserve_historical_pages=True)
            isolated = GithubSyncManager(AppConfig(raw, self.config.path))
            isolated._run_git(['remote', 'set-url', 'origin', origin])
            isolated._run_git(['fetch', '--no-tags', 'origin', branch])
            baseline = isolated._run_git(['rev-parse', 'FETCH_HEAD']).stdout.strip()
            isolated._run_git(['checkout', '-b', 'single-article', baseline])
            isolated._run_git(['config', 'branch.single-article.remote', 'origin'])
            isolated._run_git(['config', 'branch.single-article.merge', f'refs/heads/{branch}'])
            isolated._run_git(['config', 'push.default', 'upstream'])
            for field, fmt in [('user.name', '%an'), ('user.email', '%ae')]:
                value = self._run_git(['log', '-1', '--format=' + fmt]).stdout.strip()
                isolated._run_git(['config', field, value])
            target = projection / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(article)
            label = html.escape(title or article_path.stem)
            for index, href in [('index.html', quote(rel)), (author_index, quote(article_path.name))]:
                path = projection / index
                before = path.read_bytes().decode('utf-8') if path.exists() else '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>KenRadar</title><body><main></main></body></html>'
                if rel not in self._canonical_index_links(before, index):
                    entry = f'<section class="single-note"><a href="{html.escape(href, quote=True)}">{label}</a></section>'
                    marker = '</main>' if '</main>' in before else '</body>'
                    if marker not in before:
                        raise GithubSyncError('PUBLICATION_SCOPE: index lacks safe insertion point')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(before.replace(marker, entry + marker, 1).encode('utf-8'))
            # Explicit candidates only; no catalog, asset, deletion or other note writes.
            candidates = [SyncCandidate(projection / p, 'single_article') for p in scope]
            isolated._guard_sensitive_files(scope, candidates)
            isolated._run_git(['add', '--', *scope])
            if isolated._has_staged_changes():
                isolated._guard_staged_snapshot()
                isolated._run_git(['commit', '-m', self._commit_message()])
            isolated._guard_outgoing_scope()
            isolated._run_git_push_with_retry()
            commit = isolated._run_git(['rev-parse', 'HEAD']).stdout.strip()
            remote = isolated._run_git(['ls-remote', 'origin', f'refs/heads/{branch}']).stdout.split()[0]
            if remote != commit:
                raise GithubSyncError('PUBLICATION_SCOPE: remote commit verification failed')
            blob = isolated._run_git(['rev-parse', f'{remote}:{rel}']).stdout.strip()
            receipt = {'ok': True, 'enabled': True, 'pushed': True, 'files': scope,
                    'message': '单篇隔离投影发布完成', 'projection_dir': str(projection),
                    'baseline': baseline, 'commit': commit, 'article_blob': blob,
                    'artifact_sha256': hashlib.sha256(isolated._run_git(['show', f'{remote}:{rel}'], binary=True).stdout).hexdigest(),
                    'source_sha256': hashlib.sha256(article).hexdigest()}
            try:
                self._remove_projection(projection)
            except OSError:
                receipt['projection_removed'] = False
                logger.warning("Verified publication but could not remove %s", projection, exc_info=True)
            else:
                receipt['projection_removed'] = True
            return receipt

    def _remove_projection(self, projection: Path) -> None:
        root = self.repo_dir.parent / 'publication-projections'
        if (projection.resolve() != projection or root.resolve() != root
                or projection.parent != root or not re.fullmatch('[a-f0-9]{32}', projection.name)):
            raise OSError(f"Unexpected projection path: {projection}")

        def retry_readonly(func, path, exc_info):
            if os.name != 'nt' or not isinstance(exc_info[1], PermissionError):
                raise exc_info[1]
            os.chmod(path, stat.S_IWRITE)
            func(path)

        shutil.rmtree(projection, onerror=retry_readonly)

    def collect_candidates(self) -> list[SyncCandidate]:
        from kenradar.integrations.privacy import artifact_privacy_snapshot
        with artifact_privacy_snapshot(self.config):
            return self._collect_candidates_snapshot()

    def _collect_candidates_snapshot(self) -> list[SyncCandidate]:
        candidates: list[SyncCandidate] = []
        if bool(self.config.get("publishing.github_sync.include_html_docs", True)):
            output_dir = self.config.resolve_path(str(self.config.get("publishing.github_pages.output_dir", "./data/github-pages") or "./data/github-pages"))
            candidates.extend(self._walk_allowed(output_dir, {".html", ".css", ".js", ".json", ".xml"}, "html_docs"))
        if bool(self.config.get("publishing.github_sync.include_markdown_notes", False)):
            note_candidates = self._walk_allowed(summary_dir(self.config), {".md"}, "markdown_notes")
            if not bool(self.config.get("publishing.github_sync.include_transcripts", False)):
                note_candidates = [candidate for candidate in note_candidates if not _markdown_contains_transcript(candidate.path)]
            candidates.extend(note_candidates)
        if bool(self.config.get("publishing.github_sync.include_briefs", False)):
            candidates.extend(self._walk_allowed(brief_dir(self.config), {".md"}, "briefs"))
        return sorted(_dedupe_candidates(candidates), key=lambda item: item.path.as_posix())

    def _deleted_allowed_files(self) -> list[str]:
        if self.config.get('publishing.github_pages.preserve_historical_pages',False):
            return []
        roots: list[tuple[str, set[str]]] = []
        if bool(self.config.get("publishing.github_sync.include_html_docs", True)):
            output_dir = self.config.resolve_path(str(self.config.get("publishing.github_pages.output_dir", "./data/github-pages") or "./data/github-pages"))
            roots.append((self._rel(output_dir), {".html", ".css", ".js", ".json", ".xml"}))
        if bool(self.config.get("publishing.github_sync.include_markdown_notes", False)):
            roots.append((self._rel(summary_dir(self.config)), {".md"}))
        if bool(self.config.get("publishing.github_sync.include_briefs", False)):
            roots.append((self._rel(brief_dir(self.config)), {".md"}))
        if not roots:
            return []
        result = self._run_git(["ls-files", "--deleted", "-z", "--", *[root for root, _ in roots]])
        deleted: list[str] = []
        for path in result.stdout.split("\0"):
            if not path:
                continue
            suffix = Path(path).suffix.lower()
            if any(
                (root in {"", "."} or path == root or path.startswith(root.rstrip("/") + "/"))
                and suffix in suffixes
                for root, suffixes in roots
            ):
                deleted.append(path)
        return sorted(set(deleted))

    def status_summary(self) -> dict[str, Any]:
        output_dir = self.config.resolve_path(str(self.config.get("publishing.github_pages.output_dir", "./data/github-pages") or "./data/github-pages"))
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

    def _scope_allows(self, rel: str) -> bool:
        from fnmatch import translate
        patterns = self.config.get('publishing.github_sync.allowed_paths', None)
        if patterns is None:
            return True
        if not isinstance(patterns, list):
            raise GithubSyncError('PUBLICATION_SCOPE: invalid allowed_paths')
        key = tuple(patterns)
        cached = getattr(self, '_scope_matchers', None)
        if cached is None or cached[0] != key:
            if any(not isinstance(p,str) or p.startswith(('/','\\')) or '..' in Path(p).parts for p in patterns):
                raise GithubSyncError('PUBLICATION_SCOPE: invalid allowed_paths')
            exact = {p for p in patterns if not any(c in p for c in '*?[')}
            wildcards = tuple(re.compile(translate(p)) for p in patterns if p not in exact)
            cached = self._scope_matchers = (key, exact, wildcards)
        return rel in cached[1] or any(pattern.match(rel) for pattern in cached[2])

    def _guard_snapshot_blob(self, path: str, ref: str) -> None:
        from kenradar.integrations.privacy import private_artifact
        if any(pattern.search(path) for pattern in self.SENSITIVE_PATTERNS) or private_artifact(self.repo_dir / path, self.config):
            raise GithubSyncError('SENSITIVE_PUBLICATION: private/sensitive artifact in Git snapshot')
        if not self._scope_allows(path):
            raise GithubSyncError('PUBLICATION_SCOPE: Git snapshot contains unrelated paths')
        text = self._run_git(['show', f'{ref}:{path}']).stdout
        if any(pattern.search(text) for pattern in self.SECRET_TEXT_PATTERNS) or re.search(r'hermes_private\s*[\"\x27]?\s*[:=]\s*(true|1)', text, re.I):
            raise GithubSyncError('SENSITIVE_PUBLICATION: private marker or credential in Git snapshot')

    def _guard_staged_snapshot(self) -> None:
        from kenradar.integrations.privacy import artifact_privacy_snapshot
        with artifact_privacy_snapshot(self.config):
            self._guard_staged_policy_snapshot()

    def _guard_staged_policy_snapshot(self) -> None:
        # Commit includes the entire index, not just candidates staged by us.
        paths = self._run_git(['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z']).stdout
        for path in filter(None, paths.split('\0')):
            self._guard_snapshot_blob(path, '')

    def _guard_outgoing_scope(self) -> None:
        from kenradar.integrations.privacy import artifact_privacy_snapshot
        with artifact_privacy_snapshot(self.config):
            self._guard_outgoing_policy_snapshot()

    def _guard_outgoing_policy_snapshot(self) -> None:
        branch = str(self.config.get('publishing.github_sync.branch','gh-pages'))
        refs = self._run_git(['ls-remote','origin',f'refs/heads/{branch}']).stdout.strip().split()
        if not refs or not re.fullmatch(r'[0-9a-f]{40,64}', refs[0]):
            raise GithubSyncError('PUBLICATION_SCOPE: remote baseline unavailable')
        remote = refs[0]
        # ls-remote advertises IDs without downloading their objects. A commit
        # published by another checkout may therefore be absent locally.
        if self._run_git(['cat-file', '-e', f'{remote}^{{commit}}'], check=False).returncode:
            self._run_git(['fetch', '--no-tags', 'origin', remote])
            if self._run_git(['cat-file', '-e', f'{remote}^{{commit}}'], check=False).returncode:
                raise GithubSyncError('PUBLICATION_SCOPE: fetched remote baseline unavailable')
        paths = [p for p in self._run_git(['diff','--name-only','-z',remote,'HEAD']).stdout.split('\0') if p]
        if any(not self._scope_allows(p) for p in paths):
            raise GithubSyncError('PUBLICATION_SCOPE: outgoing commits contain unrelated paths; scoped repair required')
        # Net diffs hide add-then-remove leaks. Audit each outgoing commit's
        # actual blobs, even with no scope/history configuration.
        commits = self._run_git(['rev-list', '--reverse', f'{remote}..HEAD']).stdout.split()
        for commit in commits:
            changed = self._run_git(['diff-tree', '--no-commit-id', '-m', '-r', '--name-only', '--diff-filter=ACMR', '-z', commit]).stdout
            for path in set(filter(None, changed.split('\0'))):
                self._guard_snapshot_blob(path, commit)
        if not self.config.get('publishing.github_pages.preserve_historical_pages',False):
            return
        deleted = self._run_git(['diff','--diff-filter=D','--name-only','-z',remote,'HEAD']).stdout
        if deleted.strip('\0'):
            raise GithubSyncError('HISTORY_FILE_LOSS: outgoing commit deletes historical artifacts')
        for path in paths:
            if not path.endswith('/index.html') and path != 'index.html':
                continue
            prior = self._run_git(['show',f'{remote}:{path}'],check=False)
            if prior.returncode:
                continue  # A genuinely new index has no historical links to preserve.
            current = self._run_git(['show',f'HEAD:{path}']).stdout
            if not self._canonical_index_links(prior.stdout,path).issubset(self._canonical_index_links(current,path)):
                raise GithubSyncError(f'HISTORY_LINK_LOSS: outgoing index drops historical links: {path}')

    @staticmethod
    def _canonical_index_links(text: str, path: str) -> set[str]:
        import posixpath
        from html.parser import HTMLParser
        from urllib.parse import unquote, urlsplit
        links = set()
        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag != 'a':
                    return
                href = dict(attrs).get('href') or ''
                target = urlsplit(href)
                if target.scheme or target.netloc or not target.path.lower().endswith('.html'):
                    return
                links.add(posixpath.normpath(posixpath.join(posixpath.dirname(path),unquote(target.path))))
        Parser(convert_charrefs=True).feed(text)
        return links

    def _walk_allowed(self, root: Path, suffixes: set[str], reason: str) -> list[SyncCandidate]:
        if not root.exists():
            return []
        from kenradar.integrations.privacy import private_artifact
        return [SyncCandidate(path, reason) for path in root.rglob("*") if path.is_file()
                and path.suffix.lower() in suffixes
                and (self.config.get('publishing.github_sync.allowed_paths',None) is None or self._scope_allows(self._rel(path)))
                and not private_artifact(path, self.config)]

    def _ensure_git_repo(self) -> None:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        if result.returncode != 0 or "true" not in (result.stdout or ""):
            raise GithubSyncError(f"不是 Git 仓库: {self.repo_dir}")

    def _guard_sensitive_files(self, rel_files: list[str], candidates: list[SyncCandidate]) -> None:
        from kenradar.integrations.privacy import artifact_privacy_snapshot
        with artifact_privacy_snapshot(self.config):
            self._guard_sensitive_policy_snapshot(rel_files, candidates)

    def _guard_sensitive_policy_snapshot(self, rel_files: list[str], candidates: list[SyncCandidate]) -> None:
        from kenradar.integrations.privacy import private_artifact
        blocked = [path for path in rel_files if any(pattern.search(path) for pattern in self.SENSITIVE_PATTERNS)]
        for candidate in candidates:
            if private_artifact(candidate.path, self.config):
                blocked.append(self._rel(candidate.path))
                continue
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
        changed: list[str] = []
        outputs = [self._run_git(["status", "--porcelain=v1", "-z", "--", *batch]).stdout
                   for batch in self._path_batches(rel_files)]
        records = "".join(outputs).split("\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            status = record[:2]
            path = record[3:] if len(record) > 3 else ""
            if ("R" in status or "C" in status) and index < len(records):
                changed.append(records[index])
                index += 1
            if path:
                changed.append(path)
        return sorted(set(changed))

    @staticmethod
    def _path_batches(paths: list[str]):
        # Leave ample room under Windows' 32767 UTF-16 command-line limit.
        batch, size = [], 0
        for path in paths:
            cost = len(path.encode("utf-16-le")) // 2 + 4
            if batch and size + cost > 12000:
                yield batch
                batch, size = [], 0
            batch.append(path)
            size += cost
        if batch:
            yield batch

    def _has_staged_changes(self) -> bool:
        result = self._run_git(["diff", "--cached", "--quiet"], check=False)
        return result.returncode == 1

    def _commit_message(self) -> str:
        template = str(self.config.get("publishing.github_sync.commit_message_template", "chore: publish KenRadar notes {timestamp}") or "")
        return template.format(timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def _rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.repo_dir).as_posix()

    def _run_git(self, args: list[str], check: bool = True, *, binary: bool = False) -> subprocess.CompletedProcess:
        import os
        executable = str(self.config.get('publishing.github_sync.git_executable', 'git') or 'git')
        env = dict(os.environ)
        command = [executable]
        if executable != 'git':
            root = Path(executable).parent.parent
            env['PATH'] = os.pathsep.join([str(root / 'bin'), str(root / 'usr/bin'), str(root / 'cmd'), env.get('PATH','')])
            env['SHELL'] = str(root / 'usr/bin/sh.exe')
            command += ['-c', 'credential.helper=', '-c', 'credential.helper=manager',
                        '-c', 'http.sslBackend=openssl', '-c', 'http.sslVerify=true']
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
        attempts = 3 if args and args[0] in {'ls-remote', 'fetch'} else 1
        for attempt in range(attempts):
            try:
                result = subprocess.run(
                    [*command, *args],
                    cwd=self.repo_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=not binary,
                    encoding=None if binary else "utf-8",
                    env=env,
                    timeout=min(180, max(10, int(self.config.get('publishing.github_sync.git_timeout_seconds', 120)))),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                if attempt + 1 >= attempts:
                    raise
                time.sleep(1 + attempt)
                continue
            error_text = result.stderr.decode('utf-8', errors='replace') if binary else result.stderr
            if result.returncode == 0 or not self._is_transient_push_error(error_text or '') or attempt + 1 >= attempts:
                break
            time.sleep(1 + attempt)
        if check and result.returncode != 0:
            raise GithubSyncError(f"git {' '.join(args)} 失败: {result.stderr.strip() or result.stdout.strip()}")
        return result

    def _run_git_push_with_retry(self) -> None:
        attempts = max(1, int(self.config.get("publishing.github_sync.push_retry_count", 3) or 3))
        delay = max(0.0, float(self.config.get("publishing.github_sync.push_retry_delay", 5) or 5))
        last_error = ""
        for attempt in range(1, attempts + 1):
            result = self._run_git(["push"], check=False)
            if result.returncode == 0:
                if attempt > 1:
                    logger.info("GitHub sync push succeeded after retry: attempt=%s/%s", attempt, attempts)
                return
            last_error = result.stderr.strip() or result.stdout.strip()
            if attempt >= attempts or not self._is_transient_push_error(last_error):
                raise GithubSyncError(f"git push 失败: {last_error}")
            sleep_seconds = delay * (2 ** (attempt - 1))
            logger.warning(
                "GitHub sync push transient failure, retrying in %.1fs: attempt=%s/%s error=%s",
                sleep_seconds,
                attempt,
                attempts,
                last_error[:500],
            )
            time.sleep(sleep_seconds)
        raise GithubSyncError(f"git push 失败: {last_error}")

    @classmethod
    def _is_transient_push_error(cls, error: str) -> bool:
        return any(pattern.search(error or "") for pattern in cls.TRANSIENT_PUSH_PATTERNS)

    @contextmanager
    def _repo_lock(self):
        repo_key = hashlib.sha256(str(self.repo_dir).encode("utf-8")).hexdigest()[:16]
        lock_path = Path(tempfile.gettempdir()) / f"kenradar-github-sync-{repo_key}.lock"
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
                    from kenradar.core import file_lock as fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                except Exception as exc:
                    raise GithubSyncError(f"无法获取 Git 同步锁: {lock_path} ({exc})") from exc
                try:
                    yield
                finally:
                    from kenradar.core import file_lock as fcntl

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
    # scandir reuses Windows directory metadata instead of issuing multiple
    # stat calls per file; visit each HTML exactly once.
    if patterns == ("*.html", "**/*.html"):
        latest = 0.0
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.name.lower().endswith(".html") and entry.is_file(follow_symlinks=False):
                            try:
                                latest = max(latest, entry.stat(follow_symlinks=False).st_mtime)
                            except FileNotFoundError:
                                pass  # A concurrent publisher may replace a file.
            except FileNotFoundError:
                pass
        return latest
    if not root.exists():
        return 0
    return max((path.stat().st_mtime for pattern in patterns
                for path in root.glob(pattern) if path.is_file()), default=0)



def _markdown_contains_transcript(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return any(
        heading in text
        for heading in ("## 三、转录原文", "三、转录原文", "## 四、视频原始转录", "四、视频原始转录", "## 三、视频原稿", "三、视频原稿")
    )
