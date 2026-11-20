import os
import shutil
import subprocess
from pathlib import Path

from kenradar.core.config import AppConfig
import pytest
from kenradar.publishing.github_sync import GithubSyncManager


@pytest.mark.parametrize('remote_advanced', [False, True])
def test_single_article_projects_from_fresh_remote_without_pushing_local_history(tmp_path, remote_advanced):
    git = shutil.which('git')
    if os.name == 'nt':
        git = 'C:/Program Files/Git/cmd/git.exe'
    def run(repo, *args):
        return subprocess.check_output([git, '-C', str(repo), *args], encoding='utf-8').strip()
    remote = tmp_path / 'remote.git'
    subprocess.check_call([git, 'init', '--bare', str(remote)])
    site = tmp_path / 'site'
    subprocess.check_call([git, 'clone', str(remote), str(site)])
    run(site, 'config', 'user.name', 'Fixture')
    run(site, 'config', 'user.email', 'fixture@example.invalid')
    run(site, 'checkout', '-b', 'gh-pages')
    run(site, 'config', 'core.autocrlf', 'true')
    (site/'.gitattributes').write_text('*.html text eol=lf\n',encoding='utf-8')
    (site/'index.html').write_text('<html><body><main><a href="old.html">old</a></main></body></html>', encoding='utf-8')
    (site/'old.html').write_text('<p>historical</p>', encoding='utf-8')
    run(site, 'add', '.')
    run(site, 'commit', '-m', 'baseline')
    run(site, 'push', '-u', 'origin', 'gh-pages')
    baseline = run(site, 'rev-parse', 'HEAD')
    (site/'unrelated.html').write_text('<p>must stay local</p>', encoding='utf-8')
    run(site, 'add', '.')
    run(site, 'commit', '-m', 'unrelated pending commit')
    original_head = run(site, 'rev-parse', 'HEAD')
    if remote_advanced:
        other = tmp_path/'other'
        subprocess.check_call([git, 'clone', '-b', 'gh-pages', str(remote), str(other)])
        run(other, 'config', 'user.name', 'Fixture')
        run(other, 'config', 'user.email', 'fixture@example.invalid')
        (other/'p').mkdir()
        (other/'p/historical.html').write_text('<p>remote-only short entry</p>',encoding='utf-8')
        run(other, 'add', '.')
        run(other, 'commit', '-m', 'remote advanced')
        run(other, 'push')
        baseline = run(other, 'rev-parse', 'HEAD')
    article = site/'notes/douyin/author/new_123.html'
    article.parent.mkdir(parents=True)
    article.write_bytes(b'<html>\r\n<title>Source title</title><body>Actual ASR 123</body></html>\r\n')
    (site/'staged.txt').write_text('keep index',encoding='utf-8')
    run(site, 'add', 'staged.txt')
    index_before = (site/'.git/index').read_bytes()
    status_before = run(site, 'status', '--porcelain=v1', '-z')
    config = AppConfig({'app':{'data_dir':str(tmp_path/'data')},'publishing':{
        'github_pages':{'output_dir':str(site),'preserve_historical_pages':True},
        'github_sync':{'enabled':True,'auto_commit':True,'auto_push':True,'git_executable':git,
                       'repo_dir':str(site),'allowed_paths':['index.html','notes/douyin/author/*.html']}}}, tmp_path/'config.yaml')
    manager = GithubSyncManager(config)
    result = manager.sync_single_article(article, 'Source title')
    assert result['ok'] and result['pushed']
    tip = run(remote,'rev-parse','refs/heads/gh-pages')
    assert run(remote,'rev-parse',tip+'^') == baseline
    paths = set(run(remote,'diff','--name-only',baseline,tip).splitlines())
    assert paths == {'index.html','notes/douyin/author/index.html','notes/douyin/author/new_123.html'}
    assert run(remote,'show',tip+':old.html') == '<p>historical</p>'
    assert '<a href="old.html">old</a>' in run(remote,'show',tip+':index.html')
    assert 'unrelated.html' not in run(remote,'ls-tree','-r','--name-only',tip)
    assert run(site,'rev-parse','HEAD') == original_head
    assert (site/'.git/index').read_bytes() == index_before
    assert run(site,'status','--porcelain=v1','-z') == status_before
    import hashlib
    canonical = subprocess.check_output([git, '-C', str(remote), 'show', tip+':notes/douyin/author/new_123.html'])
    assert canonical.replace(b'\r\n', b'\n') == article.read_bytes().replace(b'\r\n', b'\n')
    assert result['artifact_sha256'] == hashlib.sha256(canonical).hexdigest()
