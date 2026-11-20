from types import SimpleNamespace

import psutil
import pytest

from kenradar.runtime_control import _owned


@pytest.mark.parametrize('style', ['posix', 'native', 'relative'])
def test_owned_normalizes_config_path(monkeypatch, tmp_path, style):
    config = tmp_path / 'config' / 'config.yaml'
    arg = {'posix': config.as_posix(), 'native': str(config),
           'relative': 'config/config.yaml'}[style]
    process = SimpleNamespace(create_time=lambda: 123.0,
                              cwd=lambda: str(tmp_path),
                              cmdline=lambda: ['python', '-m', 'kenradar', '--config', arg, 'web'])
    monkeypatch.setattr('kenradar.runtime_control.psutil.Process', lambda pid: process)
    assert _owned({'pid': 1, 'created_at': 123.0}, config) is process


@pytest.mark.parametrize('argv,created_at', [
    (['kenradar', '--config', 'other.yaml', 'web'], 123.0),
    (['kenradar', '--config', 'config.yaml', 'web'], 124.0),
    (['other', '--config', 'config.yaml', 'web'], 123.0),
    (['kenradar', 'config.yaml', 'web'], 123.0),
    (['kenradar', '--config'], 123.0),
])
def test_owned_rejects_other_identity_or_malformed_arguments(monkeypatch, tmp_path, argv, created_at):
    process = SimpleNamespace(create_time=lambda: 123.0, cwd=lambda: str(tmp_path), cmdline=lambda: argv)
    monkeypatch.setattr('kenradar.runtime_control.psutil.Process', lambda pid: process)
    assert _owned({'pid': 1, 'created_at': created_at}, tmp_path / 'config.yaml') is None


def test_owned_rejects_inaccessible_or_missing_process(monkeypatch, tmp_path):
    def denied(pid):
        raise psutil.AccessDenied(pid)
    monkeypatch.setattr('kenradar.runtime_control.psutil.Process', denied)
    assert _owned({'pid': 1, 'created_at': 123.0}, tmp_path / 'config.yaml') is None
