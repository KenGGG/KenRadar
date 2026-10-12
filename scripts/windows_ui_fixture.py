"""Prepare a clearly labelled, isolated file database for manual browser acceptance."""
from pathlib import Path
import os
import yaml
from kenradar.core.config import load_config
from kenradar.storage.migrate import upgrade_database
from kenradar.storage import create_database


def main():
    for name in ("DATABASE_URL", "AGNES_API_KEY", "FEISHU_WEBHOOK_URL"):
        os.environ.pop(name, None)
    root = Path("data/test-migration/ui").resolve()
    path = root / "config/config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError("Use existing fixture; do not replace its config")
    path.write_text(yaml.safe_dump({"app": {"data_dir": str(root), "database_url": "sqlite:///" + (root / "db/fixture.sqlite3").as_posix(), "web_base_url": "http://127.0.0.1:19876"}, "schedule": {"enabled": False, "source_radar_enabled": False}, "ai": {"funasr": {"enabled": False, "managed": False}, "whisper": {"enabled": False}, "organizer": {"providers": []}}, "notification": {"enabled": False}, "publishing": {"github_pages": {"enabled": False}, "github_sync": {"enabled": False, "auto_push": False}}}), encoding="utf-8")
    upgrade_database(str(path))
    db = create_database(load_config(path))
    seed_content(db, root)
    print(path)


def seed_content(db, root):
    creator = db.upsert_creator("douyin", "fixture-source", "界面验收样本", "")
    cid = db.upsert_content_item("douyin", "000000000000000012345", creator, title="测试样本：国债与算力投资研究")
    note = root / "notes/douyin/fixture/研究样本.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    body = "# 界面验收样本\n\n> [!summary]\n> 此内容仅用于界面测试，并非真实采集结果。\n\n## 一、内容简述\n样本用于验证中文阅读。\n\n## 二、分段原文\n不能把转录错误修正成相反的事实。\n\n## 三、知识关联\n[[国债]] [[算力]]\n\n## 四、视频原始转录\n原始样本：不会自动发布或推送。\n"
    if not note.exists():
        note.write_text(body, encoding="utf-8")
    db.replace_transcript_analysis_and_note(cid, {"text_content": "原始样本：不会自动发布或推送。", "status": "success"}, {"status": "success", "result_text": "样本：国债与算力研究", "result_json": {"value_score": 4, "topics": ["国债", "算力"], "tags": ["KenRadar", "测试样本"], "recommended_action": "read"}}, {"note_path": str(note)})


if __name__ == "__main__":
    main()
