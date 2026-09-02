"""Explicit connector registry — no plugin discovery, no dynamic loading."""

from __future__ import annotations

from typing import Any

from kenradar.sources.contracts import SourceConnector


def _load_connector_classes() -> dict[str, type]:
    from kenradar.sources.douyin.connector import DouyinConnector
    from kenradar.sources.xiaoyuzhou.connector import XiaoyuzhouConnector

    return {
        "douyin": DouyinConnector,
        "xiaoyuzhou": XiaoyuzhouConnector,
    }


# Explicit launch-platform map; Bilibili/YouTube are intentionally absent.
CONNECTORS: dict[str, type] = _load_connector_classes()


def connectors_for_config(config: Any) -> dict[str, SourceConnector]:
    """Build fresh connector instances bound to one config."""
    return {platform: cls(config) for platform, cls in CONNECTORS.items()}


def connector_for_url(url: str, config: Any = None) -> SourceConnector | None:
    """Pick the launch connector that claims this URL, if any."""
    from urllib.parse import urlsplit

    host = (urlsplit(str(url or "")).netloc or "").lower()
    if not host:
        return None
    if host.endswith("douyin.com") or host.endswith("iesdouyin.com"):
        platform = "douyin"
    elif host.endswith("xiaoyuzhoufm.com"):
        platform = "xiaoyuzhou"
    else:
        return None
    return CONNECTORS[platform](config)
