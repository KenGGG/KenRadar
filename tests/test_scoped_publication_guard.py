from pathlib import Path
from types import SimpleNamespace
import pytest
from kenradar.core.config import AppConfig
from kenradar.publishing.github_sync import GithubSyncManager,GithubSyncError


def test_configured_publication_scope_excludes_other_authors_and_briefs(tmp_path):
    site=tmp_path/'site'
    for rel in ['notes/douyin/allowed/a.html','notes/douyin/other/b.html','briefs/unrelated.html','index.html']:
        path=site/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('<title>fixture</title>',encoding='utf8')
    config=AppConfig({'publishing':{'github_pages':{'output_dir':str(site)},'github_sync':{'repo_dir':str(site),'allowed_paths':['notes/douyin/allowed/*.html','index.html']}}},tmp_path/'config/config.yaml')
    manager=GithubSyncManager(config)
    assert {c.path.relative_to(site).as_posix() for c in manager.collect_candidates()}=={'notes/douyin/allowed/a.html','index.html'}


def test_outgoing_index_cannot_drop_historical_canonical_links(tmp_path,monkeypatch):
    config=AppConfig({'publishing':{'github_pages':{'preserve_historical_pages':True},'github_sync':{'repo_dir':str(tmp_path),'allowed_paths':['notes/douyin/allowed/*.html']}}},tmp_path/'config/config.yaml')
    manager=GithubSyncManager(config)
    index='notes/douyin/allowed/index.html'
    def run(args,check=True):
        if args[0]=='ls-remote':out='a'*40+'\trefs/heads/gh-pages\n'
        elif args[0]=='cat-file':out=''
        elif args[:2]==['diff','--name-only']:out=index+'\0'
        elif args[:2]==['diff','--diff-filter=D']:out=''
        elif args[0]=='rev-list':out=''  # No extra outgoing blob fixture in this href-only regression.
        elif args[0]=='show' and args[1].startswith('HEAD:'):out='<a href="new.html">new</a>'
        elif args[0]=='show':out='<a href="%E6%97%A7.html">old</a>'
        else:raise AssertionError(args)
        return SimpleNamespace(stdout=out,stderr='',returncode=0)
    monkeypatch.setattr(manager,'_run_git',run)
    with pytest.raises(GithubSyncError,match='HISTORY_LINK_LOSS'):
        manager._guard_outgoing_scope()


def test_existing_unpushed_commit_retries_without_new_render_or_commit(tmp_path,monkeypatch):
    from contextlib import nullcontext
    from kenradar.publishing.github_sync import SyncCandidate
    config=AppConfig({'publishing':{'github_sync':{'repo_dir':str(tmp_path),'enabled':True,'auto_push':True}}},tmp_path/'config/config.yaml')
    path=tmp_path/'index.html';path.write_text('fixture',encoding='utf8')
    manager=GithubSyncManager(config);calls=[]
    monkeypatch.setattr(manager,'_repo_lock',nullcontext)
    monkeypatch.setattr(manager,'_ensure_git_repo',lambda:None)
    monkeypatch.setattr(manager,'collect_candidates',lambda:[SyncCandidate(path,'fixture')])
    monkeypatch.setattr(manager,'_deleted_allowed_files',lambda:[])
    monkeypatch.setattr(manager,'_changed_files',lambda files:[])
    monkeypatch.setattr(manager,'_guard_outgoing_scope',lambda:calls.append('guard'))
    monkeypatch.setattr(manager,'_run_git_push_with_retry',lambda:calls.append('resume-push'))
    result=manager.sync(force=True)
    assert calls==['guard','resume-push']
    assert result['pushed'] is True and result['committed'] is False
