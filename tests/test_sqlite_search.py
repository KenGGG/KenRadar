from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.storage.sqlite_search import candidate_ids, rebuild
from kenradar.web.sqlite_queries import content_items


def test_trigram_and_short_chinese_preserve_substring_semantics(sqlite_db):
    db, path = sqlite_db
    config = load_config(path)
    creator = db.upsert_creator("douyin", "source", "来源", "")
    cid = db.upsert_content_item("douyin", "0001", creator, title="国债基金 ETF 100%_收益")
    db.replace_transcript_analysis_and_note(cid, {"text_content": "原稿：不会增持金融资产。"}, {"result_text": "算力投资研究"}, {"note_path": "notes/fixture.md"})
    words = ("国债基金", "国债", "债", "ETF", "100%_", "不会增持", "算力投资", '"引号"', "不存在")
    baseline = {word: [item["id"] for item in content_items(config, keyword=word)["items"]] for word in words}
    assert rebuild(db) == 1
    assert candidate_ids(db, "国债") is None
    assert candidate_ids(db, "国债基金") is not None
    for word in words:
        assert [item["id"] for item in content_items(config, keyword=word)["items"]] == baseline[word]
    db.replace_analysis_and_note(cid, {"result_text": "机器人产业研究"}, {"note_path": "notes/new.md"})
    assert not content_items(config, keyword="算力投资")["items"]
    assert content_items(config, keyword="机器人产业")["items"]
    assert rebuild(db) == 1
