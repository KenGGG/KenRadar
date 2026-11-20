from pathlib import Path
from types import SimpleNamespace
from kenradar.core.config import AppConfig
from kenradar.publishing.github_sync import GithubSyncManager


def test_git_execution_uses_explicit_native_runtime_and_bounded_noninteractive_tls(monkeypatch,tmp_path):
    config=AppConfig({'publishing':{'github_sync':{'repo_dir':str(tmp_path),'git_executable':'C:/Program Files/Git/cmd/git.exe'}}},tmp_path/'config/config.yaml')
    calls=[]
    def run(command,**kwargs):
        calls.append((command,kwargs)); return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr('kenradar.publishing.github_sync.subprocess.run',run)
    GithubSyncManager(config)._run_git(['status','--short'])
    cmd,kw=calls[0]
    assert cmd[0]=='C:/Program Files/Git/cmd/git.exe'
    assert kw['timeout']<=180
    assert kw['env']['GIT_TERMINAL_PROMPT']=='0' and kw['env']['GCM_INTERACTIVE']=='never'
    assert 'http.sslVerify=true' in cmd


def test_remote_read_retries_transient_tls_but_not_certificate_failure(monkeypatch, tmp_path):
    config = AppConfig({'publishing': {'github_sync': {'repo_dir': str(tmp_path)}}}, tmp_path/'config/config.yaml')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0, stdout='ok',
                               stderr='TLS connect error: unexpected eof while reading' if len(calls) == 1 else '')
    monkeypatch.setattr('kenradar.publishing.github_sync.subprocess.run', run)
    monkeypatch.setattr('kenradar.publishing.github_sync.time.sleep', lambda _: None)
    assert GithubSyncManager(config)._run_git(['ls-remote', 'origin']).stdout == 'ok'
    assert len(calls) == 2
    calls.clear()
    def cert_failure(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stdout='', stderr='certificate verify failed')
    monkeypatch.setattr('kenradar.publishing.github_sync.subprocess.run', cert_failure)
    result = GithubSyncManager(config)._run_git(['ls-remote', 'origin'], check=False)
    assert result.returncode == 1 and len(calls) == 1


def test_remote_read_retries_timeout_and_server_500(monkeypatch, tmp_path):
    import subprocess
    config = AppConfig({'publishing': {'github_sync': {'repo_dir': str(tmp_path)}}}, tmp_path/'config/config.yaml')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if len(calls) == 1: raise subprocess.TimeoutExpired(command, 10)
        return SimpleNamespace(returncode=1 if len(calls)==2 else 0, stdout='ok', stderr='remote: Internal Server Error' if len(calls)==2 else '')
    monkeypatch.setattr('kenradar.publishing.github_sync.subprocess.run', run)
    monkeypatch.setattr('kenradar.publishing.github_sync.time.sleep', lambda _: None)
    assert GithubSyncManager(config)._run_git(['ls-remote', 'origin']).stdout == 'ok'
    assert len(calls) == 3
