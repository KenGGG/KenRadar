from __future__ import annotations

import tomllib
from pathlib import Path


def test_runtime_dependencies_include_aiofiles_for_douyin_downloads():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]

    assert any(requirement.lower().startswith("aiofiles") for requirement in dependencies)
