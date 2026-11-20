import asyncio
from pathlib import Path
from types import SimpleNamespace
from test_sqlite_v2 import sqlite_db
from kenradar.core.config import load_config
from kenradar.core.workflow import Workflow
from kenradar.sources.base import ContentItem


def test_retry_organizes_saved_transcript_and_reports_ai_failure(sqlite_db, tmp_path):
    db, config_path = sqlite_db
    creator = db.upsert_creator("xiaoyuzhou", "show", "Show", "")
    db.upsert_content_item("xiaoyuzhou", "episode", creator)
    db.upsert_transcript("episode", "saved original transcript", "", "", "fixture", "success", platform="xiaoyuzhou")
    workflow = object.__new__(Workflow)
    workflow.config = load_config(config_path)
    workflow.database = db
    workflow.organizer = SimpleNamespace(last_error="provider failed", organize=lambda *args: "degraded")
    note = tmp_path / "degraded.md"
    note.write_text("degraded", encoding="utf-8")
    workflow._write_item_summary = lambda *args: note
    workflow._cleanup_xiaoyuzhou_transcript_temp = lambda *args: None
    item = ContentItem(platform="xiaoyuzhou", creator="Show", creator_id="show", content_id="episode", source_url="https://example.test", original_title="Episode", published_at=None, media_type="audio", duration=0, description="", cover_url=None, raw_metadata={})
    adapter = SimpleNamespace(download_media=lambda item: (_ for _ in ()).throw(AssertionError("must reuse transcript")))
    result = asyncio.run(workflow._process_xiaoyuzhou_item(item, adapter, publish=False))
    assert result["status"] == "failed"
    assert result["error"] == "provider failed"
    assert db.get_current_bundle(db.find_content_item("xiaoyuzhou", "episode")["id"])["analysis"]["status"] == "failed"


def test_funasr_compressed_audio_normalized_with_bundled_ffmpeg(tmp_path):
    import subprocess
    import imageio_ffmpeg
    import soundfile
    from kenradar.core.config import AppConfig
    from kenradar.core.transcriber import Transcriber
    audio = tmp_path / "podcast.m4a"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.1", "-c:a", "aac", str(audio)], check=True)
    transcriber = object.__new__(Transcriber)
    transcriber.config = AppConfig({"app": {"data_dir": str(tmp_path)}}, tmp_path / "config.yaml")
    upload = transcriber._asr_upload_path(audio, "funasr", "ai.funasr")
    try:
        info = soundfile.info(upload)
        assert info.samplerate == 16000 and info.channels == 1
        assert upload.suffix == ".wav" and audio.is_file()
    finally:
        upload.unlink()
