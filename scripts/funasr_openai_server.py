from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse


APP = FastAPI(title="KenRadar FunASR OpenAI-compatible API", version="1.0")
_MODEL: Any = None
_MODEL_LOCK = threading.Lock()
_STARTED_AT = int(time.time())


class RequestActivityTracker:
    """Track transcription activity without letting health probes extend GPU life."""

    def __init__(self, idle_timeout_seconds: float, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.idle_timeout_seconds = max(0.0, float(idle_timeout_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._active_requests = 0
        self._last_activity = clock()

    def begin(self) -> None:
        with self._lock:
            self._active_requests += 1

    def end(self) -> None:
        with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            self._last_activity = self._clock()

    def should_exit(self) -> bool:
        with self._lock:
            return (
                self.idle_timeout_seconds > 0
                and self._active_requests == 0
                and self._clock() - self._last_activity >= self.idle_timeout_seconds
            )


def _env(name: str, default: str) -> str:
    return str(os.getenv(name, default) or default).strip()


_ACTIVITY = RequestActivityTracker(float(_env("FUNASR_IDLE_TIMEOUT_SECONDS", "300") or "300"))


def _load_model() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        from funasr import AutoModel

        model_name = _env("FUNASR_MODEL", "paraformer-zh")
        device = _env("FUNASR_DEVICE", "cuda:0")
        ncpu = int(_env("FUNASR_NCPU", "6") or "6")
        kwargs: dict[str, Any] = {"model": model_name, "device": device, "ncpu": ncpu}

        vad_model = _env("FUNASR_VAD_MODEL", "fsmn-vad")
        if vad_model:
            kwargs["vad_model"] = vad_model
            kwargs["vad_kwargs"] = {"max_single_segment_time": int(_env("FUNASR_MAX_SEGMENT_MS", "60000") or "60000")}

        punc_model = _env("FUNASR_PUNC_MODEL", "ct-punc")
        if punc_model:
            kwargs["punc_model"] = punc_model

        spk_model = _env("FUNASR_SPK_MODEL", "")
        if spk_model:
            kwargs["spk_model"] = spk_model

        _MODEL = AutoModel(**kwargs)
        return _MODEL


def _model_status() -> dict[str, Any]:
    return {
        "model": _env("FUNASR_MODEL", "paraformer-zh"),
        "device": _env("FUNASR_DEVICE", "cuda:0"),
        "vad_model": _env("FUNASR_VAD_MODEL", "fsmn-vad"),
        "punc_model": _env("FUNASR_PUNC_MODEL", "ct-punc"),
        "spk_model": _env("FUNASR_SPK_MODEL", ""),
        "model_loaded": _MODEL is not None,
    }


def _extract_text(result: Any) -> str:
    parts: list[str] = []
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
    elif isinstance(result, dict):
        value = result.get("text")
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    elif isinstance(result, str):
        parts.append(result.strip())
    return " ".join(parts).strip()


def _extract_segments(result: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    rows = result if isinstance(result, list) else [result]
    for row in rows:
        if not isinstance(row, dict):
            continue
        sentence_info = row.get("sentence_info")
        if isinstance(sentence_info, list):
            for index, item in enumerate(sentence_info):
                if not isinstance(item, dict):
                    continue
                segments.append(
                    {
                        "id": len(segments),
                        "start": float(item.get("start") or item.get("beg") or 0) / 1000.0,
                        "end": float(item.get("end") or 0) / 1000.0,
                        "text": str(item.get("text") or "").strip(),
                        "speaker": item.get("spk"),
                    }
                )
        elif row.get("text"):
            segments.append({"id": len(segments), "start": 0.0, "end": 0.0, "text": str(row.get("text") or "").strip()})
    return segments


@APP.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "started_at": _STARTED_AT, **_model_status()}


@APP.get("/v1/models")
def models() -> dict[str, Any]:
    model_name = _env("FUNASR_MODEL", "paraformer-zh")
    return {
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": _STARTED_AT,
                "owned_by": "funasr",
                "root": model_name,
                "parent": None,
            }
        ],
    }


@APP.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form("paraformer-zh"),
    language: str = Form("zh"),
    response_format: str = Form("json"),
    prompt: str = Form(""),
    hotword: str = Form(""),
) -> Any:
    _ACTIVITY.begin()
    suffix = Path(file.filename or "audio.wav").suffix or ".wav"
    temp_path = Path(tempfile.mkstemp(prefix="kenradar_funasr_", suffix=suffix)[1])
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="empty audio file")
        temp_path.write_bytes(content)
        asr_model = _load_model()
        batch_size_s = int(_env("FUNASR_BATCH_SIZE_S", "300") or "300")
        batch_threshold_s = int(_env("FUNASR_BATCH_THRESHOLD_S", "60") or "60")
        options: dict[str, Any] = {
            "input": str(temp_path),
            "batch_size_s": batch_size_s,
            "batch_size_threshold_s": batch_threshold_s,
        }
        hotwords = hotword or prompt
        if hotwords:
            options["hotword"] = hotwords
        result = asr_model.generate(**options)
        text = _extract_text(result)
        if not text:
            raise HTTPException(status_code=502, detail="FunASR returned empty text")
        if response_format == "text":
            return PlainTextResponse(text)
        return {
            "text": text,
            "language": language,
            "duration": 0,
            "segments": _extract_segments(result),
            "model": model,
            "backend": "funasr",
            "raw_response": result,
        }
    finally:
        temp_path.unlink(missing_ok=True)
        _ACTIVITY.end()


def _monitor_idle_shutdown(server: uvicorn.Server) -> None:
    interval = min(1.0, max(0.1, _ACTIVITY.idle_timeout_seconds / 10))
    while not server.should_exit:
        time.sleep(interval)
        if _ACTIVITY.should_exit():
            server.should_exit = True
            return


def main() -> None:
    host = _env("FUNASR_HOST", "127.0.0.1")
    port = int(_env("FUNASR_PORT", "18002") or "18002")
    if _env("FUNASR_PRELOAD", "true").lower() in {"1", "true", "yes", "on"}:
        _load_model()
    config = uvicorn.Config(APP, host=host, port=port, log_level=_env("FUNASR_LOG_LEVEL", "info"))
    server = uvicorn.Server(config)
    if _ACTIVITY.idle_timeout_seconds > 0:
        threading.Thread(target=_monitor_idle_shutdown, args=(server,), name="funasr-idle-monitor", daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()
