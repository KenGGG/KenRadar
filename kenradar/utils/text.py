from __future__ import annotations

import re


def sanitize_filename(value: str, fallback: str = "untitled") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", value.strip())
    cleaned = cleaned.strip("._")
    return cleaned[:120] or fallback


def truncate_filename_bytes(value: str, limit: int = 180, fallback: str = "untitled") -> str:
    cleaned = str(value or "").strip("._") or fallback
    if len(cleaned.encode("utf-8")) <= limit:
        return cleaned

    result: list[str] = []
    used = 0
    for char in cleaned:
        char_len = len(char.encode("utf-8"))
        if used + char_len > limit:
            break
        result.append(char)
        used += char_len
    return "".join(result).strip("._") or fallback


def truncate_text(value: str, limit: int = 400) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "..."
