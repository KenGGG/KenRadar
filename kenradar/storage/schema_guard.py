from __future__ import annotations

import platform
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from kenradar.storage.migrate import schema_status


def require_schema_current(config_path: str) -> dict[str, str | bool]:
    status = schema_status(config_path)
    if not bool(status.get("up_to_date")):
        current = str(status.get("current") or "<none>")
        head = str(status.get("head") or "<unknown>")
        raise RuntimeError(
            "数据库 schema 不是最新版本："
            f"current={current} head={head}；请先执行 "
            "`python -m kenradar --config config/config.yaml migrate`"
        )
    return status


def runtime_version(config_path: str) -> dict[str, Any]:
    try:
        app_version = version("kenradar")
    except PackageNotFoundError:
        app_version = "0.0.0+local"
    return {
        "name": "KenRadar",
        "version": app_version,
        "python": platform.python_version(),
        "schema": schema_status(config_path),
    }
