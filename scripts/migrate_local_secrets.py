from __future__ import annotations

import os
import secrets
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "config.yaml"
ENV_FILE = ROOT / ".env"
COOKIE_FILE = ROOT / "config" / "douyin.cookies.yaml"


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def quote_env(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dedupe_bloggers(rows: list[object]) -> list[object]:
    seen: set[tuple[str, str]] = set()
    result: list[object] = []
    for row in rows:
        if not isinstance(row, dict):
            result.append(row)
            continue
        platform = str(row.get("platform") or "douyin")
        identity = str(row.get("sec_uid") or row.get("url") or row.get("name") or "").strip()
        key = (platform, identity)
        if identity and key in seen:
            continue
        if identity:
            seen.add(key)
        result.append(row)
    return result


def main() -> None:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    env = parse_env(ENV_FILE)
    app = raw.setdefault("app", {})
    feishu = raw.setdefault("notification", {}).setdefault("channels", {}).setdefault("feishu", {})

    env["DATABASE_URL"] = env.get("DATABASE_URL") or str(app.get("database_url") or "")
    env["FEISHU_WEBHOOK_URL"] = env.get("FEISHU_WEBHOOK_URL") or str(feishu.get("webhook_url") or "")
    env["KENRADAR_WEB_PASSWORD"] = env.get("KENRADAR_WEB_PASSWORD") or secrets.token_urlsafe(24)
    env["DOUYIN_COOKIE_FILE"] = str(COOKIE_FILE)

    cookies = raw.pop("cookies", {}) or {}
    if cookies:
        COOKIE_FILE.write_text(yaml.safe_dump(cookies, allow_unicode=True, sort_keys=True), encoding="utf-8")
        os.chmod(COOKIE_FILE, 0o600)

    app["database_url"] = "${DATABASE_URL}"
    app["web_password"] = "${KENRADAR_WEB_PASSWORD}"
    app["douyin_cookie_file"] = "${DOUYIN_COOKIE_FILE}"
    feishu["webhook_url"] = "${FEISHU_WEBHOOK_URL}"
    raw["bloggers"] = dedupe_bloggers(raw.get("bloggers") or [])

    CONFIG.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ENV_FILE.write_text(
        "\n".join(f"{key}={quote_env(value)}" for key, value in sorted(env.items())) + "\n",
        encoding="utf-8",
    )
    os.chmod(CONFIG, 0o600)
    os.chmod(ENV_FILE, 0o600)
    for backup in CONFIG.parent.glob("*.bak*"):
        os.chmod(backup, 0o600)
    print(f"Secrets migrated. Web password is stored in {ENV_FILE}.")


if __name__ == "__main__":
    main()
