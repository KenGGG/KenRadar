from __future__ import annotations

import multiprocessing
import os
import socket
import time

import pytest
import yaml

from test_sqlite_v2 import sqlite_db
from kenradar.core.file_lock import flock, LOCK_EX, LOCK_UN
from kenradar.runtime_control import control
from kenradar.storage import reset_database_cache


def _lock_competitor(path, results):
    os.environ["KENRADAR_LOCK_TIMEOUT"] = "0.15"
    with open(path, "a+") as lock:
        try:
            flock(lock.fileno(), LOCK_EX)
        except TimeoutError:
            results.put("timeout")
        else:
            results.put("acquired")
            flock(lock.fileno(), LOCK_UN)


def test_native_file_lock_contention(tmp_path):
    path = tmp_path / "config-gpu-provider.lock"
    ctx = multiprocessing.get_context("spawn")
    results = ctx.Queue()
    with path.open("a+") as lock:
        flock(lock.fileno(), LOCK_EX)
        child = ctx.Process(target=_lock_competitor, args=(str(path), results))
        child.start()
        child.join(10)
        assert child.exitcode == 0
        assert results.get(timeout=2) == "timeout"
        flock(lock.fileno(), LOCK_UN)
    child = ctx.Process(target=_lock_competitor, args=(str(path), results))
    child.start()
    child.join(10)
    assert child.exitcode == 0
    assert results.get(timeout=2) == "acquired"


def test_isolated_native_start_status_stop(sqlite_db):
    db, cfg = sqlite_db
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    config["app"]["web_port"] = port
    config["ai"] = {"organizer": {"providers": []}, "funasr": {"enabled": False}}
    cfg.write_text(yaml.safe_dump(config), encoding="utf-8")
    reset_database_cache()
    try:
        started = control("start", str(cfg))["started"]
        repeated = control("start", str(cfg))["started"]
        assert started == repeated
        assert len({v["pid"] for v in started.values()}) == 2
        status = control("status", str(cfg))
        assert set(status) == {"web", "worker"}
        assert all(v["running"] for v in status.values())
    finally:
        control("stop", str(cfg))
        reset_database_cache()
    assert control("status", str(cfg)) == {}
    assert db.diagnostic()["integrity"] == "ok"
