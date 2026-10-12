"""Bounded cross-process advisory locks on Windows and POSIX."""
from __future__ import annotations

import os
import time
import portalocker

LOCK_EX = 2
LOCK_UN = 8


def flock(fd: int, operation: int) -> None:
    if operation == LOCK_UN:
        portalocker.unlock(fd)
        return
    if operation != LOCK_EX:
        raise ValueError("不支持的文件锁操作")
    deadline = time.monotonic() + float(os.getenv("KENRADAR_LOCK_TIMEOUT", "60"))
    while True:
        try:
            portalocker.lock(fd, portalocker.LOCK_EX | portalocker.LOCK_NB)
            return
        except portalocker.exceptions.LockException as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError("跨进程文件锁等待超时，拒绝无锁运行") from exc
            time.sleep(0.05)
