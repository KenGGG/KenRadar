from __future__ import annotations

import os
import re
import fcntl
import hashlib
import json
import logging
import time
import threading
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from kenradar.core.ai_json import parse_ai_json
from kenradar.core.config import AppConfig
from kenradar.core.gpu_scheduler import GpuResourceManager
from kenradar.utils.text import truncate_text

logger = logging.getLogger(__name__)


class ContentOrganizer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.last_error: str | None = None
        max_concurrent = max(1, int(self.config.get("ai.organizer.max_concurrent", 1) or 1))
        self._semaphore = threading.BoundedSemaphore(max_concurrent)
        self._rate_lock = threading.Lock()
        self._request_times: dict[str, deque[float]] = {}
        self.gpu = GpuResourceManager(config)

    def organize(self, title: str, transcript: str, metadata: dict[str, Any] | None = None) -> str:
        with self._semaphore:
            self.last_error = None
            if not transcript.strip():
                return "无可整理内容。"

            if not self.config.get("ai.organizer.enabled", True):
                return self._local_fallback(title, transcript)

            providers = self._organizer_providers()
            if not providers:
                return self._local_fallback(title, transcript)

            profile = self._analysis_profile(transcript, metadata or {})
            prompt = self._build_prompt(title, transcript, profile)
            errors: list[str] = []

            for index, provider in enumerate(providers, start=1):
                name = str(provider.get("name") or f"provider-{index}")
                api_key = self._provider_api_key(provider)
                if self._provider_requires_api_key(provider) and not api_key:
                    errors.append(f"{name}: missing api key")
                    logger.warning("AI provider 缺少 API Key，已跳过: %s", name)
                    continue
                try:
                    provider_transcript = self._provider_transcript(provider, transcript)
                    provider_prompt = self._provider_prompt(provider, title, provider_transcript, prompt if provider_transcript == transcript else self._build_prompt(title, provider_transcript, profile))
                    text = self._organize_with_provider(provider, api_key, provider_prompt).strip()
                    if text:
                        self._validate_provider_output(text, provider_transcript)
                        if index > 1:
                            logger.info("AI 整理已切换备用 provider 成功: %s", name)
                        return text
                    errors.append(f"{name}: empty response")
                    logger.warning("AI provider 返回空内容，尝试下一个: %s", name)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    if isinstance(exc, requests.RequestException):
                        logger.warning("AI provider 不可用，尝试下一个: provider=%s title=%s error=%s", name, title, exc)
                    else:
                        logger.exception("AI provider 整理失败，尝试下一个: provider=%s title=%s", name, title)

            error_text = "; ".join(errors) if errors else "AI 整理失败"
            fallback = self._local_fallback(title, transcript)
            self.last_error = error_text
            if self.config.get("ai.organizer.fallback_note", True):
                logger.error("全部 AI provider 不可用，已生成本地降级整理: %s", error_text)
                return fallback
            return f"> AI 整理失败，已保留本地基础整理。错误：{self.last_error}\n\n{fallback}"

    @staticmethod
    def _validate_provider_output(text: str, transcript: str) -> None:
        parsed = parse_ai_json(text)
        if not parsed:
            raise ValueError("AI 返回内容不是可解析的 JSON 对象")
        value = (
            parsed.get("corrected_transcript_sections")
            or parsed.get("corrected_transcript")
            or parsed.get("transcript_sections")
        )
        if isinstance(value, dict):
            value = [value]
        sections = value if isinstance(value, list) else []
        corrected_parts: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            content = section.get("content") or section.get("text") or section.get("paragraph")
            if isinstance(content, str) and content.strip():
                corrected_parts.append(content.strip())

        original_length = len(re.sub(r"\s+", "", str(transcript or "")))
        corrected_length = sum(len(re.sub(r"\s+", "", part)) for part in corrected_parts)
        if not corrected_parts:
            raise ValueError("AI 未生成纠错分段原文")
        if original_length >= 200 and corrected_length < original_length * 0.65:
            coverage = corrected_length / max(original_length, 1)
            raise ValueError(
                f"AI 纠错分段覆盖不足: corrected_chars={corrected_length} "
                f"original_chars={original_length} coverage={coverage:.0%} required=65%"
            )

    def _organize_with_provider(self, provider: dict[str, Any], api_key: str, prompt: str) -> str:
        model = str(provider.get("model") or self.config.get("ai.organizer.model", "gpt-5-mini") or "gpt-5-mini")
        endpoint = str(provider.get("endpoint") or self.config.get("ai.organizer.endpoint", "https://api.openai.com/v1/responses") or "").strip()
        api_type = str(provider.get("api_type") or self.config.get("ai.organizer.api_type", "") or "").strip()
        rpm_limit = self._provider_rpm_limit(provider)
        rate_limit_key = self._provider_rate_limit_key(provider, model)
        timeout = max(
            5,
            int(provider.get("request_timeout") or self.config.get("ai.organizer.request_timeout", self.config.get("ai.organizer.timeout", 120)) or 120),
        )
        if api_type == "ollama":
            if self.gpu.should_lock_llm(provider):
                min_free = int(self.config.get("gpu_scheduler.memory_check.min_free_vram_mb_for_llm", 9000) or 9000)
                free_vram = self.gpu.free_vram_mb()
                logger.info("准备调用 Ollama LLM: model=%s free_vram=%sMB min=%sMB", model, free_vram, min_free)
                with self.gpu.gpu_task(f"ollama:{model}"):
                    return self._organize_with_ollama_native(endpoint, model, prompt, timeout, provider, rpm_limit, rate_limit_key).strip()
            return self._organize_with_ollama_native(endpoint, model, prompt, timeout, provider, rpm_limit, rate_limit_key).strip()
        if self._is_chat_completions(endpoint, api_type):
            return self._organize_with_chat_completions(endpoint, api_key, model, prompt, timeout, provider, rpm_limit, rate_limit_key).strip()
        response = self._post_with_retry(
            endpoint,
            headers=self._provider_headers(api_key),
            json={
                "model": model,
                "instructions": (
                    "你是中文投资研究助理。你的任务是把口语化视频转录整理成结构化 JSON。"
                    "保留原文含义，不编造股票、数据或结论；无法确定的内容要标注为原文表述。"
                    "只输出 JSON 对象，不输出 Markdown、YAML 或解释文字。"
                ),
                "input": prompt,
                **self._sampling_options(provider),
            },
            timeout=timeout,
            attempts=int(provider.get("retry_count") or self.config.get("ai.organizer.retry_count", 3) or 3),
            retry_delay=float(provider.get("retry_delay") or self.config.get("ai.organizer.retry_delay", 2) or 2),
            rpm_limit=rpm_limit,
            rate_limit_key=rate_limit_key,
        )
        response.raise_for_status()
        data = response.json()
        return self._extract_response_text(data).strip()

    def _organize_with_ollama_native(
        self,
        endpoint: str,
        model: str,
        prompt: str,
        timeout: int,
        provider: dict[str, Any],
        rpm_limit: int,
        rate_limit_key: str,
    ) -> str:
        base_url = self._ollama_base_url(endpoint)
        self._ensure_ollama_gpu_ready(base_url, model, provider)
        url = f"{base_url}/api/chat"
        messages = [{"role": "user", "content": prompt}]
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": "json",
            "keep_alive": str(provider.get("keep_alive") or self.config.get("gpu_scheduler.llm.keep_alive", "10m") or "10m"),
            "options": self._ollama_options(provider),
        }
        response = self._post_with_retry(
            url,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
            attempts=int(provider.get("retry_count") or self.config.get("ai.organizer.retry_count", 3) or 3),
            retry_delay=float(provider.get("retry_delay") or self.config.get("ai.organizer.retry_delay", 2) or 2),
            rpm_limit=rpm_limit,
            rate_limit_key=rate_limit_key,
        )
        response.raise_for_status()
        data = response.json()
        message = data.get("message") if isinstance(data, dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"].strip()
        return ""

    def _ollama_base_url(self, endpoint: str) -> str:
        parsed = urlparse(endpoint.rstrip("/"))
        if parsed.path.endswith("/v1"):
            return endpoint.rstrip("/")[:-3]
        if parsed.path.endswith("/api/chat"):
            return endpoint.rstrip()[: -len("/api/chat")]
        if parsed.path.endswith("/api/generate"):
            return endpoint.rstrip()[: -len("/api/generate")]
        return endpoint.rstrip("/")

    def _ollama_options(self, provider: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {
            "num_predict": int(provider.get("max_tokens") or self.config.get("ai.organizer.max_tokens", 2048) or 2048),
            "temperature": float(provider.get("temperature") or self.config.get("ai.organizer.temperature", 0.2) or 0.2),
        }
        num_gpu = provider.get("num_gpu", self.config.get("gpu_scheduler.llm.num_gpu"))
        if num_gpu not in (None, ""):
            options["num_gpu"] = int(num_gpu)
        main_gpu = provider.get("main_gpu", self.config.get("gpu_scheduler.llm.main_gpu"))
        if main_gpu not in (None, ""):
            options["main_gpu"] = int(main_gpu)
        return options

    def _ensure_ollama_gpu_ready(self, base_url: str, model: str, provider: dict[str, Any]) -> None:
        require_gpu = bool(provider.get("require_gpu", self.config.get("gpu_scheduler.llm.require_gpu", False)))
        if not require_gpu:
            return
        if self._ollama_model_vram_mb(base_url, model) > 0:
            return

        min_free = int(self.config.get("gpu_scheduler.memory_check.min_free_vram_mb_for_llm", 9000) or 9000)
        free_vram = self.gpu.free_vram_mb()
        if self._ollama_model_loaded(base_url, model):
            logger.warning("Ollama 模型当前未使用 GPU，先卸载 CPU runner 后重试: model=%s free_vram=%sMB", model, free_vram)
            self._unload_ollama_model(base_url, model)
            time.sleep(float(self.config.get("gpu_scheduler.ollama.unload_wait_seconds", 3) or 0))
            free_vram = self.gpu.free_vram_mb()
        if free_vram < min_free:
            raise RuntimeError(
                "Ollama GPU 强制模式已启用，但当前空闲显存不足，已阻止 CPU 降级加载。"
                f" model={model} free_vram={free_vram}MB min_required={min_free}MB；"
                "请先停止 Qwen3-ASR/Whisper 等占用 GPU 的任务后再恢复 AI 队列。"
            )

        load_timeout = max(5, int(provider.get("gpu_check_timeout") or self.config.get("gpu_scheduler.llm.gpu_check_timeout", 30) or 30))
        keep_alive = str(provider.get("keep_alive") or self.config.get("gpu_scheduler.llm.keep_alive", "10m") or "10m")
        options = self._ollama_options(provider)
        options["num_predict"] = 1
        options["temperature"] = 0
        response = requests.post(
            f"{base_url}/api/generate",
            headers={"Content-Type": "application/json"},
            json={
                "model": model,
                "prompt": "OK",
                "stream": False,
                "keep_alive": keep_alive,
                "options": options,
            },
            timeout=load_timeout,
        )
        response.raise_for_status()
        vram_mb = self._ollama_model_vram_mb(base_url, model)
        if vram_mb <= 0:
            raise RuntimeError(
                "Ollama GPU 强制模式已启用，但模型未使用 GPU。"
                f" model={model} size_vram=0；请修复 Docker Ollama 的 NVIDIA/CUDA 运行环境后再恢复 AI 队列。"
            )
        logger.info("Ollama GPU 检查通过: model=%s size_vram=%sMB", model, vram_mb)

    @staticmethod
    def _ollama_model_loaded(base_url: str, model: str) -> bool:
        try:
            response = requests.get(f"{base_url}/api/ps", timeout=5)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Ollama GPU 检查失败，无法读取 /api/ps: %s", exc)
            return False
        models = data.get("models") if isinstance(data, dict) else []
        if not isinstance(models, list):
            return False
        for item in models:
            if not isinstance(item, dict):
                continue
            loaded_name = str(item.get("name") or item.get("model") or "")
            if loaded_name == model:
                return True
        return False

    @staticmethod
    def _unload_ollama_model(base_url: str, model: str) -> None:
        response = requests.post(
            f"{base_url}/api/generate",
            headers={"Content-Type": "application/json"},
            json={"model": model, "prompt": "", "stream": False, "keep_alive": 0},
            timeout=15,
        )
        response.raise_for_status()

    @staticmethod
    def _ollama_model_vram_mb(base_url: str, model: str) -> int:
        try:
            response = requests.get(f"{base_url}/api/ps", timeout=5)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning("Ollama GPU 检查失败，无法读取 /api/ps: %s", exc)
            return 0
        models = data.get("models") if isinstance(data, dict) else []
        if not isinstance(models, list):
            return 0
        for item in models:
            if not isinstance(item, dict):
                continue
            loaded_name = str(item.get("name") or item.get("model") or "")
            if loaded_name == model:
                try:
                    return int(float(item.get("size_vram") or 0) / 1024 / 1024)
                except (TypeError, ValueError):
                    return 0
        return 0

    def _organize_with_chat_completions(
        self,
        endpoint: str,
        api_key: str,
        model: str,
        prompt: str,
        timeout: int,
        provider: dict[str, Any] | None = None,
        rpm_limit: int | None = None,
        rate_limit_key: str | None = None,
    ) -> str:
        url = endpoint.rstrip("/")
        if not url.endswith("/chat/completions"):
            url = f"{url}/chat/completions"
        provider = provider or {}
        system_prompt = (
            "你是中文投资研究助理。你的任务是把口语化视频转录整理成结构化 JSON。"
            "保留原文含义，不编造股票、数据或结论；无法确定的内容要标注为原文表述。"
            "只输出 JSON 对象，不输出 Markdown、YAML 或解释文字。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        if provider.get("no_think"):
            messages[-1]["content"] = f"/no_think\n{messages[-1]['content']}"
        if provider.get("system_as_user"):
            user_prompt = f"{system_prompt}\n\n{prompt}"
            if provider.get("no_think"):
                user_prompt = f"/no_think\n{user_prompt}"
            messages = [{"role": "user", "content": user_prompt}]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            **self._sampling_options(provider),
            "max_tokens": int(provider.get("max_tokens") or self.config.get("ai.organizer.max_tokens", 2048) or 2048),
        }
        if provider.get("no_think"):
            payload["think"] = False
        response = self._post_with_retry(
            url,
            headers=self._provider_headers(api_key),
            json=payload,
            timeout=timeout,
            attempts=int(provider.get("retry_count") or self.config.get("ai.organizer.retry_count", 3) or 3),
            retry_delay=float(provider.get("retry_delay") or self.config.get("ai.organizer.retry_delay", 2) or 2),
            rpm_limit=rpm_limit,
            rate_limit_key=rate_limit_key or self._provider_rate_limit_key(provider, model),
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                content = self._strip_thinking(message["content"])
                if content:
                    return content
        return ""

    def _organizer_providers(self) -> list[dict[str, Any]]:
        organizer = self.config.get("ai.organizer", {}) or {}
        raw_providers = organizer.get("providers")
        providers: list[dict[str, Any]] = []
        if isinstance(raw_providers, list):
            for item in raw_providers:
                if isinstance(item, dict) and item.get("enabled", True):
                    providers.append(dict(item))
        if providers:
            return providers
        legacy = {
            "name": "primary",
            "enabled": True,
            "api_type": organizer.get("api_type", "chat_completions"),
            "endpoint": organizer.get("endpoint", "https://api.openai.com/v1"),
            "model": organizer.get("model", "gpt-5-mini"),
            "api_key": organizer.get("api_key", ""),
            "env_var": organizer.get("env_var", "OPENAI_API_KEY"),
            "request_timeout": organizer.get("request_timeout", organizer.get("timeout", 120)),
            "max_tokens": organizer.get("max_tokens", 2048),
            "temperature": organizer.get("temperature", 0.2),
            "top_p": organizer.get("top_p"),
            "top_k": organizer.get("top_k"),
            "rpm_limit": organizer.get("rpm_limit", 0),
        }
        return [legacy]

    @staticmethod
    def _provider_requires_api_key(provider: dict[str, Any]) -> bool:
        if "requires_api_key" in provider:
            return bool(provider.get("requires_api_key"))
        endpoint = str(provider.get("endpoint") or "").strip().lower()
        return not (
            endpoint.startswith("http://127.0.0.1")
            or endpoint.startswith("http://localhost")
            or endpoint.startswith("http://0.0.0.0")
        )

    @staticmethod
    def _provider_headers(api_key: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _provider_api_key(self, provider: dict[str, Any]) -> str:
        env_var = str(provider.get("env_var") or "").strip()
        if env_var:
            env_value = os.getenv(env_var, "").strip()
            if env_value:
                return env_value
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_var):
                return env_var
        if not env_var:
            env_value = os.getenv("OPENAI_API_KEY", "").strip()
            if env_value:
                return env_value
        provider_key = str(provider.get("api_key") or "").strip()
        if provider_key:
            return provider_key
        if str(provider.get("name") or "").strip().lower() in {"primary", "主 api", "主api"}:
            return str(self.config.get("ai.organizer.api_key", "") or "").strip()
        return ""

    def _sampling_options(self, provider: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": float(provider.get("temperature") or self.config.get("ai.organizer.temperature", 0.2) or 0.2),
        }
        top_p = provider.get("top_p", self.config.get("ai.organizer.top_p"))
        top_k = provider.get("top_k", self.config.get("ai.organizer.top_k"))
        if top_p not in (None, ""):
            options["top_p"] = float(top_p)
        if not provider.get("omit_top_k") and top_k not in (None, ""):
            options["top_k"] = int(top_k)
        return options

    def _post_with_retry(self, url: str, **kwargs: Any) -> requests.Response:
        attempts = max(1, int(kwargs.pop("attempts", self.config.get("ai.organizer.retry_count", 3)) or 3))
        delay = max(0.5, float(kwargs.pop("retry_delay", self.config.get("ai.organizer.retry_delay", 2)) or 2))
        rpm_limit = kwargs.pop("rpm_limit", None)
        rate_limit_key = str(kwargs.pop("rate_limit_key", "") or "default")
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                self._wait_for_rate_limit(rpm_limit, rate_limit_key)
                response = requests.post(url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_exc = exc
                if attempt >= attempts or not self._is_retryable_request_error(exc):
                    raise
                wait_seconds = delay * attempt
                logger.warning("AI 整理请求临时失败，%s 秒后重试 %s/%s: %s", wait_seconds, attempt + 1, attempts, exc)
                time.sleep(wait_seconds)
        if last_exc:
            raise last_exc
        raise RuntimeError("AI 整理请求失败")

    def _wait_for_rate_limit(self, rpm_limit: int | None = None, key: str = "default") -> None:
        if rpm_limit is None:
            rpm_limit = int(self.config.get("ai.organizer.rpm_limit", 0) or 0)
        if rpm_limit <= 0:
            return
        if self._wait_for_shared_rate_limit(rpm_limit, key):
            return
        while True:
            with self._rate_lock:
                now = time.monotonic()
                request_times = self._request_times.setdefault(key, deque())
                while request_times and now - request_times[0] >= 60:
                    request_times.popleft()
                if len(request_times) < rpm_limit:
                    request_times.append(now)
                    return
                sleep_for = max(0.5, 60 - (now - request_times[0]))
            logger.info("AI 整理触发 RPM 限流，provider=%s limit=%s，等待 %.1f 秒", key, rpm_limit, sleep_for)
            time.sleep(sleep_for)

    def _wait_for_shared_rate_limit(self, rpm_limit: int, key: str) -> bool:
        try:
            rate_dir = Path(str(self.config.get("app.data_dir", "./data") or "./data")) / "runtime" / "rate_limits"
            rate_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
            path = rate_dir / f"ai_{digest}.json"
            while True:
                with path.open("a+", encoding="utf-8") as handle:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    handle.seek(0)
                    try:
                        raw = json.load(handle)
                    except json.JSONDecodeError:
                        raw = []
                    now = time.time()
                    request_times = [float(item) for item in raw if isinstance(item, (int, float)) and now - float(item) < 60]
                    if len(request_times) < rpm_limit:
                        request_times.append(now)
                        handle.seek(0)
                        handle.truncate()
                        json.dump(request_times, handle)
                        handle.flush()
                        os.fsync(handle.fileno())
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                        return True
                    sleep_for = max(0.5, 60 - (now - request_times[0]))
                    handle.seek(0)
                    handle.truncate()
                    json.dump(request_times, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                logger.info("AI 整理触发共享 RPM 限流，provider=%s limit=%s，等待 %.1f 秒", key, rpm_limit, sleep_for)
                time.sleep(sleep_for)
        except Exception as exc:
            logger.warning("共享 RPM 限流不可用，回退到进程内限流: provider=%s error=%s", key, exc)
            return False

    def _provider_rpm_limit(self, provider: dict[str, Any]) -> int:
        raw_limit = provider.get("rpm_limit", self.config.get("ai.organizer.rpm_limit", 0))
        try:
            return max(0, int(raw_limit or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _provider_rate_limit_key(provider: dict[str, Any], model: str) -> str:
        endpoint = str(provider.get("endpoint") or "").strip().rstrip("/")
        name = str(provider.get("name") or provider.get("api_type") or "provider").strip()
        return f"{name}:{model}:{endpoint}"

    @staticmethod
    def _is_retryable_request_error(exc: requests.RequestException) -> bool:
        response = getattr(exc, "response", None)
        if response is None:
            return True
        try:
            status_code = int(response.status_code)
        except (TypeError, ValueError):
            return True
        return status_code == 429 or status_code >= 500

    @staticmethod
    def _is_chat_completions(endpoint: str, api_type: str) -> bool:
        if api_type == "chat_completions":
            return True
        if api_type == "responses":
            return False
        normalized = endpoint.rstrip("/")
        return normalized.endswith("/v1") or normalized.endswith("/chat/completions")

    @staticmethod
    def _strip_thinking(text: str) -> str:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"^\s*<think>.*", "", text, flags=re.DOTALL | re.IGNORECASE)
        return text.strip()

    def _analysis_profile(self, transcript: str, metadata: dict[str, Any]) -> dict[str, Any]:
        duration = self._duration_seconds(metadata.get("duration") or metadata.get("duration_seconds"))
        text_len = len(transcript)
        if duration and duration < 120 or text_len < 1200:
            return {
                "kind": "short",
                "sections": "2 个",
                "section_words": "80-160 字",
                "summary_chars": 80,
                "extra": "短视频只提炼明确观点，不为凑篇幅扩写。",
            }
        if duration and duration > 600 or text_len > 6000:
            return {
                "kind": "long",
                "sections": "4-6 个",
                "section_words": "120-260 字",
                "summary_chars": 180,
                "extra": "长视频要覆盖主要论证链条，可按时间线或话题递进组织，避免遗漏中段内容。",
            }
        return {
            "kind": "normal",
            "sections": "3 个",
            "section_words": "100-250 字",
            "summary_chars": 100,
            "extra": "围绕核心观点组织，避免逐字复述。",
        }

    @staticmethod
    def _duration_seconds(value: Any) -> int:
        try:
            duration = int(float(value or 0))
        except (TypeError, ValueError):
            return 0
        if duration > 10000:
            duration = round(duration / 1000)
        return max(0, duration)

    @staticmethod
    def _build_prompt(title: str, transcript: str, profile: dict[str, Any] | None = None) -> str:
        profile = profile or {"sections": "3 个", "section_words": "100-250 字", "summary_chars": 100, "extra": ""}
        return f"""请整理下面这条视频转录，只输出一个 JSON 对象，不要输出 Markdown、YAML 或解释文字。要求：
- 只根据转录原文整理，不编造事实、公司、数据或结论。
- brief_title 不超过 30 个中文字符，不要直接照搬原标题。
- brief_summary 不超过 {int(profile.get("summary_chars") or 100)} 个中文字符，不要复制大段原标题，不要塞入 Whisper 原文。
- content_sections 建议 {profile.get("sections") or "3 个"}小节。
- content_sections[].title 必须是判断性、概括性短句，不超过 30 个中文字符，不要写“观点一”“核心观点”等空泛标题。
- content_sections[].content 每段 {profile.get("section_words") or "100-250 字"}，围绕小节观点展开，不逐字复述转录。
- corrected_transcript_sections 必须覆盖所提供转录原文的全部有效内容，按话题转换自然分段，每段对应一个对象。
- corrected_transcript_sections[].title 是该段原文的简短主题标题，不超过 20 个中文字符。
- corrected_transcript_sections[].content 必须保持博主原意、论述顺序、数字和观点，只修正明显错别字、同音字、ASR 识别错误、标点和断句。
- corrected_transcript_sections[].content 不是摘要，不得压缩、改写、扩写、补充事实或删除重要表达；无法确认的专有名词保留原转录写法。
- 无法确定的内容写“原文未明确说明”。
- tags 输出 1-5 个主题标签，优先从 AI产业、半导体、融资租赁、国企改革、宏观经济、股票市场、房地产、算力中心、新能源车、其他 中选择；必要时可补充更具体标签。
- importance_score、novelty_score、information_density、business_relevance 都是 1-5 的整数，5 代表最高。
- value_score 是综合价值评分，1-5，可保留 1 位小数。
- recommended_action 只能是 push、archive、review、research 之一：push 表示适合进入简报，review 表示值得人工阅读，research 表示建议深挖，archive 表示仅归档。
- recommendation_reason 不超过 80 个中文字符，只解释推荐动作原因。
- deep_research_suggested 是布尔值。
- {profile.get("extra") or "围绕核心观点组织，避免逐字复述。"}

JSON 结构：
{{
  "brief_title": "不超过30个中文字符的简报标题",
  "brief_summary": "不超过100个中文字符的简报简介",
  "content_sections": [
    {{"title": "观点小标题1", "content": "围绕观点小标题1展开的说明"}},
    {{"title": "观点小标题2", "content": "围绕观点小标题2展开的说明"}},
    {{"title": "观点小标题3", "content": "围绕观点小标题3展开的说明"}}
  ],
  "corrected_transcript_sections": [
    {{"title": "这一段原文的主题", "content": "保持博主原意、仅修正错别字和断句后的完整段落"}},
    {{"title": "下一段原文的主题", "content": "保持博主原意、仅修正错别字和断句后的完整段落"}}
  ],
  "content_category": "内容分类",
  "importance_level": "高/中/低",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "tags": ["AI产业", "算力中心"],
  "importance_score": 4,
  "novelty_score": 4,
  "information_density": 4,
  "business_relevance": 4,
  "value_score": 4.0,
  "recommended_action": "push",
  "recommendation_reason": "内容包含明确产业变化或投资研究线索",
  "deep_research_suggested": false
}}

标题：{title}

转录原文：
{transcript}
"""

    @staticmethod
    def _provider_prompt(provider: dict[str, Any], title: str, transcript: str, default_prompt: str) -> str:
        if not provider.get("compact_prompt"):
            return default_prompt
        return f"""只输出一个 JSON 对象，不要解释，不要输出思考过程。
JSON 字段必须包含：brief_title、brief_summary、content_sections、corrected_transcript_sections、content_category、importance_level、keywords、tags、importance_score、novelty_score、information_density、business_relevance、value_score、recommended_action、recommendation_reason、deep_research_suggested。
content_sections 必须是数组，使用 2-5 项；数组里的每一项都必须是对象，且只能包含 title 和 content 两个字段。
每个小节都必须写成 {{"title": "小标题", "content": "说明文字"}}，不要把 title/content 直接裸写在数组里，不要在小节对象里再嵌套 content_sections。
corrected_transcript_sections 必须覆盖所提供原文的全部有效内容，按话题自然分段；每项只能包含 title 和 content。
corrected_transcript_sections.content 保持原意和顺序，只修正明显错别字、ASR 识别错误、标点与断句，不得摘要、删减、扩写或补充事实。
只根据原文整理，无法确定写“原文未明确说明”。
评分字段使用 1-5；recommended_action 只能是 push、archive、review、research。

标题：{title}

转录原文：
{transcript}
"""

    @staticmethod
    def _provider_transcript(provider: dict[str, Any], transcript: str) -> str:
        max_chars = int(provider.get("max_input_chars") or 0)
        if max_chars <= 0 or len(transcript) <= max_chars:
            return transcript
        head = max_chars * 2 // 3
        tail = max_chars - head
        return (
            transcript[:head].rstrip()
            + "\n\n[中间转录过长，已为本地兜底模型截断。请基于保留片段提炼核心内容，不能确定的部分写原文未明确说明。]\n\n"
            + transcript[-tail:].lstrip()
        )

    @staticmethod
    def _extract_response_text(data: dict[str, Any]) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str):
            return output_text
        chunks: list[str] = []
        for item in data.get("output", []) if isinstance(data.get("output"), list) else []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
        return "\n".join(chunks)

    @staticmethod
    def _local_fallback(title: str, transcript: str) -> str:
        return (
            '{"brief_title": "'
            + truncate_text(title.replace('"', ""), 30)
            + '", "brief_summary": "该视频已完成抓取和转录，系统已生成基础整理，可在原稿中查看完整内容。", '
            + '"content_sections": [{"title": "系统基础整理", "content": "该视频已完成抓取和转录。当前内容由本地规则生成基础整理，未额外推断原文未明确说明的信息；可结合下方视频原稿查看完整表述，后续也可以在详情页重新生成更完整的 AI 整理。"}], '
            + '"corrected_transcript_sections": [], '
            + '"content_category": "未分类", "importance_level": "中", "keywords": [], "tags": ["其他"], '
            + '"importance_score": 3, "novelty_score": 3, "information_density": 3, "business_relevance": 3, '
            + '"value_score": 3.0, "recommended_action": "review", "recommendation_reason": "本地降级整理，需要人工查看原稿判断价值", "deep_research_suggested": false}'
        )
