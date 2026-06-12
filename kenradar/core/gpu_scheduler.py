from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

from kenradar.core.config import AppConfig

logger = logging.getLogger(__name__)

_GPU_LOCK = threading.RLock()
_LOCK_PATH = Path(os.getenv("KENRADAR_GPU_LOCK", "/tmp/kenradar_gpu.lock"))


class GpuResourceManager:
    """Small in-process GPU coordinator for Whisper and local Ollama usage."""

    def __init__(self, config: AppConfig):
        self.config = config

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("gpu_scheduler.enabled", True))

    @property
    def mode(self) -> str:
        return str(self.config.get("gpu_scheduler.mode", "safe") or "safe").strip().lower()

    @contextmanager
    def gpu_task(self, name: str) -> Iterator[None]:
        if not self.enabled or not self.config.get("gpu_scheduler.lock.enabled", self.config.get("gpu_scheduler.gpu_lock", True)):
            yield
            return
        logger.info("等待 GPU 锁: task=%s", name)
        with _GPU_LOCK:
            with self._file_lock():
                logger.info("获得 GPU 锁: task=%s", name)
                try:
                    yield
                finally:
                    logger.info("释放 GPU 锁: task=%s", name)

    def choose_whisper_device(self, configured_device: str) -> str:
        configured = str(configured_device or "").strip().lower()
        default_device = str(
            self.config.get("gpu_scheduler.whisper.default_device", configured or self.config.get("ai.whisper.device", "cpu"))
            or "cpu"
        ).strip().lower()
        allow_gpu = bool(self.config.get("gpu_scheduler.whisper.allow_gpu", False))
        fallback = str(self.config.get("gpu_scheduler.whisper.fallback_device", "cpu") or "cpu").strip().lower()

        if not self.enabled:
            return configured or default_device or "cpu"
        if self.mode == "whisper_exclusive":
            if allow_gpu and configured == "cuda":
                return "cuda"
            logger.info("GPU 调度处于 whisper_exclusive，但 Whisper GPU 未启用，回退 CPU: configured=%s allow_gpu=%s", configured, allow_gpu)
            return "cpu"
        if self.mode == "safe":
            return "cpu"
        if self.mode in {"turbo", "time_division", "staged_gpu"}:
            if not allow_gpu:
                return default_device if default_device in {"cpu", "cuda"} else "cpu"
            if self.llm_is_loaded():
                logger.info("阶段式 GPU 转录准备卸载 Ollama 后使用 CUDA Whisper")
            return "cuda"
        if not allow_gpu:
            return default_device if default_device in {"cpu", "cuda"} else "cpu"
        if self.mode not in {"auto", "fast"}:
            return default_device if default_device in {"cpu", "cuda"} else "cpu"
        if self.mode == "fast":
            return "cuda"
        if self.llm_is_loaded():
            logger.info("Ollama 模型正在占用 GPU，Whisper 使用 CPU")
            return fallback
        min_free = int(self.config.get("gpu_scheduler.memory_check.min_free_vram_mb_for_whisper_gpu", 7000) or 7000)
        if self.free_vram_mb() < min_free:
            logger.info("GPU 空闲显存不足，Whisper 使用 CPU: free=%sMB min=%sMB", self.free_vram_mb(), min_free)
            return fallback
        return "cuda"

    def prepare_whisper_exclusive(self) -> None:
        if not self.enabled or self.mode != "whisper_exclusive":
            return
        if not bool(self.config.get("gpu_scheduler.whisper.allow_gpu", False)):
            raise RuntimeError("gpu_scheduler.mode=whisper_exclusive 需要 gpu_scheduler.whisper.allow_gpu=true")
        if bool(self.config.get("gpu_scheduler.ollama.stop_before_whisper_gpu", False)):
            self.unload_ollama_models()
            settle_seconds = float(self.config.get("gpu_scheduler.ollama.unload_wait_seconds", 3) or 0)
            if settle_seconds > 0:
                time.sleep(settle_seconds)
        min_free = int(self.config.get("gpu_scheduler.memory_check.min_free_vram_mb_for_whisper_gpu", 7000) or 7000)
        free_vram = self.free_vram_mb()
        if free_vram < min_free:
            raise RuntimeError(f"Whisper GPU 独占模式显存不足: free_vram={free_vram}MB min_required={min_free}MB")
        logger.info("Whisper GPU 独占模式显存检查通过: free_vram=%sMB min_required=%sMB", free_vram, min_free)

    def prepare_turbo_whisper_phase(self) -> None:
        if not self.enabled:
            return
        if not bool(self.config.get("gpu_scheduler.whisper.allow_gpu", False)):
            raise RuntimeError("阶段式 GPU 转录需要 gpu_scheduler.whisper.allow_gpu=true")
        if bool(self.config.get("gpu_scheduler.ollama.stop_before_whisper_gpu", True)):
            self.unload_ollama_models()
        settle_seconds = float(
            self.config.get(
                "gpu_scheduler.turbo.phase_switch_wait_seconds",
                self.config.get("gpu_scheduler.ollama.unload_wait_seconds", 3),
            )
            or 0
        )
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        min_free = int(self.config.get("gpu_scheduler.memory_check.min_free_vram_mb_for_whisper_gpu", 4000) or 4000)
        timeout = float(self.config.get("gpu_scheduler.turbo.phase_switch_timeout_seconds", 45) or 45)
        free_vram = self.wait_for_free_vram(min_free, timeout, "Whisper GPU 阶段")
        logger.info("阶段式 GPU 转录显存检查通过: free_vram=%sMB min_required=%sMB", free_vram, min_free)

    def prepare_turbo_llm_phase(self) -> None:
        if not self.enabled:
            return
        settle_seconds = float(self.config.get("gpu_scheduler.turbo.phase_switch_wait_seconds", 3) or 0)
        if settle_seconds > 0:
            time.sleep(settle_seconds)
        logger.info("准备进入 Ollama AI 阶段: free_vram=%sMB ollama_loaded=%s", self.free_vram_mb(), self.llm_is_loaded())

    def wait_for_free_vram(self, min_free_mb: int, timeout_seconds: float, reason: str) -> int:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        last_free = self.free_vram_mb()
        while last_free < min_free_mb and time.monotonic() < deadline:
            time.sleep(1.0)
            last_free = self.free_vram_mb()
        if last_free < min_free_mb:
            raise RuntimeError(f"{reason}显存不足: free_vram={last_free}MB min_required={min_free_mb}MB")
        return last_free

    def unload_ollama_models(self) -> None:
        try:
            models = self.ollama_ps()
        except Exception as exc:
            logger.warning("卸载 Ollama 模型前读取 /api/ps 失败: %s", exc)
            return
        if not models:
            logger.info("Ollama 当前没有已加载模型，无需卸载")
            return
        endpoint = str(
            self.config.get("gpu_scheduler.llm.endpoint")
            or self._ollama_provider().get("endpoint")
            or self.config.get("ai.organizer.endpoint", "http://127.0.0.1:11434/v1")
            or "http://127.0.0.1:11434/v1"
        )
        base_url = self._ollama_base_url(endpoint)
        for item in models:
            model = str(item.get("name") or item.get("model") or "").strip()
            if not model:
                continue
            try:
                response = requests.post(
                    f"{base_url}/api/generate",
                    headers={"Content-Type": "application/json"},
                    json={"model": model, "prompt": "", "stream": False, "keep_alive": 0},
                    timeout=15,
                )
                response.raise_for_status()
                logger.info("已请求卸载 Ollama 模型以释放 GPU: model=%s", model)
            except Exception as exc:
                logger.warning("卸载 Ollama 模型失败: model=%s error=%s", model, exc)

    def should_lock_llm(self, provider: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        if str(provider.get("api_type") or "").lower() != "ollama":
            return False
        return bool(self.config.get("gpu_scheduler.llm.exclusive_gpu", True))

    def llm_is_loaded(self) -> bool:
        try:
            models = self.ollama_ps()
        except Exception as exc:
            logger.debug("查询 Ollama /api/ps 失败: %s", exc)
            return False
        return bool(models)

    def ollama_ps(self) -> list[dict[str, Any]]:
        endpoint = str(
            self.config.get("gpu_scheduler.llm.endpoint")
            or self._ollama_provider().get("endpoint")
            or self.config.get("ai.organizer.endpoint", "http://127.0.0.1:11434/v1")
            or "http://127.0.0.1:11434/v1"
        )
        base_url = self._ollama_base_url(endpoint)
        response = requests.get(f"{base_url}/api/ps", timeout=5)
        response.raise_for_status()
        data = response.json()
        models = data.get("models") if isinstance(data, dict) else []
        return models if isinstance(models, list) else []

    def free_vram_mb(self) -> int:
        if not bool(self.config.get("gpu_scheduler.memory_check.enabled", True)):
            return 10**9
        query_tool = str(self.config.get("gpu_scheduler.memory_check.command") or ("nv" + "idia-smi"))
        try:
            output = subprocess.check_output(
                [
                    query_tool,
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                ],
                text=True,
                timeout=5,
            )
        except Exception as exc:
            logger.debug("GPU 显存查询失败: %s", exc)
            return 0
        values: list[int] = []
        for line in output.splitlines():
            try:
                values.append(int(line.strip()))
            except ValueError:
                continue
        return max(values) if values else 0

    def is_oom_error(self, exc: BaseException | str) -> bool:
        text = str(exc).lower()
        return any(
            marker in text
            for marker in (
                "out of memory",
                "cuda out of memory",
                "cublas",
                "cudnn",
                "failed to allocate",
                "oom",
                "显存不足",
            )
        )

    def _ollama_provider(self) -> dict[str, Any]:
        providers = self.config.get("ai.organizer.providers", []) or []
        if isinstance(providers, list):
            for provider in providers:
                if isinstance(provider, dict) and str(provider.get("api_type") or "").lower() == "ollama":
                    return provider
        return {}

    @staticmethod
    def _ollama_base_url(endpoint: str) -> str:
        parsed = urlparse(str(endpoint or "").rstrip("/"))
        if parsed.path.endswith("/v1"):
            return endpoint.rstrip("/")[:-3]
        if parsed.path.endswith("/api/chat"):
            return endpoint.rstrip()[: -len("/api/chat")]
        return endpoint.rstrip("/") or "http://127.0.0.1:11434"

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        scope = str(self.config.get("gpu_scheduler.lock.scope", "file") or "file").strip().lower()
        if scope != "file":
            yield
            return
        try:
            import fcntl

            _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.warning("GPU 文件锁不可用，降级为进程内锁: %s", exc)
            yield
            return
        with _LOCK_PATH.open("w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def gpu_policy_snapshot(config: AppConfig) -> dict[str, Any]:
    manager = GpuResourceManager(config)
    result = {
        "enabled": manager.enabled,
        "mode": manager.mode,
        "free_vram_mb": manager.free_vram_mb(),
        "ollama_models": [],
    }
    try:
        result["ollama_models"] = [
            {
                "name": str(model.get("name") or model.get("model") or ""),
                "size_vram": model.get("size_vram"),
            }
            for model in manager.ollama_ps()
        ]
    except Exception:
        result["ollama_models"] = []
    return json.loads(json.dumps(result, ensure_ascii=False, default=str))
