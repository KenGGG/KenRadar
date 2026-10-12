"""
Source metrics aggregation scanner.

Computes daily per-source metrics from content_item and related tables.
Designed to be idempotent — rerunning for the same date range produces
the same result (UPSERT on source_id + metric_date).

CLI:
    python -m kenradar analytics-scan --days 7 --step aggregate
    python -m kenradar analytics-scan --days 30 --step aggregate --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

from kenradar.core.curation import CurationPolicy

HIGH_VALUE_THRESHOLD = CurationPolicy().high_value_threshold


def aggregate_source_metrics(
    config,
    days: int = 7,
    dry_run: bool = False,
) -> dict[str, int]:
    """Compute daily metrics for each source over the last `days` days.

    Returns a summary dict with counts of rows processed/updated/skipped.
    """
    from kenradar.storage import create_database

    db = create_database(config)
    if getattr(config, "database_type", "") == "sqlite":
        from kenradar.storage.sqlite_analytics import aggregate
        return aggregate(db, config, days=days, dry_run=dry_run)
    policy = CurationPolicy.from_config(config)
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)

    summary = {
        "total_days": 0,
        "sources_processed": 0,
        "rows_upserted": 0,
        "rows_skipped_no_mapping": 0,
        "errors": 0,
    }

    # Get all enabled sources with their creator mappings
    with db.connect() as conn:
        sources = conn.execute(
            """
            SELECT s.id AS source_id, s.display_name, s.platform_id,
                   s.source_key, s.feed_url, s.source_url
            FROM source_subscription s
            WHERE s.enabled = true
            ORDER BY s.id
            """
        ).fetchall()

    logger.info("Found %d enabled sources, computing %d days of metrics", len(sources), days)

    for source_row in sources:
        source_id = int(source_row["source_id"])
        source_name = source_row["display_name"] or str(source_id)

        # Find linked creators for this source
        with db.connect() as conn2:
            creators = conn2.execute(
                """
                SELECT cr.id AS creator_id
                FROM creator cr
                WHERE cr.platform_id = %s
                  AND (
                      cr.platform_uid = %s
                      OR cr.profile_url = %s
                      OR cr.profile_url = %s
                      OR cr.nickname = %s
                  )
                """,
                (
                    source_row["platform_id"],
                    source_row["source_key"],
                    source_row["source_url"],
                    source_row["feed_url"],
                    source_row["display_name"],
                ),
            ).fetchall()

        creator_ids = [int(c["creator_id"]) for c in creators]
        mapped_count = len(creator_ids)

        for d in _date_range(start_date, end_date):
            summary["total_days"] += 1

            # Compute metrics for this source+date
            metrics = _compute_day_metrics(
                db,
                source_id,
                creator_ids,
                d,
                high_value_threshold=policy.high_value_threshold,
            )
            summary["sources_processed"] += 1

            if dry_run:
                logger.info(
                    "DRY-RUN source=%s date=%s total=%d rated=%d hv=%d avg=%.1f push=%d review=%d failed=%d",
                    source_name, d,
                    metrics["total_content"], metrics["rated_count"],
                    metrics["high_value_count"], metrics["avg_rating"] or 0,
                    metrics["push_count"], metrics["review_count"],
                    metrics["failed_count"],
                )
                summary["rows_upserted"] += 1
                _aggregate_source_topics(db, source_id, creator_ids, d, dry_run=True)
                continue

            # Upsert into source_daily_metrics
            try:
                with db.connect() as conn3:
                    conn3.execute(
                        """
                        INSERT INTO source_daily_metrics
                            (source_id, metric_date, total_content, rated_count,
                             high_value_count, avg_rating, push_count, review_count,
                             failed_count, calculation_version, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'v1', NOW())
                        ON CONFLICT (source_id, metric_date)
                        DO UPDATE SET
                            total_content = EXCLUDED.total_content,
                            rated_count = EXCLUDED.rated_count,
                            high_value_count = EXCLUDED.high_value_count,
                            avg_rating = EXCLUDED.avg_rating,
                            push_count = EXCLUDED.push_count,
                            review_count = EXCLUDED.review_count,
                            failed_count = EXCLUDED.failed_count,
                            calculation_version = EXCLUDED.calculation_version,
                            updated_at = NOW()
                        """,
                        (
                            source_id, d,
                            metrics["total_content"], metrics["rated_count"],
                            metrics["high_value_count"], metrics["avg_rating"],
                            metrics["push_count"], metrics["review_count"],
                            metrics["failed_count"],
                        ),
                    )
                summary["rows_upserted"] += 1
            except Exception:
                logger.exception("Failed to upsert metrics for source=%s date=%s", source_name, d)
                summary["errors"] += 1
            _aggregate_source_topics(db, source_id, creator_ids, d, dry_run=dry_run)

    if not dry_run:
        logger.info(
            "Aggregation complete: %s",
            ", ".join(f"{k}={v}" for k, v in summary.items()),
        )

    return summary


def _aggregate_source_topics(db: Any, source_id: int, creator_ids: list[int], metric_date: date, dry_run: bool = False) -> None:
    """Persist topics/tags already present in ai_analysis; never creates AI calls."""
    if not creator_ids:
        return
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT ai.result_json
            FROM content_item ci
            JOIN ai_analysis ai ON ai.content_item_id = ci.id AND ai.analysis_type = 'summary'
            WHERE ci.creator_id = ANY(%s) AND ci.publish_time::date = %s
            """,
            (creator_ids, metric_date),
        ).fetchall()
    from collections import Counter
    import json
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get("result_json") if hasattr(row, "get") else row[0]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = {}
        if not isinstance(value, dict):
            continue
        labels = value.get("topics") or value.get("tags") or value.get("keywords") or []
        if isinstance(labels, str):
            labels = [labels]
        for label in labels if isinstance(labels, list) else []:
            text = str(label).strip()[:128]
            if text:
                counts[text] += 1
    if dry_run or not counts:
        return
    total = max(1, len(rows))
    with db.connect() as conn:
        conn.execute("DELETE FROM source_topic_metrics WHERE source_id = %s AND metric_date = %s AND taxonomy_version = 'v1'", (source_id, metric_date))
        for topic, count in counts.items():
            conn.execute(
                """
                INSERT INTO source_topic_metrics
                    (source_id, metric_date, topic, content_count, content_ratio, taxonomy_version, model_name, updated_at)
                VALUES (%s, %s, %s, %s, %s, 'v1', 'existing-ai-labels', NOW())
                ON CONFLICT (source_id, metric_date, topic, taxonomy_version)
                DO UPDATE SET content_count = EXCLUDED.content_count,
                              content_ratio = EXCLUDED.content_ratio,
                              updated_at = NOW()
                """,
                (source_id, metric_date, topic, count, round(count / total, 6)),
            )


def _date_range(start: date, end: date):
    """Yield dates from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _compute_day_metrics(
    db: Any,
    source_id: int,
    creator_ids: list[int],
    metric_date: date,
    *,
    high_value_threshold: float = HIGH_VALUE_THRESHOLD,
) -> dict[str, Any]:
    """Compute metrics for a single source on a single day."""
    with db.connect() as conn:
        # Build creator filter
        if creator_ids:
            creator_filter = "ci.creator_id IN (%s)" % ",".join(str(x) for x in creator_ids)
        else:
            creator_filter = "1=0"  # no creators mapped

        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_content,
                COUNT(*) FILTER (WHERE (ai.result_json->>'value_score') ~ '^[0-9]+([.][0-9]+)?$') AS rated_count,
                AVG((ai.result_json->>'value_score')::float) FILTER (WHERE (ai.result_json->>'value_score') ~ '^[0-9]+([.][0-9]+)?$') AS avg_rating,
                COUNT(*) FILTER (WHERE (ai.result_json->>'value_score') ~ '^[0-9]+([.][0-9]+)?$' AND (ai.result_json->>'value_score')::float >= {high_value_threshold:g}) AS high_value_count,
                COUNT(*) FILTER (WHERE ai.result_json->>'recommended_action' = 'push') AS push_count,
                COUNT(*) FILTER (WHERE ai.result_json->>'recommended_action' = 'confirm') AS review_count,
                COUNT(*) FILTER (WHERE ci.download_status = 'failed' OR ai.status = 'failed') AS failed_count
            FROM content_item ci
            LEFT JOIN ai_analysis ai ON ai.content_item_id = ci.id
            WHERE {creator_filter}
              AND ci.publish_time::date = %s
            """,
            (metric_date,),
        ).fetchone()

        return {
            "total_content": int(row["total_content"] or 0),
            "rated_count": int(row["rated_count"] or 0),
            "avg_rating": round(float(row["avg_rating"] or 0), 4) if row["avg_rating"] else None,
            "high_value_count": int(row["high_value_count"] or 0),
            "push_count": int(row["push_count"] or 0),
            "review_count": int(row["review_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
        }


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Source metrics aggregation scanner")
    parser.add_argument("--days", type=int, default=7, help="Number of days to aggregate (default: 7)")
    parser.add_argument("--step", choices=["aggregate", "topic-classify"], default="aggregate", help="Step to run")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    args = parser.parse_args(argv)

    if args.step in {"aggregate", "topic-classify"}:
        from kenradar.core.config import load_config

        config = load_config("config/config.yaml")
        t0 = time.monotonic()
        summary = aggregate_source_metrics(config, days=args.days, dry_run=args.dry_run)
        elapsed = round(time.monotonic() - t0, 2)
        summary["elapsed_s"] = elapsed
        print(f"\n{'DRY-RUN ' if args.dry_run else ''}Summary:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        return 0
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.exit(cli_main())
