import json
from pathlib import Path

import pytest
from kenradar.core.config import AppConfig
from kenradar.core.transcriber import Transcriber


class DB:
    def upsert_transcript(self, *args, **kwargs):
        pass


def test_chunked_asr_resumes_raw_chunks_and_covers_tail(tmp_path, monkeypatch):
    config = AppConfig({'app': {'data_dir': str(tmp_path)}, 'ai': {'whisper': {'chunk_seconds': 600, 'checkpoint_dir': str(tmp_path/'checkpoints')}}}, tmp_path/'config/config.yaml')
    transcriber = Transcriber(config, DB())
    media = tmp_path/'actual.mp4'
    media.write_bytes(b'fixture-media')
    monkeypatch.setattr(transcriber, '_media_duration', lambda p: 1250.25, raising=False)
    extracted = []
    def extract(source, target, start, duration):
        extracted.append((start, duration))
        target.write_bytes(b'pcm')
    monkeypatch.setattr(transcriber, '_extract_asr_chunk', extract, raising=False)
    calls = []
    def recognize(identity, path, model, device, language, backend, platform):
        calls.append(path.name)
        if len(calls) == 2:
            raise RuntimeError('interrupted inference')
        return {'text': path.stem, 'duration': 600, 'segments': [{'start': 0, 'end': 10, 'text': path.stem}]}
    monkeypatch.setattr(transcriber, '_transcribe_with_fallback', recognize)
    with pytest.raises(RuntimeError, match='interrupted'):
        transcriber._transcribe_chunked_sync('exact', media, 'turbo', 'cpu', 'zh', 'faster-whisper', 'douyin')
    files = list((tmp_path/'checkpoints').rglob('chunk-00000.json'))
    assert len(files) == 1
    saved = files[0].read_bytes()
    result = transcriber._transcribe_chunked_sync('exact', media, 'turbo', 'cpu', 'zh', 'faster-whisper', 'douyin')
    assert len(calls) == 4  # successful first chunk is NOT inferred again
    assert result['coverage'] == {'duration_seconds': 1250.25, 'covered_seconds': 1250.25, 'chunks_done': 3, 'chunks_total': 3, 'complete': True}
    assert [c['start'] for c in result['chunks']] == [0, 600, 1200]
    assert extracted[-1] == (1200, 50.25)
    assert [s['start'] for s in result['segments']] == [0, 600, 1200]
    assert files[0].read_bytes() == saved
    progress = json.loads((files[0].parent/'progress.json').read_text())
    assert progress['coverage']['complete'] is True
    assert all(Path(c['raw_path']).is_file() for c in result['chunks'])


def test_funasr_long_media_is_bounded_and_resumes_after_timeout(tmp_path, monkeypatch):
    config = AppConfig({'app': {'data_dir': str(tmp_path)}, 'ai': {'funasr': {
        'chunk_seconds': 300, 'checkpoint_dir': str(tmp_path/'checkpoints')
    }}}, tmp_path/'config.yaml')
    transcriber = Transcriber(config, DB())
    media = tmp_path/'long.mp4'
    media.write_bytes(b'fixture-media')
    monkeypatch.setattr(transcriber, '_media_duration', lambda p: 650.25)
    monkeypatch.setattr(transcriber, '_extract_asr_chunk', lambda s, p, a, b: p.write_bytes(b'pcm'))
    calls = []
    def recognize(path, metadata):
        calls.append(metadata['duration'])
        if len(calls) == 2:
            raise TimeoutError('read timed out')
        return {'text': '这里是保留原始语音内容的完整转录。' * 40,
                'segments': [{'start': 0, 'end': metadata['duration'], 'text': '原文'}]}
    monkeypatch.setattr(transcriber, '_funasr_transcribe_sync', recognize)
    with pytest.raises(TimeoutError):
        transcriber._funasr_transcribe_resumable('123', media, {'platform': 'douyin', 'raw_metadata': {'video': {'duration': 35919766}}})
    result = transcriber._funasr_transcribe_resumable('123', media, {'platform': 'douyin', 'raw_metadata': {'video': {'duration': 35919766}}})
    assert calls == [300, 300, 300, 50.25]
    assert result['coverage']['complete']
    assert result['coverage']['covered_seconds'] == 650.25
    assert [s['start'] for s in result['segments']] == [0, 300, 600]
    assert result['backend'] == 'funasr'


def test_funasr_transient_window_failure_retries_same_engine(tmp_path, monkeypatch):
    import requests
    config = AppConfig({'app': {'data_dir': str(tmp_path)}}, tmp_path/'config.yaml')
    engine = Transcriber(config, DB())
    attempts = []
    monkeypatch.setattr('kenradar.core.transcriber.time.sleep', lambda _: None)
    def recognize(path, metadata):
        attempts.append(path)
        if len(attempts) == 1:
            raise requests.Timeout('temporary read timeout')
        return {'text': 'FunASR 原始转录'}
    monkeypatch.setattr(engine, '_funasr_transcribe_sync', recognize)
    assert engine._funasr_transcribe_retry(tmp_path/'window.wav', {})['text'] == 'FunASR 原始转录'
    assert attempts == [tmp_path/'window.wav'] * 2


def test_funasr_permanent_http_failure_does_not_retry(tmp_path, monkeypatch):
    import requests
    engine = Transcriber(AppConfig({}, tmp_path/'config.yaml'), DB())
    attempts = []
    def recognize(path, metadata):
        attempts.append(path)
        response = requests.Response()
        response.status_code = 401
        raise requests.HTTPError('unauthorized', response=response)
    monkeypatch.setattr(engine, '_funasr_transcribe_sync', recognize)
    with pytest.raises(requests.HTTPError):
        engine._funasr_transcribe_retry(tmp_path/'window.wav', {})
    assert len(attempts) == 1
