from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


MAX_TEXT_BYTES = 2 * 1024 * 1024
PLACEHOLDERS = {"", "CHANGE_ME", "CHANGEME", "EXAMPLE", "example", "test", "disabled"}
FORBIDDEN_NAMES = {
    ".git",
    ".codex",
    ".agent",
    ".opencode",
    ".playwright-mcp",
    ".playwright-cli",
    ".superpowers",
    ".worktrees",
    "node_modules",
    "__pycache__",
    "kenradar.egg-info",
}
FORBIDDEN_FILE_PATTERNS = (
    re.compile(r"(^|/)\.env($|\.)"),
    re.compile(r"(^|/)config/config\.ya?ml$", re.IGNORECASE),
    re.compile(r"cookie", re.IGNORECASE),
    re.compile(r"\.(?:log|mp4|m4a|mp3|wav|mov|avi|mkv|webm|db|sqlite|dump|sql)$", re.IGNORECASE),
    re.compile(r"\.transcript\.(?:txt|json)$", re.IGNORECASE),
    re.compile(r"(?:^|/)(?:data|screenshots)(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:\.bak(?:[.-]|$)|backup\.(?:zip|tar|tgz|gz)$)", re.IGNORECASE),
)
SECRET_ASSIGNMENT = re.compile(
    r"(?m)^[ \t]*(?:[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)|FEISHU_WEBHOOK_URL)"
    r"[ \t]*=[ \t]*([^\s#]+)"
)
CREDENTIAL_URL = re.compile(r"postgres(?:ql)?://([^:/\s]+):([^@\s]+)@", re.IGNORECASE)
BEARER = re.compile(r"(?i)Bearer\s+([A-Za-z0-9._~+/=-]{16,})")
WEBHOOK = re.compile(r"open-apis/bot/v2/hook/([A-Za-z0-9_-]{12,})", re.IGNORECASE)
HOME_PATH = re.compile(r"/(?:home|Users)/([^/\s]+)/")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Z0-9.-]+\.[A-Z]{2,}\b")
PUBLIC_CONTACT_EMAILS = {"support@f2.wiki"}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    rule: str
    excerpt: str = ""


def load_manifest(path: Path) -> tuple[str, ...]:
    entries: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        pure = PurePosixPath(entry)
        if pure.is_absolute() or ".." in pure.parts or entry.startswith("~"):
            raise ValueError(f"unsafe manifest path: {entry}")
        entries.append(entry.rstrip("/") + ("/" if entry.endswith("/") else ""))
    if len(entries) != len(set(entries)):
        raise ValueError("duplicate manifest entries")
    return tuple(entries)


def audit_tree(root: Path) -> list[Finding]:
    root = root.resolve()
    findings: set[Finding] = set()
    if not root.is_dir():
        return [Finding(".", "missing_root")]
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            findings.add(Finding(relative, "symlink"))
            continue
        if any(part in FORBIDDEN_NAMES for part in path.relative_to(root).parts):
            blocked = next(part for part in path.relative_to(root).parts if part in FORBIDDEN_NAMES)
            prefix = relative.split(blocked, 1)[0] + blocked
            findings.add(Finding(prefix, "forbidden_path"))
            continue
        if path.is_dir():
            continue
        if relative.endswith(".env.example"):
            path_findings = _audit_text(path, relative)
        elif any(pattern.search(relative) for pattern in FORBIDDEN_FILE_PATTERNS):
            findings.add(Finding(relative, "forbidden_path"))
            continue
        else:
            path_findings = _audit_text(path, relative)
        findings.update(path_findings)
    return sorted(findings)


def _audit_text(path: Path, relative: str) -> list[Finding]:
    try:
        if path.stat().st_size > MAX_TEXT_BYTES:
            return [Finding(relative, "oversized_file")]
        raw = path.read_bytes()
        if b"\0" in raw[:4096]:
            return []
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for match in SECRET_ASSIGNMENT.finditer(text):
        value = match.group(1).strip("'\"")
        if not _is_placeholder(value):
            findings.append(Finding(relative, "secret_assignment", "<redacted>"))
    for match in CREDENTIAL_URL.finditer(text):
        if not _is_placeholder(match.group(2)):
            findings.append(Finding(relative, "credential_url", "postgresql://<redacted>"))
    for rule, pattern in (("bearer_token", BEARER), ("webhook_token", WEBHOOK)):
        if pattern.search(text):
            findings.append(Finding(relative, rule, "<redacted>"))
    if HOME_PATH.search(text):
        findings.append(Finding(relative, "personal_absolute_path", "<absolute-path-redacted>"))
    emails = {match.group(0).lower() for match in EMAIL.finditer(text)}
    if emails - PUBLIC_CONTACT_EMAILS:
        findings.append(Finding(relative, "personal_email", "<redacted@example>"))
    return findings


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().strip("'\"")
    return (
        normalized in PLACEHOLDERS
        or "CHANGE_ME" in normalized
        or normalized.startswith("MY_")
        or "${" in normalized
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a KenRadar public release tree")
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    findings = audit_tree(Path(args.root))
    for item in findings:
        print(f"{item.path}: {item.rule}: {item.excerpt}".rstrip())
    if findings:
        print(f"Public release audit failed: {len(findings)} finding(s)")
        return 1
    print("Public release audit passed: 0 findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
