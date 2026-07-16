"""Keep repository-local secrets from leaking between configuration tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_process_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent load_config(.env) from changing unrelated test expectations.

    Individual tests that exercise environment precedence set the variable
    explicitly with monkeypatch; all other tests should be independent of the
    developer's local `.env` file.
    """

    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)

