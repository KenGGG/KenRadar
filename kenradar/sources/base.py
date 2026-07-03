from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass(slots=True)
class ContentItem:
    platform: str
    creator: str | None
    creator_id: str | None
    content_id: str
    source_url: str
    original_title: str
    published_at: datetime | None
    media_type: str
    duration: int | None
    description: str | None
    cover_url: str | None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    media_url: str | None = None
    local_path: str | None = None
    failure_reason: str | None = None


class SourceAdapter(Protocol):
    def resolve_source(self, url_or_config: str) -> list[ContentItem]:
        ...

    def fetch_latest(self, source_config: dict[str, Any]) -> list[ContentItem]:
        ...

    def download_media(self, item: ContentItem) -> Path | None:
        ...
