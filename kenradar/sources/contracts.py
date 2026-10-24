"""Explicit connector contracts for the V2 media radar.

The generic layer only understands platform, external source/content ids,
titles, timestamps, media type, URL and raw metadata. Every platform-specific
field stays inside the connector or its ``raw_metadata`` payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class SourceIdentityMismatch(ValueError):
    """Upstream metadata belongs to a different requested content item."""

    error_code = "SOURCE_IDENTITY_MISMATCH"


class SourceParseChanged(ValueError):
    """The upstream page or feed structure changed and parsing returned nothing.

    Raising this must never be reported to the user as "no updates"; it maps to
    the ``SOURCE_PARSE_CHANGED`` error code.
    """

    error_code = "SOURCE_PARSE_CHANGED"


@dataclass(frozen=True)
class SourceDescriptor:
    """A subscribed source (douyin creator, xiaoyuzhou podcast, RSS feed)."""

    platform: str
    external_source_id: str
    display_name: str
    source_url: str
    avatar_url: str = ""
    feed_url: str = ""
    history_capability: str = "unknown"
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentDescriptor:
    """A single addressable piece of content on a platform."""

    platform: str
    external_content_id: str
    external_source_id: str
    title: str
    published_at: datetime | None
    media_type: str
    url: str
    description: str = ""
    duration: int | None = None
    cover_url: str = ""
    media_url: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContentPage:
    """One page of a listing; cursors are opaque strings owned by the connector."""

    items: list[ContentDescriptor]
    next_cursor: str | None = None
    has_more: bool = False
    history_capability: str = "unknown"


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of downloading the current media for a content descriptor."""

    success: bool
    path: Path | None = None
    media_url: str = ""
    error_code: str = ""
    error_message: str = ""


@runtime_checkable
class SourceConnector(Protocol):
    """Capabilities required of a launch platform connector."""

    platform: str

    def match_url(self, url: str) -> bool: ...

    async def resolve_source(self, url: str) -> SourceDescriptor: ...

    async def resolve_content(self, url: str) -> ContentDescriptor: ...

    async def list_recent(
        self, source: SourceDescriptor, cursor: str | None = None
    ) -> ContentPage: ...

    async def list_history(
        self, source: SourceDescriptor, cursor: str | None = None
    ) -> ContentPage: ...

    async def download(
        self, content: ContentDescriptor, target_dir: Path
    ) -> DownloadResult: ...
