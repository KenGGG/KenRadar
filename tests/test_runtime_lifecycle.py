from __future__ import annotations
import json
from pathlib import Path
import socket
import time
from types import SimpleNamespace

import pytest

from kenradar import runtime_control as rc
from kenradar.core.config import load_config
from kenradar.runtime_health import identity, singleton
from kenradar.storage.migrate import upgrade_database


def isolated_config(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    path = tmp_path / 'config.yaml'
    path.write_text(f'''app:
  data_dir: "{tmp_path.as_posix()}"
  database_url: "sqlite:///{(tmp_path / 'db.sqlite3').as_posix()}"
  web_port: {port}
schedule:
  enabled: false
notification:
  enabled: false
publishing:
  github_pages:
    enabled: false
  github_sync:
    enabled: false
''', encoding='utf8')
    return path, port


def test_singleton_rejects_second_owner_and_releases(tmp_path):
    path, _ = isolated_config(tmp_path)
    with singleton(path, 'worker'):
        with pytest.raises(RuntimeError, match='已有实例'):
            with singleton(path, 'worker'):
                pytest.fail('second owner entered')
    with singleton(path, 'worker'):
        pass


def test_status_rejects_live_pid_wrong_listener_and_wrong_receipt(monkeypatch, tmp_path):
    path, _ = isolated_config(tmp_path)
    config = load_config(path)
    stamp = 123.0
    state = {role: {'pid': i, 'created_at': stamp} for role, i in [('web', 11), ('worker', 12)]}
    monkeypatch.setattr(rc, '_owned', lambda record, path: SimpleNamespace(role='web' if record.get('pid') == 11 else 'worker'))
    monkeypatch.setattr(rc, '_process_role', lambda process, path: process.role)
    monkeypatch.setattr(rc, '_listeners', lambda port: [99])
    monkeypatch.setattr(rc, '_web_health', lambda port: {'ok': True, 'instance': {'pid': 99, 'created_at': stamp, 'config_id': 'other'}})
    root = config.data_dir / 'runtime'; root.mkdir()
    (root / 'worker-health.json').write_text(json.dumps({'pid': 12, 'created_at': stamp, 'config_id': identity(path)['config_id'], 'heartbeat_at': time.time()-30, 'scheduler_alive': True}))
    result = rc._status(config, state, {role: [record] for role, record in state.items()})
    assert result['web']['process_alive'] and not result['web']['running']
    assert result['worker']['process_alive'] and not result['worker']['running']
    assert any('过期' in reason for reason in result['worker']['reasons'])


def test_start_refuses_foreign_listener_before_database_write(monkeypatch, tmp_path):
    path, _ = isolated_config(tmp_path)
    monkeypatch.setattr(rc, '_inventory', lambda path: {'web': [], 'worker': []})
    monkeypatch.setattr(rc, '_listeners', lambda port: [99999])
    monkeypatch.setattr(rc, '_web_health', lambda port: {'ok': True})
    monkeypatch.setattr(rc, 'create_database', lambda config: pytest.fail('must refuse before database initialization'))
    with pytest.raises(RuntimeError, match='端口已被占用'):
        rc.control('start', str(path))


def test_real_web_worker_start_adopt_repeat_and_stop(tmp_path):
    path, port = isolated_config(tmp_path)
    upgrade_database(str(path))
    try:
        first = rc.control('start', str(path))['started']
        result = rc.control('status', str(path))
        assert result['web']['running'] and result['worker']['running'], result
        assert rc._listeners(port) == [first['web']['pid']]
        assert rc._web_health(port)['instance']['config_id'] == identity(path)['config_id']
        # Lost process registry: recover only a unique, verified healthy owner.
        (tmp_path/'runtime/processes.json').write_text(json.dumps({role: {'pid': -1, 'created_at': 0} for role in ('web', 'worker')}))
        second = rc.control('start', str(path))['started']
        assert second == first
        assert rc.control('start', str(path))['started'] == first
        import subprocess, sys, os
        env = dict(os.environ, KENRADAR_EMBEDDED_WORKER='0')
        for role in ('web', 'worker'):
            args = [sys.executable, '-m', 'kenradar', '--config', str(path), role]
            if role == 'web':
                args += ['--host', '127.0.0.1', '--port', str(port)]
            duplicate = subprocess.run(args, capture_output=True, timeout=15, env=env)
            assert duplicate.returncode != 0, role
        assert rc.control('status', str(path))['web']['running']
        assert rc.control('status', str(path))['worker']['running']
        other_root = tmp_path / 'other'; other_root.mkdir()
        other_path, _ = isolated_config(other_root)
        upgrade_database(str(other_path))
        collision = subprocess.run([sys.executable, '-m', 'kenradar', '--config', str(other_path),
                                    'web', '--host', '127.0.0.1', '--port', str(port)],
                                   capture_output=True, timeout=15, env=env)
        assert collision.returncode != 0
        assert rc._listeners(port) == [first['web']['pid']]
    finally:
        rc.control('stop', str(path))
    assert rc._listeners(port) == []
    assert not rc.control('status', str(path))['web']['running']


def test_start_refuses_duplicate_inventory_without_spawning(monkeypatch, tmp_path):
    path, _ = isolated_config(tmp_path)
    found = {'web': [], 'worker': [{'pid': 11, 'created_at': 1}, {'pid': 12, 'created_at': 2}]}
    monkeypatch.setattr(rc, '_inventory', lambda path: found)
    monkeypatch.setattr(rc, '_status', lambda *args: {'web': {'running': False}, 'worker': {'running': False}})
    monkeypatch.setattr(rc.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('duplicate must not spawn'))
    with pytest.raises(RuntimeError, match='重复实例'):
        rc.control('start', str(path))


def test_listener_permission_failure_does_not_mean_free_port(monkeypatch, tmp_path):
    path, _ = isolated_config(tmp_path)
    monkeypatch.setattr(rc, '_inventory', lambda path: {'web': [], 'worker': []})
    def denied(port):
        import psutil
        raise psutil.AccessDenied()
    monkeypatch.setattr(rc, '_listeners', denied)
    monkeypatch.setattr(rc, '_web_health', lambda port: {})
    result = rc.control('status', str(path))
    assert not result['web']['running']
    assert any('无法核对监听' in item for item in result['web']['reasons'])
    with pytest.raises(Exception):
        rc.control('start', str(path))


def test_start_rolls_back_new_process_with_wrong_health_identity(monkeypatch, tmp_path):
    path, port = isolated_config(tmp_path)
    upgrade_database(str(path))
    monkeypatch.setattr(rc, 'STARTUP_TIMEOUT_SECONDS', 2)
    monkeypatch.setattr(rc, '_web_health', lambda port: {'ok': True, 'instance': {'pid': -1}})
    try:
        with pytest.raises(RuntimeError, match='启动未通过'):
            rc.control('start', str(path))
        assert json.loads((tmp_path/'runtime/processes.json').read_text()) == {}
        assert rc._listeners(port) == []
    finally:
        rc.control('stop', str(path))


def test_worker_start_failure_rolls_back_new_web_too(monkeypatch, tmp_path):
    path, port = isolated_config(tmp_path)
    upgrade_database(str(path))
    real_status = rc._status
    def without_worker(*args, **kwargs):
        result = real_status(*args, **kwargs)
        result['worker']['running'] = False
        return result
    monkeypatch.setattr(rc, '_status', without_worker)
    monkeypatch.setattr(rc, 'STARTUP_TIMEOUT_SECONDS', 2)
    try:
        with pytest.raises(RuntimeError, match='worker 启动未通过'):
            rc.control('start', str(path))
        assert json.loads((tmp_path/'runtime/processes.json').read_text()) == {}
        assert rc._listeners(port) == []
        assert rc._inventory(path) == {'web': [], 'worker': []}
    finally:
        rc.control('stop', str(path))


def test_restart_elevates_only_stop_and_starts_in_original_process(monkeypatch, tmp_path):
    path, _ = isolated_config(tmp_path)
    config = load_config(path)
    events = []
    monkeypatch.setattr(rc, 'create_database', lambda _: SimpleNamespace(list_task_runs=lambda **kw: [], close=lambda: None))
    monkeypatch.setattr(rc, '_needs_elevated_stop', lambda _: True)
    monkeypatch.setattr(rc, '_elevated_stop', lambda _: events.append('elevated_stop'))
    monkeypatch.setattr(rc, 'control', lambda action, path: events.append(action) or {})
    rc._restart(config)
    assert events == ['elevated_stop', 'start']


def test_restart_refuses_pending_work_before_any_uac_or_stop(monkeypatch, tmp_path):
    path, _ = isolated_config(tmp_path)
    config = load_config(path)
    monkeypatch.setattr(rc, 'create_database', lambda _: SimpleNamespace(list_task_runs=lambda **kw: [{'id':7,'status':'running'}], close=lambda: None))
    monkeypatch.setattr(rc, '_needs_elevated_stop', lambda _: pytest.fail('must not prompt during active work'))
    with pytest.raises(RuntimeError, match='7'):
        rc._restart(config)


def test_restart_uac_rejection_does_not_start_duplicate(monkeypatch, tmp_path):
    path, _ = isolated_config(tmp_path)
    config = load_config(path)
    monkeypatch.setattr(rc, 'create_database', lambda _: SimpleNamespace(list_task_runs=lambda **kw: [], close=lambda: None))
    monkeypatch.setattr(rc, '_needs_elevated_stop', lambda _: True)
    def denied(_): raise PermissionError('UAC denied')
    monkeypatch.setattr(rc, '_elevated_stop', denied)
    monkeypatch.setattr(rc, 'control', lambda *args: pytest.fail('must not start'))
    with pytest.raises(PermissionError): rc._restart(config)


def test_real_restart_replaces_both_owned_processes(tmp_path):
    path, _ = isolated_config(tmp_path)
    upgrade_database(str(path))
    try:
        old = rc.control('start', str(path))['started']
        new = rc.control('restart', str(path))['started']
        assert new['web']['pid'] != old['web']['pid']
        assert new['worker']['pid'] != old['worker']['pid']
        status = rc.control('status', str(path))
        assert status['web']['running'] and status['worker']['running']
        assert status['restart_requires_uac'] is False
    finally:
        rc.control('stop', str(path))
