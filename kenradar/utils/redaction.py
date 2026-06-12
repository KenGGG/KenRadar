from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


SENSITIVE_HEADER_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-feishu-signature",
    "x-lark-signature",
}


def redact_url(value: str) -> str:
    """Remove credentials, query strings and fragments before logging URLs."""
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    if not parsed.scheme or not parsed.netloc:
        return text
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = hostname + port
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in (headers or {}).items():
        redacted[str(key)] = "***" if str(key).lower() in SENSITIVE_HEADER_KEYS else value
    return redacted


def redact_secret(value: str, keep: int = 6) -> str:
    text = str(value or "")
    if len(text) <= keep * 2:
        return "***" if text else ""
    return f"{text[:keep]}...{text[-keep:]}"
