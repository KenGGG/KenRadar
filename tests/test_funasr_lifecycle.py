from __future__ import annotations

import threading
import time
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kenradar.core.config import AppConfig
from kenradar.core.funasr_service import FunASRServiceManager


def test_health_requires_loaded_model(tmp_path: Path, monkeypatch) -> None:
    import requests
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"ok": false}'
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: response)
    manager = FunASRServiceManager(_config(tmp_path))
    assert manager._default_health_check("http://localhost/health") is False
    response._content = b'{"ok": true}'
    assert manager._default_health_check("http://localhost/health") is True


def test_upload_closes_temporary_file_and_preserves_sentences(tmp_path: Path, monkeypatch) -> None:
    module = _server_module()
    monkeypatch.setattr(module.tempfile, "tempdir", str(tmp_path))
    captured = []

    def generate(options):
        path = Path(options["input"])
        assert path.read_bytes() == b"test audio"
        captured.append(path)
        return [{"text": "你好世界。", "sentence_info": [{"sentence": "你好世界。", "start": 0, "end": 1000}]}]

    monkeypatch.setattr(module, "_generate", generate)
    with TestClient(module.APP) as client:
        response = client.post("/v1/audio/transcriptions", files={"file": ("sample.wav", b"test audio", "audio/wav")})
    assert response.status_code == 200
    assert response.json()["segments"][0]["text"] == "你好世界。"
    assert response.json()["segments"][0]["end"] == 1.0
    assert not captured[0].exists()


def test_file_lock_serializes_processes(tmp_path: Path) -> None:
    from kenradar.core import file_lock
    lock_path = tmp_path / "process.lock"
    code = "from pathlib import Path; from kenradar.core import file_lock; import sys; f=Path(sys.argv[1]).open('a+'); file_lock.flock(f.fileno(), file_lock.LOCK_EX); print('locked', flush=True)"
    with lock_path.open("a+") as handle:
        file_lock.flock(handle.fileno(), file_lock.LOCK_EX)
        process = subprocess.Popen([sys.executable, "-c", code, str(lock_path)], stdout=subprocess.PIPE, text=True)
        try:
            time.sleep(0.2)
            assert process.poll() is None
            file_lock.flock(handle.fileno(), file_lock.LOCK_UN)
            output, _ = process.communicate(timeout=10)
            assert process.returncode == 0
            assert output.strip() == "locked"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


@pytest.mark.skipif(os.name != "nt", reason="Windows detached launcher")
def test_windows_launcher_propagates_endpoint_and_device(tmp_path: Path, monkeypatch) -> None:
    from types import SimpleNamespace
    captured = {}

    def launch(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(pid=123, poll=lambda: None)

    monkeypatch.setattr(subprocess, "Popen", launch)
    monkeypatch.setattr(FunASRServiceManager, "_repo_root", staticmethod(lambda: tmp_path))
    manager = FunASRServiceManager(_config(tmp_path, endpoint="http://127.0.0.1:19002/v1", device="cpu"))
    manager._default_process_runner(tmp_path / "start.sh")
    assert captured["command"] == [sys.executable, str(tmp_path / "scripts/funasr_openai_server.py")]
    assert captured["env"]["FUNASR_PORT"] == "19002"
    assert captured["env"]["FUNASR_DEVICE"] == "cpu"
    assert captured["creationflags"] == subprocess.CREATE_NO_WINDOW
    assert (tmp_path / "data/funasr_server.pid").read_text() == "123"


def _server_module():
    server_path = Path(__file__).resolve().parents[1] / "scripts/funasr_openai_server.py"
    spec = importlib.util.spec_from_file_location("test_funasr_openai_server", server_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _config(tmp_path: Path, **funasr: object) -> AppConfig:
    values: dict[str, object] = {
        "enabled": True,
        "managed": True,
        "endpoint": "http://127.0.0.1:18002/v1",
        "startup_timeout_seconds": 0.2,
        "startup_poll_seconds": 0.01,
        "startup_lock_path": str(tmp_path / "funasr-start.lock"),
        "start_script": str(tmp_path / "start-funasr.sh"),
    }
    values.update(funasr)
    return AppConfig({"ai": {"funasr": values}}, tmp_path / "config.yaml")


def test_healthy_service_is_reused_without_starting(tmp_path: Path) -> None:
    starts: list[str] = []
    manager = FunASRServiceManager(
        _config(tmp_path),
        health_check=lambda _url: True,
        process_runner=lambda script: starts.append(str(script)),
    )

    manager.ensure_available()

    assert starts == []


def test_unmanaged_service_never_starts_local_process(tmp_path: Path) -> None:
    starts: list[str] = []
    manager = FunASRServiceManager(
        _config(tmp_path, managed=False),
        health_check=lambda _url: False,
        process_runner=lambda script: starts.append(str(script)),
    )

    manager.ensure_available()

    assert starts == []


def test_unhealthy_managed_service_starts_and_waits_until_healthy(tmp_path: Path) -> None:
    state = {"healthy": False}
    starts: list[str] = []

    def start(script: Path) -> None:
        starts.append(str(script))
        state["healthy"] = True

    manager = FunASRServiceManager(
        _config(tmp_path),
        health_check=lambda _url: state["healthy"],
        process_runner=start,
    )

    manager.ensure_available()

    assert starts == [str(tmp_path / "start-funasr.sh")]


def test_concurrent_callers_start_service_once(tmp_path: Path) -> None:
    state = {"healthy": False}
    starts = 0
    state_lock = threading.Lock()

    def start(_script: Path) -> None:
        nonlocal starts
        with state_lock:
            starts += 1
        time.sleep(0.05)
        state["healthy"] = True

    managers = [
        FunASRServiceManager(
            _config(tmp_path),
            health_check=lambda _url: state["healthy"],
            process_runner=start,
        )
        for _ in range(2)
    ]
    threads = [threading.Thread(target=manager.ensure_available) for manager in managers]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert starts == 1


def test_startup_timeout_is_reported(tmp_path: Path) -> None:
    manager = FunASRServiceManager(
        _config(tmp_path, startup_timeout_seconds=0.03),
        health_check=lambda _url: False,
        process_runner=lambda _script: None,
    )

    with pytest.raises(RuntimeError, match="did not become healthy"):
        manager.ensure_available()


def test_default_process_runner_uses_current_python_environment(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def run(command, *, check, env):
        captured.update(command=command, check=check, env=env)

    monkeypatch.setattr(subprocess, "run", run)
    manager = FunASRServiceManager(_config(tmp_path))

    script = tmp_path / ("start-funasr.bat" if os.name == "nt" else "start-funasr.sh")
    manager._default_process_runner(script)

    assert captured["command"] == [str(script)]
    assert captured["check"] is True
    assert captured["env"]["PYTHON_BIN"] == sys.executable


def test_active_transcription_blocks_idle_exit() -> None:
    module = _server_module()
    now = [100.0]
    tracker = module.RequestActivityTracker(300, clock=lambda: now[0])

    tracker.begin()
    now[0] = 1000.0

    assert tracker.should_exit() is False


def test_last_request_completion_starts_new_idle_interval() -> None:
    module = _server_module()
    now = [100.0]
    tracker = module.RequestActivityTracker(300, clock=lambda: now[0])

    tracker.begin()
    now[0] = 500.0
    tracker.end()
    now[0] = 799.9
    assert tracker.should_exit() is False
    now[0] = 800.0

    assert tracker.should_exit() is True


def test_new_request_resets_idle_interval() -> None:
    module = _server_module()
    now = [0.0]
    tracker = module.RequestActivityTracker(300, clock=lambda: now[0])

    now[0] = 250.0
    tracker.begin()
    now[0] = 260.0
    tracker.end()
    now[0] = 559.9

    assert tracker.should_exit() is False


def test_zero_idle_timeout_disables_exit() -> None:
    module = _server_module()
    now = [0.0]
    tracker = module.RequestActivityTracker(0, clock=lambda: now[0])
    now[0] = 10_000.0

    assert tracker.should_exit() is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell lifecycle")
def test_kenradar_start_does_not_eagerly_probe_or_start_funasr(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_curl = fake_bin / "curl"
    fake_curl.write_text("#!/usr/bin/env bash\necho eager-funasr-probe\nexit 0\n", encoding="utf-8")
    fake_curl.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "MODE": "unsupported-test-mode",
            "PYTHON_BIN": "/bin/true",
            "PID_FILE": str(tmp_path / "kenradar.pid"),
            "WORKER_PID_FILE": str(tmp_path / "worker.pid"),
            "FUNASR_PID_FILE": str(tmp_path / "funasr.pid"),
            "FUNASR_LOG_FILE": str(tmp_path / "funasr.log"),
            "ENV_FILE": str(tmp_path / "missing.env"),
            "CONFIG_PATH": str(tmp_path / "config.yaml"),
        }
    )

    result = subprocess.run(
        [str(repo_root / "ctl.sh"), "start"],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "FunASR server already healthy" not in result.stdout
