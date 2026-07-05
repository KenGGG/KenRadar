from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from kenradar.core.config import load_config
from kenradar.storage.pg_database import Database as PostgreSQLDatabase


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate KenRadar SQLite data to PostgreSQL")
    parser.add_argument("--config", default="config/config.yaml", help="配置文件路径")
    parser.add_argument("--sqlite", default="", help="旧 SQLite 数据库路径；默认读取 app.database_path")
    parser.add_argument("--database-url", default="", help="PostgreSQL 连接串；默认读取 DATABASE_URL/app.database_url")
    args = parser.parse_args()

    config = load_config(args.config)
    sqlite_path = Path(args.sqlite).expanduser().resolve() if args.sqlite else config.database_path
    database_url = args.database_url or config.database_url
    if not database_url:
        raise ValueError("缺少 PostgreSQL database_url，请设置 DATABASE_URL 或 app.database_url")
    if not sqlite_path.exists():
        raise FileNotFoundError(sqlite_path)

    pg = PostgreSQLDatabase(database_url)
    pg.initialize()
    stats = migrate(sqlite_path, pg)
    report_path = write_report(config.data_dir, sqlite_path, database_url, stats)
    print(f"迁移完成: {stats}")
    print(f"迁移报告: {report_path}")


def migrate(sqlite_path: Path, pg: PostgreSQLDatabase) -> dict[str, int]:
    stats = {
        "blogger": 0,
        "aweme": 0,
        "transcript": 0,
        "summary": 0,
        "push_log": 0,
        "alert_log": 0,
        "research_job": 0,
        "research_job_item": 0,
        "transcript_file_missing": 0,
        "transcript_json_missing": 0,
    }
    blogger_id_map: dict[int, int] = {}
    research_job_id_map: dict[int, int] = {}

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT * FROM blogger ORDER BY id").fetchall():
            new_id = pg.upsert_blogger(
                url=str(row["douyin_url"] or ""),
                name=str(row["nickname"] or row["sec_uid"] or ""),
                sec_uid=str(row["sec_uid"] or ""),
                enabled=bool(row["enabled"]),
            )
            blogger_id_map[int(row["id"])] = new_id
            stats["blogger"] += 1

        for row in conn.execute("SELECT * FROM aweme ORDER BY id").fetchall():
            blogger_id = blogger_id_map.get(int(row["blogger_id"]))
            if not blogger_id:
                continue
            aweme = {
                "aweme_id": str(row["aweme_id"] or ""),
                "desc": row["title"],
                "title": row["title"],
                "aweme_type": row["aweme_type"],
                "create_time": row["create_time"],
                "duration": row["duration"],
                "video_url": row["video_url"],
                "cover_url": row["cover_url"],
                "local_path": row["local_path"],
            }
            extra = _read_aweme_json(row["local_path"])
            aweme.update(extra)
            pg.insert_aweme(blogger_id, aweme, status=str(row["download_status"] or "pending"))
            pg.update_aweme_download(
                str(row["aweme_id"] or ""),
                str(row["download_status"] or "pending"),
                str(row["local_path"] or "") or None,
                str(row["video_url"] or "") or None,
                metadata=extra,
            )
            stats["aweme"] += 1

        for row in conn.execute("SELECT * FROM transcript ORDER BY id").fetchall():
            text = str(row["text_content"] or "")
            if not text and row["text_path"]:
                path = Path(str(row["text_path"]))
                if path.exists():
                    text = path.read_text(encoding="utf-8", errors="replace")
                else:
                    stats["transcript_file_missing"] += 1
            segments: dict[str, Any] = {}
            if row["json_path"]:
                path = Path(str(row["json_path"]))
                if path.exists():
                    try:
                        loaded = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                        if isinstance(loaded, dict):
                            segments = loaded
                    except json.JSONDecodeError:
                        segments = {}
                else:
                    stats["transcript_json_missing"] += 1
            pg.upsert_transcript(
                aweme_id=str(row["aweme_id"] or ""),
                text=text,
                text_path="",
                json_path="",
                model=str(row["model"] or "large-v3-turbo"),
                status=str(row["status"] or "pending"),
                error_message=row["error_message"],
                segments_json=segments,
            )
            stats["transcript"] += 1

        for row in conn.execute("SELECT * FROM summary ORDER BY id").fetchall():
            pg.upsert_summary(
                aweme_id=str(row["aweme_id"] or ""),
                summary_text=str(row["summary_text"] or ""),
                summary_path=str(row["summary_path"] or ""),
                model=str(row["model"] or ""),
                status=str(row["status"] or "pending"),
                error_message=row["error_message"],
            )
            stats["summary"] += 1

        for row in conn.execute("SELECT * FROM push_log ORDER BY id").fetchall():
            pg.insert_push_log(
                aweme_id=str(row["aweme_id"] or "") or None,
                batch_id=str(row["batch_id"] or ""),
                status=str(row["status"] or ""),
                error_message=row["error_message"],
            )
            stats["push_log"] += 1

        for row in conn.execute("SELECT * FROM alert_log ORDER BY id").fetchall():
            pg.insert_alert_log(
                level=str(row["level"] or "info"),
                component=str(row["component"] or "system"),
                message=str(row["message"] or ""),
                aweme_id=str(row["aweme_id"] or "") or None,
                title=row["title"],
                context=row["context"],
                notified=bool(row["notified"]),
            )
            stats["alert_log"] += 1

        for row in conn.execute("SELECT * FROM research_job ORDER BY id").fetchall():
            new_id = pg.create_research_job(
                platform=str(row["platform"] or "douyin"),
                blogger_id=blogger_id_map.get(int(row["blogger_id"])) if row["blogger_id"] else None,
                blogger_name=str(row["blogger_name"] or ""),
                limit_count=int(row["limit_count"] or 0),
                since_time=row["since_time"],
                until_time=row["until_time"],
                push_enabled=bool(row["push_enabled"]),
                force_enabled=bool(row["force_enabled"]),
            )
            research_job_id_map[int(row["id"])] = new_id
            pg.update_research_job(
                new_id,
                status=row["status"],
                total_count=row["total_count"],
                pending_count=row["pending_count"],
                success_count=row["success_count"],
                failed_count=row["failed_count"],
                skipped_count=row["skipped_count"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                last_error=row["last_error"],
                report_path=row["report_path"] if "report_path" in row.keys() else "",
            )
            stats["research_job"] += 1

        for row in conn.execute("SELECT * FROM research_job_item ORDER BY id").fetchall():
            new_job_id = research_job_id_map.get(int(row["job_id"]))
            if not new_job_id:
                continue
            pg.upsert_research_job_item(
                new_job_id,
                str(row["aweme_id"] or ""),
                str(row["status"] or "pending"),
                row["error_message"],
            )
            stats["research_job_item"] += 1
    finally:
        conn.close()
    return stats


def _read_aweme_json(local_path: Any) -> dict[str, Any]:
    if not local_path:
        return {}
    path = Path(str(local_path))
    candidates = [path.with_suffix(".json")]
    candidates.extend(path.parent.glob(f"*{path.stem[-19:]}*.json") if path.parent.exists() else [])
    for candidate in candidates:
        if candidate.exists():
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            return loaded if isinstance(loaded, dict) else {}
    return {}


def write_report(data_dir: Path, sqlite_path: Path, database_url: str, stats: dict[str, int]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"migration_sqlite_to_pg_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    safe_url = database_url.split("@", 1)[-1] if "@" in database_url else database_url
    lines = [
        f"# SQLite → PostgreSQL 迁移报告｜{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- SQLite: `{sqlite_path}`",
        f"- PostgreSQL: `{safe_url}`",
        "",
        "| 对象 | 数量 |",
        "|---|---:|",
    ]
    for key, value in stats.items():
        lines.append(f"| {key} | {value} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
