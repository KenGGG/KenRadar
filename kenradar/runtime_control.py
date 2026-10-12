"""Native process lifecycle for one Web + one worker. No service registration."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

from kenradar.core.config import load_config
from kenradar.core.file_lock import flock, LOCK_EX, LOCK_UN
from kenradar.storage import create_database


def _owned(record: dict, config_path: Path) -> psutil.Process | None:
    try:
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["created_at"]) > .01:
            return None
        argv = process.cmdline()
        if "kenradar" not in argv or str(config_path) not in argv:
            return None
        return process
    except (psutil.Error, KeyError):
        return None


def control(action: str, config_path: str) -> dict:
    config = load_config(config_path)
    if config.database_type != "sqlite":
        raise RuntimeError("只支持 SQLite 测试/已授权配置")
    root = config.data_dir / "runtime"
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / "processes.json"
    with (root / "processes.lock").open("a+") as lock:
        flock(lock.fileno(), LOCK_EX)
        try:
            state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
            if action == "diagnose":
                db = create_database(config)
                result = db.diagnostic()
                result.update(python=sys.version.split()[0], executable=sys.executable, data_dir=str(config.data_dir))
                return result
            if action == "status":
                return {name: {"running": _owned(record, config.path.resolve()) is not None, "pid": record["pid"]}
                        for name, record in state.items()}
            if action == "stop":
                stopped = []
                for name, record in state.items():
                    parent = _owned(record, config.path.resolve())
                    if parent is None:
                        continue
                    # Freeze descendants before teardown; verify PID identity first.
                    processes = parent.children(recursive=True) + [parent]
                    for process in processes:
                        try:
                            process.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    _, alive = psutil.wait_procs(processes, timeout=5)
                    for process in alive:
                        process.kill()
                    psutil.wait_procs(alive, timeout=5)
                    stopped.append(name)
                state_path.write_text("{}", encoding="utf-8")
                return {"stopped": stopped, "leases": "未完成租约保持审计，期限到后由 worker 原子回收"}
            if action != "start":
                raise ValueError("未知生命周期操作")
            db = create_database(config)
            db.initialize()
            for name, args in (("web", ["web", "--host", "127.0.0.1", "--port", str(config.get("app.web_port", 8765))]),
                               ("worker", ["worker", "--name", "local-worker"])):
                if name in state and _owned(state[name], config.path.resolve()):
                    continue
                logs = config.data_dir / "logs"
                logs.mkdir(parents=True, exist_ok=True)
                env = os.environ.copy()
                env["KENRADAR_EMBEDDED_WORKER"] = "0"
                with (logs / f"{name}.log").open("a", encoding="utf-8") as output:
                    process = subprocess.Popen([sys.executable, "-m", "kenradar", "--config", str(config.path.resolve()), *args],
                        cwd=Path(__file__).resolve().parents[1], env=env, stdout=output, stderr=output,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                info = psutil.Process(process.pid)
                state[name] = {"pid": process.pid, "created_at": info.create_time()}
                state_path.write_text(json.dumps(state), encoding="utf-8")
                time.sleep(.3)
                if process.poll() is not None:
                    raise RuntimeError(f"{name} 启动失败，查看 {logs / (name + '.log')}")
            return {"started": state}
        finally:
            flock(lock.fileno(), LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status", "diagnose"])
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    print(json.dumps(control(args.action, args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
