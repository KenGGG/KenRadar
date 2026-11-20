import shutil
import subprocess

from kenradar.core.config import AppConfig
from kenradar.publishing.github_sync import GithubSyncManager


def test_missing_remote_commit_is_fetched_before_publication_audit(tmp_path):
    git = shutil.which('git')

    def run(root, *args):
        return subprocess.run(
            [git, '-c', 'user.name=Fixture', '-c',
             'user.email=fixture@example.invalid', *args],
            cwd=root, check=True, capture_output=True, text=True,
        ).stdout.strip()

    remote = tmp_path / 'remote.git'
    run(tmp_path, 'init', '--bare', str(remote))
    writer = tmp_path / 'writer'
    run(tmp_path, 'clone', str(remote), str(writer))
    run(writer, 'checkout', '-b', 'gh-pages')
    (writer / 'index.html').write_text('baseline', encoding='utf-8')
    run(writer, 'add', '.')
    run(writer, 'commit', '-m', 'baseline')
    run(writer, 'push', 'origin', 'gh-pages')
    local = tmp_path / 'local'
    run(tmp_path, 'clone', '--branch', 'gh-pages', str(remote), str(local))
    (writer / 'index.html').write_text('remote update', encoding='utf-8')
    run(writer, 'commit', '-am', 'remote update')
    run(writer, 'push', 'origin', 'gh-pages')
    revision = run(writer, 'rev-parse', 'HEAD')
    config = AppConfig({'publishing': {'github_sync': {
        'repo_dir': str(local), 'allowed_paths': ['index.html'],
    }}}, tmp_path / 'config/config.yaml')
    manager = GithubSyncManager(config)
    assert manager._run_git(['cat-file', '-e', revision], check=False).returncode
    manager._guard_outgoing_policy_snapshot()
    assert manager._run_git(['cat-file', '-e', revision], check=False).returncode == 0
    assert (local / 'index.html').read_text(encoding='utf-8') == 'baseline'
