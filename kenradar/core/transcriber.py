from __future__ import annotations

import asyncio
import base64
import gc
import json
import logging
import mimetypes
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

from kenradar.core.config import AppConfig
from kenradar.core.gpu_scheduler import GpuResourceManager
from kenradar.storage.database import Database
from kenradar.utils.text import sanitize_filename, truncate_filename_bytes

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, config: AppConfig, database: Database):
        self.config = config
        self.database = database
        self._model: Any = None
        self._batched_model: Any = None
        self._model_name = ""
        self._model_device = ""
        self.gpu = GpuResourceManager(config)

    def release_model(self) -> None:
        """Release cached Whisper model objects before switching GPU ownership."""
        self._model = None
        self._batched_model = None
        self._model_name = ""
        self._model_device = ""
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception as exc:
            logger.debug("释放 Whisper GPU 缓存时跳过 torch 清理: %s", exc)

    async def transcribe(self, aweme_id: str, video_path: Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.get("ai.whisper.enabled", True):
            return {"status": "skipped", "text": "", "text_path": "", "json_path": ""}

        metadata = metadata or {}
        if self.config.get("ai.funasr.enabled", False):
            funasr_result = await self._try_funasr(aweme_id, video_path, metadata)
            if funasr_result.get("status") == "success":
                return funasr_result
            if not self.config.get("ai.funasr.fallback_to_qwen_asr", True):
                return funasr_result
            logger.warning(
                "FunASR 转录未通过，回退 Qwen3-ASR: aweme_id=%s error=%s",
                aweme_id,
                funasr_result.get("error") or funasr_result.get("fail_reason") or "unknown",
            )

        if self.config.get("ai.qwen_asr.enabled", False):
            self._ensure_qwen_asr_available()
            qwen_result = await self._try_qwen_asr(aweme_id, video_path, metadata)
            if qwen_result.get("status") == "success":
                return qwen_result
            if not self.config.get("ai.qwen_asr.fallback_to_whisper", True):
                return qwen_result
            logger.warning(
                "Qwen3-ASR 转录失败，回退 Whisper: aweme_id=%s error=%s",
                aweme_id,
                qwen_result.get("error") or qwen_result.get("fail_reason") or "unknown",
            )

        model_name = str(self.config.get("transcribe.model", self.config.get("ai.whisper.model", "large-v3-turbo")))
        configured_device = str(self.config.get("transcribe.device", self.config.get("ai.whisper.device", "cpu")))
        device = self.gpu.choose_whisper_device(configured_device)
        language = str(self.config.get("ai.whisper.language", "zh"))
        backend = str(self.config.get("ai.whisper.backend", "openai-whisper") or "openai-whisper").strip().lower()
        started_at = time.monotonic()
        logger.info(
            "Whisper 转录开始: aweme_id=%s model=%s device=%s backend=%s compute_type=%s threads=%s vad=%s",
            aweme_id,
            model_name,
            device,
            backend,
            self._compute_type(device),
            self._cpu_threads(),
            self._vad_enabled(),
        )

        if device == "cuda":
            self.gpu.prepare_turbo_whisper_phase()

        try:
            self.database.upsert_transcript(
                aweme_id,
                "",
                "",
                "",
                f"{backend}:{model_name}",
                "running",
                "progress=0",
                language=language,
            )
            result = await asyncio.to_thread(self._transcribe_with_fallback, aweme_id, video_path, model_name, device, language, backend)
            raw_text = str(result.get("text", "")).strip()
            self._validate_transcript_text(raw_text, language)
            text = await self._correct_text(raw_text, metadata)
            self._validate_transcript_text(text, language)
            if text != raw_text:
                result["raw_text"] = raw_text
                result["text"] = text
                result["post_correction"] = {
                    "provider": str(self.config.get("ai.transcript_correction.provider", "ollama")),
                    "model": str(self.config.get("ai.transcript_correction.model", "")),
                }
            text_path, json_path = self._save_transcript_files(video_path, text, result)
            self.database.upsert_transcript(
                aweme_id,
                text,
                str(text_path) if text_path else "",
                str(json_path) if json_path else "",
                model_name,
                "success",
                segments_json=result,
                language=language,
            )
            elapsed = time.monotonic() - started_at
            logger.info(
                "Whisper 转录完成: aweme_id=%s duration=%.1fs elapsed=%.1fs rtf=%.2fx model=%s device=%s compute_type=%s batch_size=%s threads=%s vad=%s vad_retry=%s text_chars=%s",
                aweme_id,
                float(result.get("duration") or 0.0),
                elapsed,
                (float(result.get("duration") or 0.0) / elapsed) if elapsed > 0 else 0.0,
                model_name,
                device,
                str(result.get("compute_type") or self._compute_type(device)),
                int(result.get("batch_size") or self._batch_size(device)),
                self._cpu_threads(),
                bool(result.get("vad_filter")),
                bool(result.get("vad_retry")),
                len(text),
            )
            return {
                "status": "success",
                "text": text,
                "segments": result,
                "duration": result.get("duration"),
                "elapsed": elapsed,
                "model": model_name,
                "device": device,
                "compute_type": result.get("compute_type") or self._compute_type(device),
                "batch_size": result.get("batch_size") or self._batch_size(device),
                "vad_retry": bool(result.get("vad_retry")),
                "text_path": str(text_path) if text_path else "",
                "txt_path": str(text_path) if text_path else "",
                "json_path": str(json_path) if json_path else "",
            }
        except Exception as exc:
            fail_reason = self._classify_failure(exc)
            elapsed = time.monotonic() - started_at
            error = f"{fail_reason}: {exc}"
            self.database.upsert_transcript(aweme_id, "", "", "", f"{backend}:{model_name}", "failed", error)
            logger.warning(
                "Whisper 转录失败: aweme_id=%s elapsed=%.1fs model=%s device=%s compute_type=%s threads=%s fail_reason=%s error=%s",
                aweme_id,
                elapsed,
                model_name,
                device,
                self._compute_type(device),
                self._cpu_threads(),
                fail_reason,
                exc,
            )
            return {"status": "failed", "text": "", "error": error, "fail_reason": fail_reason, "text_path": "", "json_path": ""}

    def _ensure_qwen_asr_available(self) -> None:
        if not bool(self.config.get("ai.qwen_asr.start_on_fallback", False)):
            return
        endpoint = str(self.config.get("ai.qwen_asr.endpoint", "http://127.0.0.1:18001/v1") or "").rstrip("/")
        if endpoint:
            try:
                response = requests.get(f"{endpoint}/models", timeout=3)
                if response.ok:
                    return
            except Exception:
                pass
        container = str(self.config.get("ai.qwen_asr.container_name", "kenradar-qwen3-asr") or "").strip()
        if not container:
            return
        logger.info("FunASR 回退触发，按需启动 Qwen3-ASR 容器: container=%s", container)
        try:
            subprocess.run(["docker", "start", container], check=False, capture_output=True, text=True, timeout=30)
        except Exception as exc:
            logger.warning("启动 Qwen3-ASR 容器失败: container=%s error=%s", container, exc)
            return
        timeout = int(self.config.get("ai.qwen_asr.startup_wait_seconds", 180) or 180)
        deadline = time.monotonic() + max(5, timeout)
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{endpoint}/models", timeout=5)
                if response.ok:
                    logger.info("Qwen3-ASR 容器已可用: endpoint=%s", endpoint)
                    return
            except Exception:
                pass
            time.sleep(5)
        logger.warning("Qwen3-ASR 容器启动后未在超时时间内就绪: endpoint=%s timeout=%ss", endpoint, timeout)

    async def _try_funasr(self, aweme_id: str, video_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        started_at = time.monotonic()
        model_name = str(self.config.get("ai.funasr.model", "paraformer-zh") or "paraformer-zh")
        endpoint = str(self.config.get("ai.funasr.endpoint", "http://127.0.0.1:18002/v1") or "").rstrip("/")
        language = str(self.config.get("ai.funasr.language", self.config.get("ai.whisper.language", "zh")) or "zh")
        if not endpoint:
            return {"status": "failed", "text": "", "error": "funasr_endpoint_empty", "fail_reason": "funasr_unavailable"}
        logger.info("FunASR 转录开始: aweme_id=%s model=%s endpoint=%s", aweme_id, model_name, endpoint)
        try:
            self.database.upsert_transcript(
                aweme_id,
                "",
                "",
                "",
                f"funasr:{model_name}",
                "running",
                "progress=0",
                language=language,
            )
            result = await asyncio.to_thread(self._funasr_transcribe_sync, video_path, metadata)
            raw_text = str(result.get("text") or "").strip()
            self._validate_transcript_text(raw_text, language)
            self._validate_asr_quality(raw_text, metadata, "FunASR")
            text = await self._correct_text(raw_text, metadata)
            self._validate_transcript_text(text, language)
            self._validate_asr_quality(text, metadata, "FunASR")
            if text != raw_text:
                result["raw_text"] = raw_text
                result["text"] = text
                result["post_correction"] = {
                    "provider": str(self.config.get("ai.transcript_correction.provider", "ollama")),
                    "model": str(self.config.get("ai.transcript_correction.model", "")),
                }
            text_path, json_path = self._save_transcript_files(video_path, text, result)
            self.database.upsert_transcript(
                aweme_id,
                text,
                str(text_path) if text_path else "",
                str(json_path) if json_path else "",
                f"funasr:{model_name}",
                "success",
                segments_json=result,
                language=language,
            )
            elapsed = time.monotonic() - started_at
            logger.info("FunASR 转录完成: aweme_id=%s elapsed=%.1fs text_chars=%s", aweme_id, elapsed, len(text))
            return {
                "status": "success",
                "text": text,
                "segments": result,
                "duration": result.get("duration") or self._duration_seconds(metadata.get("duration")),
                "elapsed": elapsed,
                "model": f"funasr:{model_name}",
                "device": "server",
                "compute_type": "server",
                "batch_size": 1,
                "vad_retry": False,
                "text_path": str(text_path) if text_path else "",
                "txt_path": str(text_path) if text_path else "",
                "json_path": str(json_path) if json_path else "",
            }
        except Exception as exc:
            fail_reason = self._classify_funasr_failure(exc)
            elapsed = time.monotonic() - started_at
            error = f"{fail_reason}: {exc}"
            self.database.upsert_transcript(aweme_id, "", "", "", f"funasr:{model_name}", "failed", error)
            logger.warning("FunASR 转录失败: aweme_id=%s elapsed=%.1fs fail_reason=%s error=%s", aweme_id, elapsed, fail_reason, exc)
            return {"status": "failed", "text": "", "error": error, "fail_reason": fail_reason, "text_path": "", "json_path": ""}

    def _funasr_transcribe_sync(self, video_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(self.config.get("ai.funasr.endpoint", "http://127.0.0.1:18002/v1") or "").rstrip("/")
        model_name = str(self.config.get("ai.funasr.model", "paraformer-zh") or "paraformer-zh")
        timeout = int(self.config.get("ai.funasr.request_timeout", 300) or 300)
        language = str(self.config.get("ai.funasr.language", self.config.get("ai.whisper.language", "zh")) or "zh")
        prompt = str(self.config.get("ai.funasr.prompt", "") or self._initial_prompt() or "")
        url = endpoint if endpoint.endswith("/audio/transcriptions") else f"{endpoint}/audio/transcriptions"
        headers: dict[str, str] = {}
        api_key = str(self.config.get("ai.funasr.api_key", "") or os.getenv("FUNASR_API_KEY", "")).strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        data: dict[str, Any] = {"model": model_name, "language": language, "response_format": "json"}
        if prompt:
            data["prompt"] = prompt
            data["hotword"] = prompt
        upload_path = self._asr_upload_path(video_path, "funasr", "ai.funasr")
        try:
            with upload_path.open("rb") as file:
                response = requests.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (upload_path.name, file, mimetypes.guess_type(upload_path.name)[0] or "application/octet-stream")},
                    timeout=timeout,
                )
            response.raise_for_status()
            payload = response.json()
        finally:
            if upload_path != video_path:
                try:
                    upload_path.unlink(missing_ok=True)
                except OSError:
                    logger.debug("清理 FunASR 临时音频失败: %s", upload_path)
        text = self._extract_funasr_text(payload)
        if not text:
            raise ValueError("FunASR 未返回有效转录文本")
        return {
            "text": text,
            "segments": payload.get("segments") if isinstance(payload, dict) else [],
            "language": payload.get("language", language) if isinstance(payload, dict) else language,
            "duration": self._duration_seconds(metadata.get("duration")),
            "backend": "funasr",
            "model": model_name,
            "raw_response": payload,
        }

    async def _try_qwen_asr(self, aweme_id: str, video_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        started_at = time.monotonic()
        model_name = str(self.config.get("ai.qwen_asr.model", "Qwen/Qwen3-ASR-1.7B") or "Qwen/Qwen3-ASR-1.7B")
        endpoint = str(self.config.get("ai.qwen_asr.endpoint", "http://127.0.0.1:18001/v1") or "").rstrip("/")
        language = str(self.config.get("ai.qwen_asr.language", self.config.get("ai.whisper.language", "zh")) or "zh")
        if not endpoint:
            return {"status": "failed", "text": "", "error": "qwen_asr_endpoint_empty", "fail_reason": "qwen_asr_unavailable"}
        logger.info("Qwen3-ASR 转录开始: aweme_id=%s model=%s endpoint=%s", aweme_id, model_name, endpoint)
        try:
            self.database.upsert_transcript(
                aweme_id,
                "",
                "",
                "",
                f"qwen3-asr:{model_name}",
                "running",
                "progress=0",
                language=language,
            )
            result = await asyncio.to_thread(self._qwen_asr_transcribe_sync, video_path, metadata)
            raw_text = str(result.get("text") or "").strip()
            self._validate_transcript_text(raw_text, language)
            text = await self._correct_text(raw_text, metadata)
            self._validate_transcript_text(text, language)
            if text != raw_text:
                result["raw_text"] = raw_text
                result["text"] = text
                result["post_correction"] = {
                    "provider": str(self.config.get("ai.transcript_correction.provider", "ollama")),
                    "model": str(self.config.get("ai.transcript_correction.model", "")),
                }
            text_path, json_path = self._save_transcript_files(video_path, text, result)
            self.database.upsert_transcript(
                aweme_id,
                text,
                str(text_path) if text_path else "",
                str(json_path) if json_path else "",
                f"qwen3-asr:{model_name}",
                "success",
                segments_json=result,
                language=language,
            )
            elapsed = time.monotonic() - started_at
            logger.info("Qwen3-ASR 转录完成: aweme_id=%s elapsed=%.1fs text_chars=%s", aweme_id, elapsed, len(text))
            return {
                "status": "success",
                "text": text,
                "segments": result,
                "duration": result.get("duration") or self._duration_seconds(metadata.get("duration")),
                "elapsed": elapsed,
                "model": f"qwen3-asr:{model_name}",
                "device": "server",
                "compute_type": "server",
                "batch_size": 1,
                "vad_retry": False,
                "text_path": str(text_path) if text_path else "",
                "txt_path": str(text_path) if text_path else "",
                "json_path": str(json_path) if json_path else "",
            }
        except Exception as exc:
            fail_reason = self._classify_qwen_asr_failure(exc)
            elapsed = time.monotonic() - started_at
            error = f"{fail_reason}: {exc}"
            self.database.upsert_transcript(aweme_id, "", "", "", f"qwen3-asr:{model_name}", "failed", error)
            logger.warning("Qwen3-ASR 转录失败: aweme_id=%s elapsed=%.1fs fail_reason=%s error=%s", aweme_id, elapsed, fail_reason, exc)
            return {"status": "failed", "text": "", "error": error, "fail_reason": fail_reason, "text_path": "", "json_path": ""}

    def _qwen_asr_transcribe_sync(self, video_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(self.config.get("ai.qwen_asr.endpoint", "http://127.0.0.1:18001/v1") or "").rstrip("/")
        model_name = str(self.config.get("ai.qwen_asr.model", "Qwen/Qwen3-ASR-1.7B") or "Qwen/Qwen3-ASR-1.7B")
        timeout = int(self.config.get("ai.qwen_asr.request_timeout", 300) or 300)
        language = str(self.config.get("ai.qwen_asr.language", self.config.get("ai.whisper.language", "zh")) or "zh")
        prompt = str(self.config.get("ai.qwen_asr.prompt", "") or self._initial_prompt() or "")
        url = endpoint if endpoint.endswith("/audio/transcriptions") else f"{endpoint}/audio/transcriptions"
        headers: dict[str, str] = {}
        api_key = str(self.config.get("ai.qwen_asr.api_key", "") or os.getenv("QWEN_ASR_API_KEY", "")).strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        data: dict[str, Any] = {"model": model_name, "language": language, "response_format": "json"}
        if prompt:
            data["prompt"] = prompt
        upload_path = self._qwen_asr_upload_path(video_path)
        try:
            with upload_path.open("rb") as file:
                response = requests.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (upload_path.name, file, mimetypes.guess_type(upload_path.name)[0] or "application/octet-stream")},
                    timeout=timeout,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("Qwen3-ASR audio/transcriptions 接口失败，尝试 chat/completions audio_url: %s", exc)
            payload = self._qwen_asr_chat_completions_sync(video_path, headers, endpoint, model_name, timeout, language)
        finally:
            if upload_path != video_path:
                try:
                    upload_path.unlink(missing_ok=True)
                except OSError:
                    logger.debug("清理 Qwen3-ASR 临时音频失败: %s", upload_path)
        text = self._extract_qwen_asr_text(payload)
        if not text:
            raise ValueError("Qwen3-ASR 未返回有效转录文本")
        return {
            "text": text,
            "segments": payload.get("segments") if isinstance(payload, dict) else [],
            "language": payload.get("language", language) if isinstance(payload, dict) else language,
            "duration": self._duration_seconds(metadata.get("duration")),
            "backend": "qwen3-asr",
            "model": model_name,
            "raw_response": payload,
        }

    def _qwen_asr_upload_path(self, video_path: Path) -> Path:
        return self._asr_upload_path(video_path, "qwen_asr", "ai.qwen_asr")

    def _asr_upload_path(self, video_path: Path, prefix: str, config_prefix: str) -> Path:
        content_type = mimetypes.guess_type(video_path.name)[0] or ""
        if content_type.startswith("audio/") or video_path.suffix.lower() in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
            return video_path
        ffmpeg = str(self.config.get(f"{config_prefix}.ffmpeg_path", "ffmpeg") or "ffmpeg")
        temp_dir = Path(self.config.get("app.data_dir", "./data")) / "tmp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(prefix=f"{prefix}_", suffix=".wav", dir=temp_dir, delete=False)
        temp_path = Path(handle.name)
        handle.close()
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(video_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(temp_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=int(self.config.get(f"{config_prefix}.extract_timeout", 180) or 180),
            )
            if temp_path.stat().st_size <= 0:
                raise RuntimeError("抽取出的 WAV 文件为空")
            return temp_path
        except Exception as exc:
            temp_path.unlink(missing_ok=True)
            logger.warning("%s 抽取音频失败，改用原文件上传: video=%s error=%s", prefix, video_path, exc)
            return video_path

    def _qwen_asr_chat_completions_sync(
        self,
        video_path: Path,
        headers: dict[str, str],
        endpoint: str,
        model_name: str,
        timeout: int,
        language: str,
    ) -> dict[str, Any]:
        url = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
        content_type = mimetypes.guess_type(video_path.name)[0] or "application/octet-stream"
        encoded = base64.b64encode(video_path.read_bytes()).decode("ascii")
        audio_url = f"data:{content_type};base64,{encoded}"
        prompt = str(self.config.get("ai.qwen_asr.chat_prompt", "") or "<|zh|><|NEUTRAL|><|Speech|><|woitn|><|ASR|>")
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", **headers},
            json={
                "model": model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "audio_url", "audio_url": {"url": audio_url}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                "temperature": 0,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            payload.setdefault("language", language)
        return payload

    @staticmethod
    def _extract_qwen_asr_text(payload: Any) -> str:
        if isinstance(payload, str):
            return Transcriber._clean_qwen_asr_text(payload)
        if not isinstance(payload, dict):
            return ""
        for key in ("text", "transcription", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return Transcriber._clean_qwen_asr_text(value)
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message") if isinstance(first, dict) else {}
            content = message.get("content") if isinstance(message, dict) else first.get("text")
            if isinstance(content, str):
                return Transcriber._clean_qwen_asr_text(content)
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                return Transcriber._clean_qwen_asr_text("\n".join(parts))
        return ""

    @staticmethod
    def _extract_funasr_text(payload: Any) -> str:
        if isinstance(payload, str):
            return payload.strip()
        if not isinstance(payload, dict):
            return ""
        for key in ("text", "transcription", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return re.sub(r"\s+", " ", value).strip()
        result = payload.get("result") or payload.get("results")
        rows = result if isinstance(result, list) else [result]
        parts: list[str] = []
        for row in rows:
            if isinstance(row, dict) and isinstance(row.get("text"), str) and row["text"].strip():
                parts.append(row["text"].strip())
        return re.sub(r"\s+", " ", " ".join(parts)).strip()

    @staticmethod
    def _clean_qwen_asr_text(text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^\s*language\s+[A-Za-z\u4e00-\u9fff -]+\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"</?asr_text>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<\|[^|]{1,80}\|>", "", cleaned)
        cleaned = re.sub(r"^[\s,，。:：;；]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _classify_qwen_asr_failure(self, exc: BaseException | str) -> str:
        text = str(exc).lower()
        if "connection" in text or "refused" in text or "connect" in text:
            return "qwen_asr_unavailable"
        if "timeout" in text or "timed out" in text or "超时" in text:
            return "qwen_asr_timeout"
        if "404" in text or "not found" in text:
            return "qwen_asr_endpoint_not_found"
        if "empty" in text or "未返回有效转录文本" in text:
            return "qwen_asr_empty"
        return "qwen_asr_failed"

    def _classify_funasr_failure(self, exc: BaseException | str) -> str:
        text = str(exc).lower()
        if "connection" in text or "refused" in text or "connect" in text:
            return "funasr_unavailable"
        if "timeout" in text or "timed out" in text or "超时" in text:
            return "funasr_timeout"
        if "404" in text or "not found" in text:
            return "funasr_endpoint_not_found"
        if "empty" in text or "未返回有效转录文本" in text:
            return "funasr_empty"
        if "too short" in text or "过短" in text or "quality" in text or "质量" in text:
            return "funasr_quality_failed"
        return "funasr_failed"

    def _transcribe_with_fallback(self, aweme_id: str, video_path: Path, model_name: str, device: str, language: str, backend: str) -> dict[str, Any]:
        try:
            return self._transcribe_sync(aweme_id, video_path, model_name, device, language, backend)
        except Exception as exc:
            fallback = str(self.config.get("gpu_scheduler.whisper.fallback_device", "cpu") or "cpu").strip().lower()
            if device == "cuda" and fallback == "cpu" and self.gpu.is_oom_error(exc):
                logger.warning("Whisper GPU 转录疑似显存不足，自动降级 CPU 重试: video=%s error=%s", video_path, exc)
                self._model = None
                self._batched_model = None
                self._model_name = ""
                self._model_device = ""
                return self._transcribe_sync(aweme_id, video_path, model_name, "cpu", language, backend)
            raise

    def _transcribe_sync(self, aweme_id: str, video_path: Path, model_name: str, device: str, language: str, backend: str) -> dict[str, Any]:
        if backend in {"faster-whisper", "faster_whisper", "faster"}:
            return self._transcribe_faster_whisper_sync(aweme_id, video_path, model_name, device, language)
        import whisper

        def run() -> dict[str, Any]:
            if self._model is None or self._model_name != model_name or self._model_device != device:
                self._model = whisper.load_model(model_name, device=device)
                self._model_name = model_name
                self._model_device = device
            options: dict[str, Any] = {
                "language": language,
                "condition_on_previous_text": bool(self.config.get("ai.whisper.condition_on_previous_text", False)),
                "temperature": float(self.config.get("ai.whisper.temperature", 0) or 0),
                "fp16": device == "cuda",
            }
            initial_prompt = self._initial_prompt()
            if initial_prompt:
                options["initial_prompt"] = initial_prompt
            value = self._model.transcribe(str(video_path), **options)
            return value if isinstance(value, dict) else {"text": str(value)}

        if device == "cuda":
            with self.gpu.gpu_task(f"whisper:{video_path.name}"):
                result = run()
        else:
            result = run()
        return result if isinstance(result, dict) else {"text": str(result)}

    def _transcribe_faster_whisper_sync(self, aweme_id: str, video_path: Path, model_name: str, device: str, language: str) -> dict[str, Any]:
        self._configure_cpu_thread_env()
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        compute_type = self._compute_type(device)
        cpu_threads = self._cpu_threads()
        num_workers = int(self.config.get("ai.whisper.num_workers", 1) or 1)
        vad_filter = self._vad_enabled()
        batch_size = self._batch_size(device)

        if self._model is None or self._model_name != model_name or self._model_device != f"faster:{device}:{compute_type}":
            kwargs: dict[str, Any] = {"device": device, "compute_type": compute_type, "num_workers": max(1, num_workers)}
            if device == "cpu" and cpu_threads > 0:
                kwargs["cpu_threads"] = cpu_threads
            logger.info("加载 faster-whisper 模型: model=%s device=%s compute_type=%s batch_size=%s cpu_threads=%s num_workers=%s", model_name, device, compute_type, batch_size, cpu_threads, num_workers)
            self._model = WhisperModel(model_name, **kwargs)
            self._batched_model = BatchedInferencePipeline(self._model) if batch_size > 1 else None
            self._model_name = model_name
            self._model_device = f"faster:{device}:{compute_type}"

        def run(vad: bool) -> dict[str, Any]:
            if device == "cuda":
                with self.gpu.gpu_task(f"whisper:{video_path.name}"):
                    return self._run_faster_whisper(aweme_id, video_path, model_name, language, compute_type, vad, batch_size)
            return self._run_faster_whisper(aweme_id, video_path, model_name, language, compute_type, vad, batch_size)

        try:
            result = run(vad_filter)
        except Exception as exc:
            if vad_filter and not self.gpu.is_oom_error(exc):
                logger.warning("Whisper VAD 异常回退触发: aweme_id=%s error=%s", aweme_id, exc)
                result = run(False)
                result["vad_retry"] = True
            else:
                raise
        duration = float(result.get("duration") or 0.0)
        if vad_filter and self._transcript_too_short(str(result.get("text") or ""), duration):
            logger.warning(
                "Whisper VAD 回退触发: aweme_id=%s duration=%.1fs text_chars=%s",
                aweme_id,
                duration,
                len(str(result.get("text") or "")),
            )
            result = run(False)
            result["vad_retry"] = True
        return result

    def _run_faster_whisper(self, aweme_id: str, video_path: Path, model_name: str, language: str, compute_type: str, vad_filter: bool, batch_size: int) -> dict[str, Any]:
        vad_parameters = None
        if vad_filter:
            vad_parameters = {
                "min_silence_duration_ms": int(
                    self.config.get("transcribe.vad_min_silence_duration_ms", self.config.get("ai.whisper.vad_min_silence_duration_ms", 500))
                    or 500
                )
            }
        options = {
            "language": language,
            "initial_prompt": self._initial_prompt() or None,
            "vad_filter": vad_filter,
            "vad_parameters": vad_parameters,
            "condition_on_previous_text": bool(self.config.get("ai.whisper.condition_on_previous_text", False)),
            "temperature": float(self.config.get("ai.whisper.temperature", 0) or 0),
        }
        if self._batched_model is not None and not vad_filter:
            options["clip_timestamps"] = "0"
        if self._batched_model is not None:
            segments_iter, info = self._batched_model.transcribe(str(video_path), batch_size=batch_size, **options)
        else:
            segments_iter, info = self._model.transcribe(str(video_path), **options)
        duration = float(getattr(info, "duration", 0.0) or 0.0)
        segments: list[dict[str, Any]] = []
        text_parts: list[str] = []
        last_update = 0.0
        for segment in segments_iter:
            item = {
                "id": int(getattr(segment, "id", len(segments)) or len(segments)),
                "start": float(getattr(segment, "start", 0.0) or 0.0),
                "end": float(getattr(segment, "end", 0.0) or 0.0),
                "text": str(getattr(segment, "text", "") or ""),
            }
            segments.append(item)
            if item["text"].strip():
                text_parts.append(item["text"].strip())
            now = time.monotonic()
            if duration > 0 and now - last_update >= 15:
                progress = max(0, min(99, round(item["end"] / duration * 100)))
                self.database.upsert_transcript(
                    aweme_id,
                    "",
                    "",
                    "",
                    f"faster-whisper:{model_name}",
                    "running",
                    f"progress={progress}",
                    segments_json={"duration": duration, "segments_done": len(segments)},
                    language=language,
                    duration_seconds=duration,
                )
                last_update = now

        return {
            "text": " ".join(text_parts).strip(),
            "segments": segments,
            "language": getattr(info, "language", language),
            "duration": duration,
            "backend": "faster-whisper",
            "compute_type": compute_type,
            "batch_size": batch_size,
            "vad_filter": vad_filter,
            "vad_retry": False,
        }

    def _compute_type(self, device: str) -> str:
        value = str(self.config.get("transcribe.compute_type", self.config.get("ai.whisper.compute_type", "")) or "").strip()
        if str(device or "").lower() == "cpu" and value in {"float16", "int8_float16", "int8_float32"}:
            cpu_value = str(self.config.get("transcribe.cpu_compute_type", self.config.get("ai.whisper.cpu_compute_type", "int8")) or "int8").strip()
            return cpu_value or "int8"
        return value or ("float16" if device == "cuda" else "int8")

    def _cpu_threads(self) -> int:
        value = self.config.get("transcribe.cpu_threads_per_worker", self.config.get("ai.whisper.cpu_threads", 0))
        return max(0, int(value or 0))

    def _batch_size(self, device: str) -> int:
        if str(device or "").lower() != "cuda":
            return 1
        value = self.config.get("transcribe.batch_size", self.config.get("ai.whisper.batch_size", 1))
        return max(1, int(value or 1))

    def _vad_enabled(self) -> bool:
        return bool(self.config.get("transcribe.vad_filter", self.config.get("ai.whisper.vad_filter", False)))

    def _configure_cpu_thread_env(self) -> None:
        threads = self._cpu_threads()
        if threads > 0:
            os.environ["OMP_NUM_THREADS"] = str(threads)
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    @staticmethod
    def _transcript_too_short(text: str, duration_seconds: float) -> bool:
        compact = re.sub(r"\s+", "", str(text or ""))
        if not compact:
            return True
        if duration_seconds <= 0:
            return len(compact) < 20
        min_chars = max(30, min(500, int(duration_seconds * 0.35)))
        return len(compact) < min_chars

    def _classify_failure(self, exc: BaseException | str) -> str:
        text = str(exc).lower()
        if self.gpu.is_oom_error(exc):
            return "cuda_oom"
        if "target device or backend do not support" in text and any(token in text for token in ("float16", "int8_float16", "cuda")):
            return "cuda_oom"
        if "timeout" in text or "timed out" in text or "超时" in text:
            return "whisper_timeout"
        if "not found" in text or "no such file" in text or "不存在" in text:
            return "download_file_missing"
        if "empty" in text or "未产生有效转录文本" in text:
            return "empty_audio"
        if "too short" in text or "过短" in text:
            return "transcript_too_short"
        if "vad" in text:
            return "vad_retry_failed"
        if "audio" in text or "ffmpeg" in text:
            return "audio_extract_failed"
        if "whisper" in text:
            return "whisper_transcribe_failed"
        return "unknown_error"

    def _initial_prompt(self) -> str:
        value = self.config.get("ai.whisper.initial_prompt", "") or ""
        terms = self.config.get("ai.whisper.prompt_terms", []) or []
        parts: list[str] = []
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
        if isinstance(terms, str):
            terms = [item.strip() for item in re.split(r"[,，\n]", terms) if item.strip()]
        if isinstance(terms, list) and terms:
            clean_terms = [str(item).strip() for item in terms if str(item).strip()]
            if clean_terms:
                parts.append("常见投研术语：" + "、".join(clean_terms[:120]))
        return "\n".join(parts).strip()

    def _save_transcript_files(self, video_path: Path, text: str, result: dict[str, Any]) -> tuple[Path | None, Path | None]:
        text_path: Path | None = None
        json_path: Path | None = None
        sidecar_stem = self._sidecar_stem(video_path)
        if self.config.get("ai.whisper.save_txt", True):
            text_path = video_path.with_name(f"{sidecar_stem}.transcript.txt")
            text_path.write_text(text, encoding="utf-8")
        if self.config.get("ai.whisper.save_json", True):
            json_path = video_path.with_name(f"{sidecar_stem}.transcript.json")
            json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return text_path, json_path

    @staticmethod
    def _sidecar_stem(video_path: Path) -> str:
        stem = sanitize_filename(video_path.stem)
        match = re.search(r"(\d{12,})$", stem)
        suffix = f"_{match.group(1)}" if match else ""
        prefix_limit = 180 - len(suffix.encode("utf-8"))
        prefix = stem[: -len(suffix)] if suffix else stem
        return truncate_filename_bytes(prefix, max(40, prefix_limit), fallback="transcript") + suffix

    def _validate_transcript_text(self, text: str, language: str) -> None:
        value = str(text or "").strip()
        if not value:
            raise ValueError("Whisper 未产生有效转录文本")
        if str(language or "").lower() not in {"zh", "chinese", "cn"}:
            return
        compact = re.sub(r"\s+", "", value)
        if len(compact) < 40:
            return

        suspicious = len(re.findall(r"[\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff]", compact))
        cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", compact))
        ascii_word = len(re.findall(r"[A-Za-z0-9]", compact))
        useful = cjk + ascii_word
        suspicious_ratio = suspicious / max(len(compact), 1)
        useful_ratio = useful / max(len(compact), 1)
        repeated_noise = bool(re.search(r"(.{2,8})\1{4,}", compact))

        if suspicious_ratio >= 0.18 and useful_ratio < 0.82:
            raise ValueError(
                f"Whisper 转录疑似乱码，已拒绝写入成功状态: suspicious_ratio={suspicious_ratio:.2f}"
            )
        if repeated_noise and useful_ratio < 0.75:
            raise ValueError("Whisper 转录疑似重复幻觉文本，已拒绝写入成功状态")

    def _validate_asr_quality(self, text: str, metadata: dict[str, Any], provider: str) -> None:
        compact = re.sub(r"\s+", "", str(text or ""))
        duration = float(self._duration_seconds(metadata.get("duration")) or 0)
        min_chars = int(self.config.get("ai.funasr.quality_min_chars", 20) or 20)
        chars_per_min = float(self.config.get("ai.funasr.quality_min_chars_per_minute", 25) or 25)
        if len(compact) < min_chars:
            raise ValueError(f"{provider} 转录质量不足: text_chars={len(compact)} min_chars={min_chars}")
        if duration >= 30:
            expected = min(500, max(min_chars, int(duration / 60.0 * chars_per_min)))
            if len(compact) < expected:
                raise ValueError(f"{provider} 转录质量不足: text_chars={len(compact)} expected_min={expected} duration={duration:.1f}s")

    async def _correct_text(self, text: str, metadata: dict[str, Any]) -> str:
        if not text or not self.config.get("ai.transcript_correction.enabled", False):
            return text
        max_chars = int(self.config.get("ai.transcript_correction.max_chars", 8000) or 8000)
        if len(text) > max_chars:
            logger.info("转录文本过长，跳过 LLM 校正: chars=%s max=%s", len(text), max_chars)
            return text
        return await asyncio.to_thread(self._correct_text_sync, text, metadata)

    def _correct_text_sync(self, text: str, metadata: dict[str, Any]) -> str:
        endpoint = str(self.config.get("ai.transcript_correction.endpoint", "http://127.0.0.1:11434/v1") or "").rstrip("/")
        model = str(self.config.get("ai.transcript_correction.model", "qwen3.5:9b") or "qwen3.5:9b")
        timeout = int(self.config.get("ai.transcript_correction.request_timeout", 120) or 120)
        if not endpoint:
            return text
        url = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
        title = str(metadata.get("title") or "")
        terms = self._initial_prompt()
        prompt = (
            "/no_think\n"
            "请校正下面的视频转录文本，只修复明显错别字、投研术语、数字格式和标点。"
            "不要摘要，不要扩写，不要改变原意；无法确定就保留原文。只输出校正后的纯文本。\n\n"
            f"标题：{title}\n"
            f"{terms}\n\n"
            f"转录文本：\n{text}"
        )
        headers = {"Content-Type": "application/json"}
        api_key = str(self.config.get("ai.transcript_correction.api_key", "") or os.getenv("AI_TRANSCRIPT_CORRECTION_API_KEY", "")).strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            response = requests.post(
                url,
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": float(self.config.get("ai.transcript_correction.temperature", 0.1) or 0.1),
                    "max_tokens": int(self.config.get("ai.transcript_correction.max_tokens", 4096) or 4096),
                },
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message") if isinstance(choices[0], dict) else None
                content = message.get("content") if isinstance(message, dict) else ""
                if isinstance(content, str) and content.strip():
                    return self._clean_corrected_text(content)
        except Exception as exc:
            logger.warning("转录后校正失败，保留 Whisper 原文: %s", exc)
        return text

    @staticmethod
    def _clean_corrected_text(text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"^```(?:text)?\s*", "", text.strip())
        text = re.sub(r"\s*```$", "", text)
        return text.strip()

    @staticmethod
    def _duration_seconds(value: Any) -> int:
        try:
            duration = int(float(value or 0))
        except (TypeError, ValueError):
            return 0
        if duration > 10000:
            return max(1, round(duration / 1000))
        return max(0, duration)
