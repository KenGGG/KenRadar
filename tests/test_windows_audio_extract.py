"""Real native FFmpeg media extraction; this is not a speech-model test."""
import subprocess
import wave
from pathlib import Path
import pytest
from kenradar.core.config import AppConfig
from kenradar.core.transcriber import Transcriber


def test_real_windows_media_audio_extraction(tmp_path):
    ffmpeg_package = pytest.importorskip('imageio_ffmpeg')
    executable = ffmpeg_package.get_ffmpeg_exe()
    video = tmp_path / '样本 口播音轨.mp4'
    generated = subprocess.run([executable,'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=black:s=64x64:r=1','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','1','-c:v','mpeg4','-c:a','aac',str(video)],capture_output=True,timeout=20)
    assert generated.returncode == 0, generated.stderr.decode(errors='replace')
    engine = Transcriber.__new__(Transcriber)
    engine.config = AppConfig(raw={'app':{'data_dir':str(tmp_path)},'ai':{'funasr':{'ffmpeg_path':executable}}},path=tmp_path/'config/config.yaml')
    audio = engine._asr_upload_path(video,'fixture','ai.funasr')
    assert audio != video and audio.is_relative_to(tmp_path)
    with wave.open(str(audio)) as source:
        assert source.getnchannels() == 1 and source.getframerate() == 16000
        assert 0.9 <= source.getnframes() / source.getframerate() <= 1.2
    assert video.exists()
