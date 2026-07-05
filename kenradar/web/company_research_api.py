from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.config import AppConfig

logger = logging.getLogger(__name__)


def _notebooklm_metadata_path(config: AppConfig) -> Path:
    return Path(config.data_dir) / "company_research" / "notebooklm_session.json"


def _read_notebooklm_metadata(config: AppConfig) -> dict[str, Any]:
    path = _notebooklm_metadata_path(config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("读取 NotebookLM 会话元数据失败: path=%s", path)
        return {}


def _write_notebooklm_metadata(config: AppConfig, payload: dict[str, Any]) -> None:
    path = _notebooklm_metadata_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_notebooklm_cli(args: list[str], *, timeout: int = 60, stdin_data: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "notebooklm", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        input=stdin_data,
    )


def _inspect_notebooklm_accounts() -> list[dict[str, Any]]:
    result = _run_notebooklm_cli(["auth", "inspect", "--browser", "chrome", "--json"], timeout=60)
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout or "{}")
            accounts = payload.get("accounts") or []
            return [
                {
                    "email": str(item.get("email") or ""),
                    "is_default": bool(item.get("is_default")),
                    "browser_profile": str(item.get("browser_profile") or ""),
                }
                for item in accounts
                if str(item.get("email") or "").strip()
            ]
        except Exception:
            pass
    return _extract_accounts_from_storage()


def _extract_accounts_from_storage() -> list[dict[str, Any]]:
    storage_path = Path("/data/ken/.notebooklm/profiles/default/storage_state.json")
    if not storage_path.exists():
        return []
    try:
        state = json.loads(storage_path.read_text(encoding="utf-8"))
        cookies = state.get("cookies") or []
        emails: list[str] = []
        for cookie in cookies:
            if cookie.get("name") == "ACCOUNT_CHOOSER":
                raw = str(cookie.get("value") or "")
                for segment in raw.replace("/", " ").split():
                    if "@" in segment and "." in segment:
                        email = segment.strip()
                        if email and email not in emails:
                            emails.append(email)
        return [
            {"email": email, "is_default": i == 0, "browser_profile": "Playwright (notebooklm login)"}
            for i, email in enumerate(emails)
        ]
    except Exception:
        logger.debug("Failed to extract accounts from storage_state.json", exc_info=True)
        return []


def _notebooklm_auth_check() -> dict[str, Any]:
    result = _run_notebooklm_cli(["auth", "check", "--test", "--json"], timeout=30)
    try:
        payload = json.loads(result.stdout or "{}")
    except Exception:
        payload = {}
    checks = payload.get("checks") or {}
    details = payload.get("details") or {}
    authenticated = payload.get("status") == "ok" and bool(checks.get("token_fetch"))
    cookie_count = len(details.get("cookies_found") or [])
    profile_dir = str(details.get("storage_path") or "")
    if profile_dir:
        profile_dir = str(Path(profile_dir).parent)
    auth_detail = f"token verified ({cookie_count} cookies)" if authenticated else str(details.get("error") or "token check failed")
    return {
        "ok": result.returncode == 0,
        "profile_dir": profile_dir,
        "authenticated": authenticated,
        "auth_detail": auth_detail,
    }


def company_notebooklm_status(config: AppConfig) -> dict[str, Any]:
    metadata = _read_notebooklm_metadata(config)
    auth = _notebooklm_auth_check()
    accounts: list[dict[str, Any]] = []
    inspect_error = ""
    try:
        accounts = _inspect_notebooklm_accounts()
    except Exception as exc:
        inspect_error = str(exc)
    recorded_email = str(metadata.get("account_email") or "").strip()
    if recorded_email and not any(a.get("email") == recorded_email for a in accounts):
        accounts.insert(0, {"email": recorded_email, "is_default": True, "browser_profile": "已记录"})
    return {
        "ok": True,
        "authenticated": auth["authenticated"],
        "auth_detail": auth["auth_detail"],
        "profile_dir": auth["profile_dir"],
        "current_account": recorded_email or (accounts[0]["email"] if accounts else ""),
        "last_login_at": str(metadata.get("logged_in_at") or ""),
        "browser": str(metadata.get("browser") or "chrome"),
        "accounts": accounts,
        "inspect_error": inspect_error,
    }


def company_notebooklm_relogin(config: AppConfig, account_email: str, browser: str = "chrome") -> dict[str, Any]:
    email = str(account_email or "").strip()
    if not email:
        raise ValueError("缺少 NotebookLM 账号邮箱")
    result = _run_notebooklm_cli(["login", "--browser-cookies", browser, "--account", email], timeout=120, stdin_data="y\n")
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "notebooklm login failed").strip())
    _write_notebooklm_metadata(
        config,
        {
            "account_email": email,
            "browser": browser,
            "logged_in_at": datetime.now().isoformat(timespec="seconds"),
        },
    )
    return company_notebooklm_status(config)
