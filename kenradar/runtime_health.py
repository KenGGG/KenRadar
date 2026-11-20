"""Runtime identity, singleton ownership and local worker health receipts."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time

import portalocker
import psutil

from kenradar.core.config import load_config


def identity(config_path):
    path = Path(config_path).resolve()
    return {'pid': os.getpid(), 'created_at': psutil.Process().create_time(),
            'config_id': hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()}


@contextmanager
def singleton(config_path, role):
    from kenradar.windows_process_access import allow_account_control
    allow_account_control()
    root = load_config(config_path).data_dir / 'runtime'
    root.mkdir(parents=True, exist_ok=True)
    with (root / f'{role}.instance.lock').open('a+') as lock:
        try:
            portalocker.lock(lock, portalocker.LOCK_EX | portalocker.LOCK_NB)
        except portalocker.exceptions.LockException as exc:
            raise RuntimeError(f'{role} 已有实例持有运行锁，拒绝重复启动') from exc
        try:
            yield
        finally:
            portalocker.unlock(lock)


def worker_receipt(config_path, *, scheduler_alive, started_at):
    root = load_config(config_path).data_dir / 'runtime'
    data = {**identity(config_path), 'heartbeat_at': time.time(),
            'scheduler_alive': scheduler_alive, 'started_at': started_at}
    temporary = root / f'worker-health.{os.getpid()}.tmp'
    temporary.write_text(json.dumps(data), encoding='utf8')
    temporary.replace(root / 'worker-health.json')
