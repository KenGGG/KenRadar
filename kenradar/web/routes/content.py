"""
Content route handlers.

Registers GET routes for:
    /api/content-items
"""

from __future__ import annotations

from typing import Any

from kenradar.web.queries import load_content_items
from kenradar.web.responses import error_response, json_response


def _handle_content_items(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config

    config = load_config(config_path)

    # Validate sort parameter
    valid_sorts = ("priority_desc", "newest", "score_desc")
    sort = query_params.get("sort", [valid_sorts[0]])[0]
    if sort not in valid_sorts:
        error_response(self, f"无效的排序方式，可选值: {', '.join(valid_sorts)}", status=400)
        return

    # Validate limit
    try:
        limit = int(query_params.get("limit", ["30"])[0])
    except (TypeError, ValueError):
        error_response(self, "limit 必须是整数", status=400)
        return

    # Parse boolean params
    def _parse_bool(key: str) -> bool | None:
        val = query_params.get(key, [None])[0]
        if val is None:
            return None
        if val in ("true", "1", "yes"):
            return True
        if val in ("false", "0", "no"):
            return False
        error_response(self, f"无效的布尔值: {key}={val}", status=400)
        return None

    # Validate date params
    def _parse_date(key: str) -> str | None:
        val = query_params.get(key, [None])[0]
        if val is None:
            return None
        # Basic ISO date format validation: YYYY-MM-DD
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            error_response(self, f"日期格式无效，应为 YYYY-MM-DD: {key}={val}", status=400)
            return None
        return val

    try:
        result = load_content_items(
            config,
            keyword=query_params.get("keyword", [None])[0],
            creator_id=_parse_int_param(query_params, "creator_id"),
            platform=query_params.get("platform", [None])[0],
            status=query_params.get("status", [None])[0],
            high_value=_parse_bool("high_value"),
            reviewed=_parse_bool("reviewed"),
            date_from=_parse_date("date_from"),
            date_to=_parse_date("date_to"),
            sort=sort,
            cursor=query_params.get("cursor", [None])[0],
            limit=limit,
        )
    except Exception as exc:
        json_response(self, {"ok": False, "message": f"查询失败: {exc}"}, status=500)
        return

    result["ok"] = True
    json_response(self, result)


def _parse_int_param(query_params: dict, key: str) -> int | None:
    val = query_params.get(key, [None])[0]
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def register(handler_class: type) -> None:
    """Bind content handlers and register routes."""
    from kenradar.web.router import register_handler

    handler_class._handle_content_items = _handle_content_items
    register_handler("/api/content-items", _handle_content_items, ["config_path", "query_params"])
