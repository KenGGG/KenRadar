"""Read-only V1/V2 data-shape reconciliation for KenRadar media radar."""

from __future__ import annotations

import argparse
import json
from typing import Any


def compare_snapshot(snapshot: dict[str, set[str]]) -> dict[str, list[str]]:
    """Return legacy identities/results missing from their V2 counterparts."""
    return {
        "source_mismatches": sorted(snapshot.get("legacy_sources", set()) - snapshot.get("subscriptions", set())),
        "content_mismatches": sorted(snapshot.get("legacy_content", set()) - snapshot.get("content_items", set())),
        "result_mismatches": sorted(snapshot.get("legacy_results", set()) - snapshot.get("current_results", set())),
    }


def load_snapshot(config_path: str) -> dict[str, set[str]]:
    from kenradar.core.config import load_config
    from kenradar.storage import create_database

    database = create_database(load_config(config_path))
    with database.connect() as conn:
        subscriptions = {
            f"{row['platform']}:{row['source_key']}"
            for row in conn.execute(
                """SELECT p.code AS platform, s.source_key FROM source_subscription s
                   JOIN platform p ON p.id=s.platform_id"""
            ).fetchall()
        }
        # Legacy views predate multi-platform support. Infer their platform
        # from the V2 counterpart or original URL instead of hard-coding it.
        legacy_sources = {
            f"{row['platform']}:{row['sec_uid']}" for row in conn.execute(
                """
                SELECT b.sec_uid, COALESCE(
                    (SELECT p.code FROM content_item ci JOIN platform p ON p.id=ci.platform_id
                     JOIN creator cr ON cr.id=ci.creator_id WHERE cr.platform_uid=b.sec_uid LIMIT 1),
                    CASE WHEN b.douyin_url ILIKE '%xiaoyuzhoufm.com%' OR b.douyin_url ILIKE '%firstory.me%'
                         THEN 'xiaoyuzhou' ELSE 'douyin' END
                ) AS platform
                FROM blogger b
                WHERE COALESCE(b.sec_uid, '') <> '' AND b.sec_uid NOT LIKE 'single_video:%'
                """
            ).fetchall()
        }
        content_items = {
            f"{row['platform']}:{row['content_id']}" for row in conn.execute(
                """SELECT p.code AS platform, ci.content_id FROM content_item ci
                   JOIN platform p ON p.id=ci.platform_id"""
            ).fetchall()
        }
        legacy_content = {
            f"{row['platform']}:{row['aweme_id']}" for row in conn.execute(
                """
                SELECT a.aweme_id, COALESCE(
                    (SELECT p.code FROM content_item ci JOIN platform p ON p.id=ci.platform_id
                     WHERE ci.content_id=a.aweme_id LIMIT 1),
                    CASE WHEN b.douyin_url ILIKE '%xiaoyuzhoufm.com%' OR b.douyin_url ILIKE '%firstory.me%'
                         THEN 'xiaoyuzhou' ELSE 'douyin' END
                ) AS platform
                FROM aweme a JOIN blogger b ON b.id=a.blogger_id
                WHERE COALESCE(a.aweme_id, '') <> ''
                """
            ).fetchall()
        }
        current_results = {
            f"{row['platform']}:{row['content_id']}" for row in conn.execute(
                """SELECT p.code AS platform, ci.content_id FROM content_item ci
                   JOIN platform p ON p.id=ci.platform_id
                   JOIN content_note n ON n.content_item_id=ci.id AND n.note_type='content'
                   WHERE COALESCE(n.note_path, '') <> ''"""
            ).fetchall()
        }
        legacy_results = {
            f"{row['platform']}:{row['aweme_id']}" for row in conn.execute(
                """
                SELECT s.aweme_id, COALESCE(
                    (SELECT p.code FROM content_item ci JOIN platform p ON p.id=ci.platform_id
                     WHERE ci.content_id=s.aweme_id LIMIT 1),
                    CASE WHEN b.douyin_url ILIKE '%xiaoyuzhoufm.com%' OR b.douyin_url ILIKE '%firstory.me%'
                         THEN 'xiaoyuzhou' ELSE 'douyin' END
                ) AS platform
                FROM summary s JOIN aweme a ON a.aweme_id=s.aweme_id JOIN blogger b ON b.id=a.blogger_id
                WHERE s.status='success' AND COALESCE(s.summary_path, '') <> ''
                """
            ).fetchall()
        }
    return {
        "legacy_sources": legacy_sources,
        "subscriptions": subscriptions,
        "legacy_content": legacy_content,
        "content_items": content_items,
        "legacy_results": legacy_results,
        "current_results": current_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    report = compare_snapshot(load_snapshot(args.config))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not any(report.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
