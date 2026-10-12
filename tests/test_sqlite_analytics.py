from datetime import datetime, timezone
from sqlalchemy import select
from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.core.analytics import aggregate_source_metrics
from kenradar.web.sqlite_queries import content_items


def test_real_metrics_idempotency_scores_and_topic_replacement(sqlite_db):
    db, path = sqlite_db
    config = load_config(path)
    creator = db.upsert_creator("douyin", "source-001", "统计来源", "")
    source = db.upsert_subscription(platform="douyin", source_key="source-001", display_name="统计来源", source_url="")
    ids = []
    for index, score in enumerate((3.5, "4.5", "invalid")):
        cid = db.upsert_content_item("douyin", f"000{index}", creator, title="国债", publish_time=datetime.now(timezone.utc))
        db.replace_transcript_analysis_and_note(cid, {"text_content": "不可删改的原稿", "status": "success"}, {"result_json": {"value_score": score, "topics": ["国债", "国债"]}}, {"note_path": f"notes/fixture-{index}.md"})
        ids.append(cid)
    assert len(content_items(config, high_value=True)["items"]) == 2
    before = aggregate_source_metrics(config, days=1, dry_run=True)
    with db.connect() as conn:
        assert conn.execute(select(db.table("source_daily_metrics"))).fetchone() is None
    first = aggregate_source_metrics(config, days=1)
    second = aggregate_source_metrics(config, days=1)
    assert first == second == before
    with db.connect() as conn:
        row = conn.execute(select(db.table("source_daily_metrics"))).fetchone()
        assert row["source_id"] == source
        assert (row["total_content"], row["rated_count"], row["high_value_count"], row["avg_rating"]) == (3, 2, 2, 4)
        topics = conn.execute(select(db.table("source_topic_metrics"))).fetchall()
        assert len(topics) == 1 and topics[0]["content_count"] == 3
    for cid in ids:
        db.replace_analysis_and_note(cid, {"result_json": {"value_score": 4, "topics": []}}, {"note_path": "notes/replaced.md"})
    aggregate_source_metrics(config, days=1)
    with db.connect() as conn:
        assert not conn.execute(select(db.table("source_topic_metrics"))).fetchall()
