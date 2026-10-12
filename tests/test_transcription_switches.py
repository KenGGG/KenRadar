"""Engine-switch unit contracts. These do not certify real Windows ASR."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from kenradar.core.config import AppConfig
from kenradar.core.transcriber import Transcriber
from test_sqlite_v2 import sqlite_db


def transcriber(raw):
    instance = Transcriber.__new__(Transcriber)
    instance.config = AppConfig(raw=raw, path=Path("config/config.yaml"))
    instance._is_probably_no_speech_media = lambda metadata: False
    return instance


def test_funasr_is_not_disabled_by_whisper_switch():
    engine = transcriber({"ai": {"whisper": {"enabled": False}, "funasr": {"enabled": True}}})
    engine._try_funasr = AsyncMock(return_value={"status": "success", "text": "真实引擎响应的替身"})
    assert asyncio.run(engine.transcribe("001", Path("fixture.mp4")))["status"] == "success"
    engine._try_funasr.assert_awaited_once()


def test_global_switch_and_failed_primary_without_fallback():
    engine = transcriber({"ai": {"transcription": {"enabled": False}, "funasr": {"enabled": True}}})
    engine._try_funasr = AsyncMock()
    assert asyncio.run(engine.transcribe("001", Path("fixture.mp4")))["status"] == "skipped"
    engine._try_funasr.assert_not_awaited()
    engine = transcriber({"ai": {"whisper": {"enabled": False}, "funasr": {"enabled": True}}})
    engine._try_funasr = AsyncMock(return_value={"status": "failed", "error": "fixture unavailable"})
    assert asyncio.run(engine.transcribe("001", Path("fixture.mp4")))["status"] == "failed"


def test_correction_does_not_replace_original_in_sqlite(sqlite_db, tmp_path):
    db, cfg = sqlite_db
    creator = db.upsert_creator("douyin", "author", "样本作者", "")
    cid = db.upsert_content_item("douyin", "0001", creator, title="原稿保存契约")
    engine = transcriber({"ai": {"funasr": {"enabled": True}, "whisper": {"enabled": False}}, "transcribe": {"save_txt": True}})
    engine.database = db
    engine._validate_transcript_text = lambda *args: None
    engine._validate_asr_quality = lambda *args: None
    engine._funasr_transcribe_sync = lambda *args: {"text": "原话：不会增长 15%。"}
    engine._correct_text = AsyncMock(return_value="修订候选：会增长 50%。")
    result = asyncio.run(engine.transcribe("0001", tmp_path / "fixture.mp4"))
    assert result["status"] == "success"
    assert result["text"] == "原话：不会增长 15%。"
    assert result["corrected_text"] == "修订候选：会增长 50%。"
    assert db.get_current_bundle(cid)["transcript"]["text_content"] == result["text"]
