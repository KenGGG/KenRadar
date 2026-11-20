import subprocess
from pathlib import Path
import pytest
from kenradar.core.config import AppConfig
from kenradar.publishing.github_sync import GithubSyncManager,GithubSyncError

GIT='C:/Program Files/Git/cmd/git.exe'

def setup(tmp):
    def git(*args):
        return subprocess.run([GIT,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid',*args],cwd=tmp,check=True,capture_output=True,text=True).stdout
    git('init');(tmp/'index.html').write_text('baseline');git('add','.');git('commit','-m','baseline')
    base=git('rev-parse','HEAD').strip()
    config=AppConfig({'publishing':{'github_sync':{'repo_dir':str(tmp),'git_executable':GIT}}},tmp/'config/config.yaml')
    return git,GithubSyncManager(config),base


def test_staged_private_content_is_blocked_even_when_worktree_is_cleaned(tmp_path):
    git,m,base=setup(tmp_path)
    (tmp_path/'private.md').write_text('---\nhermes_private: true\n---\nprivate fixture');git('add','private.md')
    (tmp_path/'private.md').write_text('safe worktree replacement')
    with pytest.raises(GithubSyncError,match='PRIVATE|SENSITIVE'):
        m._guard_staged_snapshot()


def test_outgoing_private_commit_is_blocked_even_if_later_removed(tmp_path,monkeypatch):
    git,m,base=setup(tmp_path)
    (tmp_path/'leak.html').write_text('FEISHU_WEBHOOK_URL=fixture-never-send');git('add','.');git('commit','-m','unsafe fixture')
    git('rm','leak.html');git('commit','-m','remove fixture')
    actual=m._run_git
    def run(args,check=True):
        if args[0]=='ls-remote':return subprocess.CompletedProcess(args,0,base+'\trefs/heads/gh-pages\n','')
        return actual(args,check)
    monkeypatch.setattr(m,'_run_git',run)
    with pytest.raises(GithubSyncError,match='PRIVATE|SENSITIVE'):
        m._guard_outgoing_scope()
