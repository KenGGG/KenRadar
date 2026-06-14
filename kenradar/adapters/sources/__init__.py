# 来源适配器注册表

from typing import Any

_registry: dict[str, Any] = {}


def register(platform: str, adapter_cls: type) -> None:
    _registry[platform.lower()] = adapter_cls


def get_adapter(platform: str) -> Any | None:
    return _registry.get(platform.lower())


def list_platforms() -> list[str]:
    return list(_registry.keys())
