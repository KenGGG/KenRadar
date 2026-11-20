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

STARTUP_TIMEOUT_SECONDS = 15


def _needs_elevated_stop(config):
    """Use receipts to detect inaccessible owners; elevation rechecks argv."""
    if os.name != 'nt':
        return False
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin():
        return False
    receipts = []
    try:
        receipts.append(_web_health(int(config.get('app.web_port', 8765))).get('instance') or {})
    except Exception:
        pass
    try:
        receipts.append(json.loads((config.data_dir / 'runtime/worker-health.json').read_text(encoding='utf8')))
    except (OSError, ValueError):
        pass
    from kenradar.runtime_health import identity
    expected = identity(config.path)['config_id']
    for record in receipts:
        if not isinstance(record, dict):
            continue
        if record.get('config_id') != expected:
            continue
        try:
            process = psutil.Process(record['pid'])
            if abs(process.create_time() - record['created_at']) > .01:
                continue
            if Path(process.exe()).resolve() != Path(sys.executable).resolve():
                continue
            try:
                process.cmdline()
            except psutil.AccessDenied:
                return True
        except (psutil.Error, KeyError, TypeError, ValueError):
            continue
    return False


def _elevated_stop(config):
    """UAC only stops verified owners. New services inherit the caller's token."""
    import ctypes
    from ctypes import wintypes
    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('fMask', wintypes.ULONG),
                    ('hwnd', wintypes.HWND), ('lpVerb', wintypes.LPCWSTR),
                    ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                    ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int),
                    ('hInstApp', wintypes.HINSTANCE), ('lpIDList', ctypes.c_void_p),
                    ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                    ('dwHotKey', wintypes.DWORD), ('hIcon', wintypes.HANDLE),
                    ('hProcess', wintypes.HANDLE)]
    info = ShellExecuteInfo()
    info.cbSize, info.fMask = ctypes.sizeof(info), 0x40  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb, info.lpFile = 'runas', sys.executable
    info.lpParameters = subprocess.list2cmdline(['-m', 'kenradar.runtime_control', 'stop', '--config', str(config.path.resolve())])
    info.lpDirectory, info.nShow = str(Path(__file__).resolve().parents[1]), 0
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell.ShellExecuteExW.restype = wintypes.BOOL
    if not shell.ShellExecuteExW(ctypes.byref(info)):
        raise PermissionError(f'Windows UAC 未批准停止旧服务 (error {ctypes.get_last_error()})')
    if not info.hProcess:
        raise RuntimeError('未取得提权停止进程回执，拒绝启动重复服务')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        # Bounded helper; never start new services until termination is confirmed.
        if kernel.WaitForSingleObject(info.hProcess, 60000) != 0:
            raise RuntimeError('提权停止尚未完成，拒绝启动重复服务；请检查状态')
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code)) or code.value:
            raise RuntimeError('提权停止失败，拒绝启动重复服务')
    finally:
        kernel.CloseHandle(info.hProcess)


def _restart(config):
    database = create_database(config)
    try:
        active = [row['id'] for row in database.list_task_runs(limit=1000) if row['status'] in ('running', 'queued', 'retry_wait')]
    finally:
        database.close()
    if active:
        raise RuntimeError(f'仍有运行中任务 {active}，请在安全边界暂停后重启')
    if _needs_elevated_stop(config):
        _elevated_stop(config)
    else:
        control('stop', str(config.path))
    return control('start', str(config.path))


def _owned(record: dict, config_path: Path) -> psutil.Process | None:
    try:
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["created_at"]) > .01:
            return None
        argv = process.cmdline()
        if "kenradar" not in argv or "--config" not in argv:
            return None
        config_index = argv.index("--config") + 1
        if config_index >= len(argv):
            return None
        process_config = Path(argv[config_index])
        if not process_config.is_absolute():
            process_config = Path(process.cwd()) / process_config
        if process_config.resolve() != config_path.resolve():
            return None
        return process
    except (psutil.Error, KeyError, OSError, ValueError):
        return None


def _process_role(process, config_path):
    argv = process.cmdline()
    if '-m' not in argv or argv[argv.index('-m') + 1:argv.index('-m') + 2] != ['kenradar']:
        return None
    if '--config' not in argv:
        return None
    index = argv.index('--config') + 1
    if index >= len(argv):
        return None
    path = Path(argv[index])
    if not path.is_absolute():
        path = Path(process.cwd()) / path
    if path.resolve() != config_path.resolve():
        return None
    return argv[index + 1] if index + 1 < len(argv) and argv[index + 1] in ('web', 'worker') else None


def _inventory(config_path):
    found = {'web': [], 'worker': []}
    for process in psutil.process_iter():
        try:
            role = _process_role(process, config_path)
            if role:
                found[role].append({'pid': process.pid, 'created_at': process.create_time()})
        except (psutil.Error, OSError, ValueError, IndexError):
            continue
    return found


def _listeners(port):
    # Inaccessible ownership is a blocker, not an empty/free port.
    return sorted({connection.pid for connection in psutil.net_connections(kind='tcp')
                   if connection.status == psutil.CONN_LISTEN and connection.laddr.port == port},
                  key=lambda pid: pid or -1)


def _web_health(port):
    from urllib.request import build_opener, ProxyHandler
    with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/health/ready', timeout=1) as response:
        if response.status != 200:
            raise RuntimeError('健康接口未返回 200')
        payload = json.loads(response.read(32768))
        if not isinstance(payload, dict):
            raise ValueError('健康接口不是 JSON 对象')
        return payload


def _status(config, state, inventory=None):
    from kenradar.runtime_health import identity
    found = inventory if inventory is not None else _inventory(config.path.resolve())
    try:
        listeners, listener_error = _listeners(int(config.get('app.web_port', 8765))), ''
    except (psutil.Error, OSError, RuntimeError) as exc:
        listeners, listener_error = [], f'无法核对监听进程: {type(exc).__name__}'
    report = {}
    for role in ('web', 'worker'):
        record = state.get(role) or (found[role][0] if len(found[role]) == 1 else {})
        if len(found[role]) == 1 and record not in found[role]:
            # A service started outside ctl can leave stale process records.
            # Inventory already verifies module, role and exact config path.
            record = found[role][0]
        process = _owned(record, config.path.resolve())
        reasons = []
        if process is None:
            reasons.append('进程不存在或创建时间/配置身份不匹配')
        else:
            try:
                if _process_role(process, config.path.resolve()) != role:
                    reasons.append('进程角色不匹配')
            except (psutil.Error, OSError, ValueError):
                reasons.append('无法核对进程角色')
        if len(found[role]) > 1:
            reasons.append('检测到同配置的重复实例')
        health = {}
        if role == 'web':
            if listener_error:
                reasons.append(listener_error)
            if listeners != [record.get('pid')]:
                reasons.append('实际监听进程与受管 Web 不一致')
            try:
                health = _web_health(int(config.get('app.web_port', 8765)))
            except Exception as exc:
                reasons.append(f'健康接口不可用: {type(exc).__name__}')
            receipt = health.get('instance') or {}
            if not isinstance(receipt, dict):
                receipt = {}
            if not health.get('ok'):
                reasons.append('Web 未就绪')
        else:
            try:
                health = json.loads((config.data_dir / 'runtime/worker-health.json').read_text(encoding='utf8'))
            except (OSError, ValueError):
                reasons.append('缺少 worker 健康回执')
            if not isinstance(health, dict):
                health = {}
            receipt = health
            stamp = health.get('heartbeat_at', 0)
            if not isinstance(stamp, (int, float)) or not 0 <= time.time() - stamp < 15:
                reasons.append('worker 健康回执已过期')
            if not health.get('scheduler_alive'):
                reasons.append('worker 调度线程未就绪')
        if (receipt.get('pid') != record.get('pid') or
                receipt.get('created_at') != record.get('created_at') or
                receipt.get('config_id') != identity(config.path)['config_id']):
            reasons.append('健康回执与进程/配置身份不匹配')
        report[role] = {'running': not reasons, 'pid': record.get('pid'),
                        'process_alive': process is not None, 'reasons': reasons,
                        'instances': found[role]}
        if role == 'web':
            report[role]['listener_pids'] = listeners
    return report


def control(action: str, config_path: str) -> dict:
    config = load_config(config_path)
    if config.database_type != "sqlite":
        raise RuntimeError("只支持 SQLite 测试/已授权配置")
    if action == 'restart':
        return _restart(config)
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
                result = _status(config, state)
                result['restart_requires_uac'] = _needs_elevated_stop(config)
                return result
            if action == "stop":
                if _needs_elevated_stop(config):
                    raise PermissionError('旧服务权限高于当前会话；请用 ctl.ps1 restart，通过 UAC 仅停止旧服务后以普通权限启动')
                stopped = []
                found = _inventory(config.path.resolve())
                if any(len(records) > 1 for records in found.values()):
                    raise RuntimeError('检测到同配置重复实例，拒绝自动停止')
                targets = dict(state)
                targets.update({role: records[0] for role, records in found.items() if records})
                for name, record in targets.items():
                    parent = _owned(record, config.path.resolve())
                    if parent is None or _process_role(parent, config.path.resolve()) != name:
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
            found = _inventory(config.path.resolve())
            status = _status(config, state, found)
            for role in ('web', 'worker'):
                if len(found[role]) > 1:
                    raise RuntimeError(f'{role} 检测到重复实例，拒绝启动: {status[role]}')
                if found[role]:
                    if not status[role]['running']:
                        raise RuntimeError(f'{role} 已有未通过身份/健康核验的实例，拒绝重复启动: {status[role]}')
                    state[role] = found[role][0]
            listeners = _listeners(int(config.get('app.web_port', 8765)))
            if listeners and not status['web']['running']:
                raise RuntimeError(f'端口已被占用，拒绝启动；监听 PID: {listeners}')
            state_path.write_text(json.dumps(state), encoding='utf8')
            db = create_database(config)
            db.initialize()
            db.close()
            started_here = []
            for name, args in (("web", ["web", "--host", "127.0.0.1", "--port", str(config.get("app.web_port", 8765))]),
                               ("worker", ["worker", "--name", "local-worker"])):
                if status[name]['running']:
                    continue
                logs = config.data_dir / "logs"
                logs.mkdir(parents=True, exist_ok=True)
                env = os.environ.copy()
                env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
                env["KENRADAR_EMBEDDED_WORKER"] = "0"
                with (logs / f"{name}.log").open("a", encoding="utf-8") as output:
                    process = subprocess.Popen([sys.executable, "-m", "kenradar", "--config", str(config.path.resolve()), *args],
                        cwd=Path(__file__).resolve().parents[1], env=env, stdout=output, stderr=output,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                info = psutil.Process(process.pid)
                state[name] = {"pid": process.pid, "created_at": info.create_time()}
                started_here.append(name)
                state_path.write_text(json.dumps(state), encoding="utf-8")
                deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    if _status(config, state)[name]['running']:
                        break
                    time.sleep(.25)
                if not _status(config, state)[name]['running']:
                    # Roll back this start's processes only; adopted owners remain untouched.
                    for started_role in reversed(started_here):
                        owned = _owned(state[started_role], config.path.resolve())
                        if owned is not None:
                            owned.terminate()
                            try:
                                owned.wait(timeout=5)
                            except psutil.TimeoutExpired:
                                owned.kill()
                                owned.wait(timeout=5)
                        state.pop(started_role, None)
                    state_path.write_text(json.dumps(state), encoding='utf8')
                    raise RuntimeError(f"{name} 启动未通过监听/身份/健康核验，查看 {logs / (name + '.log')}")
            return {"started": state}
        finally:
            flock(lock.fileno(), LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "restart", "status", "diagnose"])
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    print(json.dumps(control(args.action, args.config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
