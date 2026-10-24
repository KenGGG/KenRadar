"""Regression for task 26's HTTPS empty-reply push failure; no live publication."""
from types import SimpleNamespace

import pytest

from kenradar.publishing.github_sync import GithubSyncError, GithubSyncManager


class RetryConfig:
    def get(self, key, default=None):
        return {"publishing.github_sync.push_retry_count": 3,
                "publishing.github_sync.push_retry_delay": 1}.get(key, default)


def retry_manager(monkeypatch, errors):
    manager = object.__new__(GithubSyncManager)
    manager.config = RetryConfig()
    calls, sleeps = [], []

    def run(args, check=True):
        calls.append(args)
        error = errors[min(len(calls) - 1, len(errors) - 1)]
        return SimpleNamespace(returncode=1 if error else 0, stdout="", stderr=error)

    monkeypatch.setattr(manager, "_run_git", run)
    monkeypatch.setattr("kenradar.publishing.github_sync.time.sleep", sleeps.append)
    return manager, calls, sleeps


EMPTY_REPLY = "fatal: unable to access 'https://github.com/KenGGG/KenRadar-pages.git/': Empty reply from server"


def test_empty_reply_retries_same_push_then_succeeds(monkeypatch):
    manager, calls, sleeps = retry_manager(monkeypatch, [EMPTY_REPLY, ""])
    manager._run_git_push_with_retry()
    assert calls == [["push"], ["push"]]
    assert sleeps == [1]


def test_empty_reply_exhaustion_is_bounded(monkeypatch):
    manager, calls, sleeps = retry_manager(monkeypatch, [EMPTY_REPLY])
    with pytest.raises(GithubSyncError, match="Empty reply from server"):
        manager._run_git_push_with_retry()
    assert calls == [["push"], ["push"], ["push"]]
    assert sleeps == [1, 2]


@pytest.mark.parametrize("error", [
    "fatal: Authentication failed",
    "fatal: SSL certificate problem: unable to get local issuer certificate",
    "! [rejected] gh-pages -> gh-pages (non-fast-forward)",
])
def test_permanent_errors_are_not_retried(monkeypatch, error):
    manager, calls, sleeps = retry_manager(monkeypatch, [error])
    with pytest.raises(GithubSyncError):
        manager._run_git_push_with_retry()
    assert calls == [["push"]]
    assert sleeps == []
