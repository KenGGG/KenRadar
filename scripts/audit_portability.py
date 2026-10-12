"""Read-only P0 inventory. Never reads .env or runtime records."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path


def inventory(root: Path) -> dict:
    findings = []
    sql = []
    methods = {}
    routes = []
    patterns = ("%s", "::jsonb", "INTERVAL", "ILIKE", "SKIP LOCKED", "NOW()",
                "ANY(", "to_regclass", "psycopg", "fcntl", "/tmp/", "/proc/", "/home/")
    for folder in ("kenradar", "scripts", "tests"):
        for path in sorted((root / folder).rglob("*")):
            if path.suffix not in {".py", ".sh", ".ps1", ".tsx", ".ts", ".json"}:
                continue
            if any(p in {"dist", "node_modules", "__pycache__"} for p in path.parts):
                continue
            source = path.read_text(encoding="utf-8")
            relative = path.relative_to(root).as_posix()
            for number, line in enumerate(source.splitlines(), 1):
                hits = [p for p in patterns if p in line]
                if hits:
                    findings.append({"path": relative, "line": number, "patterns": hits})
                if "/api/" in line or "/health/" in line:
                    routes.append({"path": relative, "line": number})
            if path.suffix == ".py":
                tree = ast.parse(source)
                if "/storage/" in relative:
                    methods[relative] = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
                for n in ast.walk(tree):
                    if isinstance(n, ast.Constant) and isinstance(n.value, str):
                        value = n.value.strip()
                        if any(value.upper().startswith(p) for p in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE ", "ALTER ", "WITH ", "DROP ")):
                            sql.append({"path": relative, "line": n.lineno, "sql": value})
    return {"head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            "worktree": subprocess.check_output(["git", "status", "--short"], cwd=root, text=True).splitlines(),
            "portability": findings, "sql": sql, "repository_methods": methods, "route_callsites": routes}


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    output = root / "data/test-migration/p0"
    if (output / "preexisting.patch").exists():
        raise SystemExit("P0 原始工作区快照已存在，拒绝覆盖；后续审计请使用 inventory() 写入新的阶段目录")
    output.mkdir(parents=True, exist_ok=True)
    report = inventory(root)
    (output / "inventory.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    patch = subprocess.check_output(["git", "diff", "--binary"], cwd=root)
    (output / "preexisting.patch").write_bytes(patch)
    untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=root, text=True).splitlines()
    hashes = {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in untracked if (root / p).is_file()}
    (output / "untracked-hashes.json").write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    print(f"{len(report['sql'])} SQL literals; {len(report['portability'])} portability callsites; {output}")
