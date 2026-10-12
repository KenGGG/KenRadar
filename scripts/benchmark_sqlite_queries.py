"""Reproducible 10k synthetic local fixture, never a production performance claim."""
import argparse
import json
import platform
from pathlib import Path
import statistics
import time
import sqlite3
import yaml
from sqlalchemy import insert
from kenradar.core.config import load_config
from kenradar.storage import create_database
from kenradar.storage.migrate import upgrade_database
from kenradar.storage.sqlite_search import rebuild
from kenradar.web.sqlite_queries import content_items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="query-benchmark")
    args = parser.parse_args()
    if not args.name.replace("-", "").isalnum():
        raise ValueError("fixture name must be a simple directory name")
    root = Path("data/test-migration") / args.name
    root.mkdir(exist_ok=False)
    root = root.resolve()
    path = root / "config/config.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump({"app": {"data_dir": str(root), "database_url": "sqlite:///" + (root / "db/fixture.sqlite3").as_posix()}, "schedule": {"enabled": False}}), encoding="utf-8")
    config = load_config(path)
    upgrade_database(str(path))
    db = create_database(config)
    creator = db.upsert_creator("douyin", "benchmark", "合成样本", "")
    with db.connect(write=True) as conn:
        conn.raw.execute(insert(db.table("content_item")), [dict(platform_id=1, content_id=f"00{i:020d}", creator_id=creator, title=f"国债基金 算力 ETF 合成样本 {i}", publish_time=f"2026-10-{1 + i % 9:02d}T00:00:00.000000Z", status="completed") for i in range(10000)])
        conn.raw.execute(insert(db.table("transcript")), [dict(content_item_id=i + 1, text_content="原稿样本：不能用空库或编译通过替代真实验收。" * 10, status="success") for i in range(10000)])
        conn.raw.execute(insert(db.table("ai_analysis")), [dict(content_item_id=i + 1, analysis_type="summary", result_text="国债与算力研究样本", result_json=json.dumps({"value_score": 3.5 + (i % 4) * 0.5}), status="success") for i in range(10000)])
    report = {"kind": "synthetic_fixture_only", "content_rows": 10000, "python": platform.python_version(), "sqlite": sqlite3.sqlite_version, "platform": platform.platform(), "samples_per_case": 30, "results": []}
    for indexed in (False, True):
        if indexed:
            rebuild(db)
        for keyword in ("国债", "国债基金", "不能用空库", "ETF", "%"):
            for _ in range(3):
                content_items(config, keyword=keyword, sort="score_desc", limit=30)
            times = []
            for _ in range(30):
                start = time.perf_counter()
                rows = content_items(config, keyword=keyword, sort="score_desc", limit=30)["items"]
                times.append((time.perf_counter() - start) * 1000)
            report["results"].append({"indexed": indexed, "keyword": keyword, "returned": len(rows), "p50_ms": round(statistics.median(times), 2), "p95_ms": round(sorted(times)[28], 2)})
    output = root / "query-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
