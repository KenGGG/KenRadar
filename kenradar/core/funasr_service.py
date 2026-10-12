from __future__ import annotations

from kenradar.core import file_lock as fcntl
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

import requests

from kenradar.core.config import AppConfig

logger = logging.getLogger(__name__)


class FunASRServiceManager:
    """Ensure the repository-local FunASR HTTP service is ready on demand."""

    def __init__(
        self,
        config: AppConfig,
        *,
        health_check: Callable[[str], bool] | None = None,
        process_runner: Callable[[Path], None] | None = None,
    ) -> None:
        self.config = config
        self._health_check = health_check or self._default_health_check
        self._process_runner = process_runner or self._default_process_runner
        self._process: subprocess.Popen | None = None

    def ensure_available(self) -> None:
        health_url = self._health_url()
        if self._health_check(health_url):
            return
        if not self.config.get("ai.funasr.managed", True):
            return
        if not self._is_loopback_endpoint():
            raise RuntimeError("managed FunASR endpoint must use a loopback host")

        lock_path = Path(
            str(self.config.get("ai.funasr.startup_lock_path", self._repo_root() / "data/funasr-start.lock"))
        )
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            if self._health_check(health_url):
                return
            script = Path(
                str(self.config.get("ai.funasr.start_script", self._repo_root() / "scripts/start_funasr_server.sh"))
            )
            logger.info("FunASR 未运行，按需启动本地服务: script=%s", script)
            self._process_runner(script)
            self._wait_until_healthy(health_url)

    def _wait_until_healthy(self, health_url: str) -> None:
        timeout = float(self.config.get("ai.funasr.startup_timeout_seconds", 180) or 180)
        poll_seconds = float(self.config.get("ai.funasr.startup_poll_seconds", 1) or 1)
        deadline = time.monotonic() + max(0, timeout)
        while time.monotonic() < deadline:
            if self._health_check(health_url):
                return
            if self._process is not None and self._process.poll() is not None:
                raise RuntimeError("FunASR exited during startup; see data/funasr_server.log")
            time.sleep(max(0.001, poll_seconds))
        raise RuntimeError(f"FunASR did not become healthy within {timeout:g} seconds")

    def _default_health_check(self, health_url: str) -> bool:
        try:
            response = requests.get(health_url, timeout=2)
            payload = response.json()
            return response.ok and isinstance(payload, dict) and payload.get("ok") is True
        except (requests.RequestException, ValueError):
            return False

    def _default_process_runner(self, script: Path) -> None:
        env = os.environ.copy()
        env["PYTHON_BIN"] = sys.executable
        env["PYTHONUNBUFFERED"] = "1"
        env["FUNASR_IDLE_TIMEOUT_SECONDS"] = str(
            int(self.config.get("ai.funasr.idle_timeout_seconds", 300) or 0)
        )
        env["FUNASR_STARTUP_TIMEOUT"] = str(
            int(self.config.get("ai.funasr.startup_timeout_seconds", 180) or 180)
        )
        endpoint = urlsplit(str(self.config.get("ai.funasr.endpoint", "http://127.0.0.1:18002/v1")))
        env["FUNASR_HOST"] = endpoint.hostname or "127.0.0.1"
        env["FUNASR_PORT"] = str(endpoint.port or 18002)
        env.setdefault("MODELSCOPE_CACHE", str(self._repo_root() / "data/models/modelscope"))
        env.setdefault("HF_HOME", str(self._repo_root() / "data/models/huggingface"))
        for key, variable in {"model": "FUNASR_MODEL", "device": "FUNASR_DEVICE", "vad_model": "FUNASR_VAD_MODEL", "punc_model": "FUNASR_PUNC_MODEL"}.items():
            value = self.config.get(f"ai.funasr.{key}", None)
            if value is not None:
                env[variable] = str(value)
        if os.name == "nt" and script.suffix == ".sh":
            data_dir = self._repo_root() / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            temp_dir = data_dir / "tmp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            env["TMP"] = env["TEMP"] = str(temp_dir)
            with (data_dir / "funasr_server.log").open("a", encoding="utf-8") as log:
                self._process = subprocess.Popen(
                    [sys.executable, str(self._repo_root() / "scripts/funasr_openai_server.py")],
                    cwd=self._repo_root(), env=env, stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
                )
            (data_dir / "funasr_server.pid").write_text(str(self._process.pid), encoding="utf-8")
            return
        subprocess.run([str(script)], check=True, env=env)

    def _health_url(self) -> str:
        endpoint = str(self.config.get("ai.funasr.endpoint", "http://127.0.0.1:18002/v1") or "").rstrip("/")
        parsed = urlsplit(endpoint)
        return urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))

    def _is_loopback_endpoint(self) -> bool:
        endpoint = str(self.config.get("ai.funasr.endpoint", "") or "")
        return (urlsplit(endpoint).hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}

    @staticmethod
    def _repo_root() -> Path:
        return Path(__file__).resolve().parents[2]
