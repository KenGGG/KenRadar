import hashlib,json
from pathlib import Path
import pytest
from test_sqlite_v2 import sqlite_db


def content(db,path):
    blogger=db.upsert_blogger(url='https://www.douyin.com/user/fixture',name='fixture',sec_uid='fixture',enabled=True)
    eid='1234567890123456789';db.insert_aweme(blogger,{'aweme_id':eid,'create_time':1792838124,'desc':'fixture'},status='done')
    item=db.find_content_item('douyin',eid);note=path.parent.parent/'notes/douyin/fixture/new.md';note.parent.mkdir(parents=True);note.write_text('# New',encoding='utf8')
    db.replace_analysis_and_note(item['id'],{'status':'success','result_json':{'brief_summary':'new'}},{'note_path':str(note),'content_sha256':hashlib.sha256(note.read_bytes()).hexdigest()})
    return item,note


def test_publication_receipt_binds_rendered_artifact_hash(sqlite_db):
    from kenradar.core.config import load_config
    from kenradar.publishing.static_site import StaticSitePublisher
    from kenradar.publishing.service import PublicationService
    db,path=sqlite_db;c=load_config(path);c.raw['publishing']={'github_pages':{'enabled':True,'output_dir':str(path.parent.parent/'site'),'public_base_url':'https://example.invalid'}}
    item,note=content(db,path);pub=StaticSitePublisher(c)
    PublicationService(db,pub,lambda:None).publish_content(item['id'])
    bundle=db.get_current_bundle(item['id']);row=db.publications.find_success(item['id'],bundle['note']['content_sha256'])
    # Git's checked-in UTF-8 HTML is LF-normalized even on a CRLF worktree.
    artifact=hashlib.sha256(pub.html_path_for(note).read_text(encoding='utf8').encode('utf8')).hexdigest()
    assert row['idempotency_key'].endswith(':html:'+artifact)


def test_failed_batch_sync_never_leaves_successful_receipts(sqlite_db,monkeypatch):
    from kenradar.core.config import load_config
    from kenradar.publishing.static_site import StaticSitePublisher
    from kenradar.publishing.service import PublicationService
    db,path=sqlite_db;c=load_config(path);c.raw['publishing']={'github_pages':{'enabled':True,'output_dir':str(path.parent.parent/'site'),'public_base_url':'https://example.invalid'}}
    item,note=content(db,path);monkeypatch.setattr(db,'get_research_job_content_ids',lambda _: [item['id']])
    def fail():raise RuntimeError('injected failed sync')
    with pytest.raises(RuntimeError,match='failed sync'):PublicationService(db,StaticSitePublisher(c),fail).publish_batch(1)
    assert db.publications.find_success(item['id'],db.get_current_bundle(item['id'])['note']['content_sha256']) is None


def test_public_matches_remote_but_obsolete_blob_fails_current_artifact_hash(sqlite_db,monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from kenradar.core.config import load_config
    from kenradar.notification.daily import DailySummaryService
    db,path=sqlite_db;c=load_config(path);root=path.parent.parent
    c.raw['publishing']={'github_pages':{'enabled':True,'output_dir':str(root/'site')},'github_sync':{'repo_dir':str(root/'site')}}
    note=root/'notes/current.md';note.parent.mkdir(parents=True);note.write_text('# New')
    old=b'<html>OLD published analysis</html>'
    def git(self,args,check=True):
        return subprocess.CompletedProcess(args,0,'a'*40+' refs/heads/gh-pages' if args[0]=='ls-remote' else old.decode(),'')
    monkeypatch.setattr('kenradar.publishing.github_sync.GithubSyncManager._run_git',git)
    monkeypatch.setattr('requests.get',lambda *a,**k:SimpleNamespace(status_code=200,content=old))
    verification=DailySummaryService(db,c).verify_publication(note,'https://example.invalid/current.html',expected_sha256=hashlib.sha256(b'NEW rendered analysis').hexdigest())
    assert verification['verified'] is False and verification['reason']=='receipt_artifact_mismatch'
