"""Generic V2 content detail endpoint."""

from __future__ import annotations

from typing import Any

from kenradar.web.responses import error_response, json_response


def _first(query_params: dict, key: str) -> str:
    return str((query_params.get(key) or [""])[0] or "").strip()


def _content_id(config: Any, query_params: dict) -> int:
    raw_id = _first(query_params, "id")
    if raw_id.isdigit():
        return int(raw_id)
    platform = _first(query_params, "platform")
    external_id = _first(query_params, "external_id")
    if not platform or not external_id:
        return 0
    from kenradar.storage import create_database

    item = create_database(config).find_content_item(platform, external_id)
    return int((item or {}).get("id") or 0)


def load_content_detail(config: Any, content_item_id: int) -> dict[str, Any] | None:
    """Read a current content result directly from the V2 tables."""
    from kenradar.storage import create_database
    from kenradar.web.helpers import _frontend_content
    from kenradar.web.queries import _enrich_aweme_row

    database = create_database(config)
    if getattr(database, "dialect", "") == "sqlite":
        from datetime import datetime
        from sqlalchemy import select
        bundle = database.get_current_bundle(content_item_id)
        if bundle is None:
            return None
        c = bundle["content"]
        t, a, n = bundle["transcript"] or {}, bundle["analysis"] or {}, bundle["note"] or {}
        p, cr = database.table("platform"), database.table("creator")
        with database.connect() as conn:
            platform = conn.execute(select(p.c.code).where(p.c.id == c["platform_id"])).fetchone()[0]
            creator = conn.execute(select(cr.c.nickname).where(cr.c.id == c["creator_id"])).fetchone()
        record = {**c, "content_item_id": c["id"], "platform": platform,
            "nickname": creator[0] if creator else "", "aweme_id": c["content_id"],
            "create_time": int(datetime.fromisoformat(c["publish_time"].replace("Z", "+00:00")).timestamp()) if c["publish_time"] else 0,
            "aweme_created_at": c["created_at"], "video_url": c["media_url"] or c["source_url"],
            "transcript_status": t.get("status", "pending"), "transcript_error": t.get("error_message"),
            "text_content": t.get("text_content"), "transcript_created_at": t.get("created_at"),
            "transcript_updated_at": t.get("updated_at"), "summary_status": a.get("status", "pending"),
            "summary_error": a.get("error_message"), "summary_text": a.get("result_text"),
            "summary_json": a.get("result_json"), "summary_updated_at": a.get("updated_at"),
            "summary_path": n.get("note_path"), "push_status": "pending"}
        return {"content_item_id": content_item_id, "item": _frontend_content(config, _enrich_aweme_row(record), include_content=True)}
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT ci.id AS content_item_id, ci.content_id, ci.title, ci.publish_time,
                   ci.created_at, ci.duration, ci.source_url, ci.media_url, ci.local_path,
                   ci.download_status, ci.status AS content_status,
                   ci.current_error_code, ci.current_error_message,
                   p.code AS platform, cr.nickname,
                   COALESCE(t.status, 'pending') AS transcript_status,
                   t.error_message AS transcript_error, t.text_content,
                   t.created_at AS transcript_created_at, t.updated_at AS transcript_updated_at,
                   COALESCE(a.status, 'pending') AS summary_status,
                   a.error_message AS summary_error, a.result_text AS summary_text,
                   a.result_json AS summary_json, a.updated_at AS summary_updated_at,
                   n.note_path AS summary_path,
                   COALESCE((SELECT pl.status FROM push_log pl
                             WHERE pl.content_item_id=ci.id ORDER BY pl.id DESC LIMIT 1), 'pending') AS push_status
            FROM content_item ci
            JOIN platform p ON p.id = ci.platform_id
            LEFT JOIN creator cr ON cr.id = ci.creator_id
            LEFT JOIN transcript t ON t.content_item_id = ci.id
            LEFT JOIN ai_analysis a
              ON a.content_item_id = ci.id AND a.analysis_type = 'summary'
            LEFT JOIN content_note n
              ON n.content_item_id = ci.id AND n.note_type = 'content'
            WHERE ci.id = %s
            """,
            (content_item_id,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record.update(
        {
            "aweme_id": record["content_id"],
            "create_time": int(record["publish_time"].timestamp()) if record.get("publish_time") else 0,
            "aweme_created_at": record.get("created_at"),
            "video_url": record.get("media_url") or record.get("source_url"),
        }
    )
    item = _frontend_content(config, _enrich_aweme_row(record), include_content=True)
    return {
        "content_item_id": content_item_id,
        "item": item,
    }


def load_content_operations(config: Any, content_item_id: int) -> list[dict[str, Any]] | None:
    from kenradar.storage import create_database

    database = create_database(config)
    if database.get_current_bundle(content_item_id) is None:
        return None
    return database.publications.list_operations(content_item_id)


def _handle_content_detail(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config

    config = load_config(config_path)
    content_item_id = _content_id(config, query_params)
    if content_item_id <= 0:
        error_response(self, "需要有效的 content id", status=400)
        return
    payload = load_content_detail(config, content_item_id)
    if payload is None:
        error_response(self, "内容不存在", status=404)
        return
    json_response(self, payload)


def _handle_content_operations(self: Any, config_path: str, query_params: dict) -> None:
    from kenradar.core.config import load_config

    config = load_config(config_path)
    content_item_id = _content_id(config, query_params)
    if content_item_id <= 0:
        error_response(self, "需要有效的 content id", status=400)
        return
    operations = load_content_operations(config, content_item_id)
    if operations is None:
        error_response(self, "内容不存在", status=404)
        return
    json_response(self, {"content_item_id": content_item_id, "operations": operations})


def register(handler_class: type) -> None:
    from kenradar.web.router import register_handler

    handler_class._handle_content_detail = _handle_content_detail
    handler_class._handle_content_operations = _handle_content_operations
    register_handler("/api/content", _handle_content_detail, ["config_path", "query_params"], method="GET")
    register_handler("/api/content/operations", _handle_content_operations, ["config_path", "query_params"], method="GET")
