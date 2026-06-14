from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class SourceItem:
    """来源内容条目"""
    id: str
    title: str | None = None
    description: str | None = None
    url: str | None = None
    author_name: str | None = None
    published_at: str | None = None
    extra: dict[str, Any] | None = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """内容源适配器协议"""
    platform: str

    def fetch_items(self, sec_uid: str, max_count: int = 30, **kwargs: Any) -> list[SourceItem]:
        """获取博主最新内容列表"""
        ...

    def resolve_user(self, url: str | None = None, name: str | None = None, sec_uid: str | None = None) -> dict[str, Any]:
        """解析用户信息"""
        ...


@runtime_checkable
class Transcriber(Protocol):
    """转录器协议"""

    def transcribe(self, audio_path: str, **kwargs: Any) -> dict[str, Any]:
        """转录音频，返回文本和元数据"""
        ...


@runtime_checkable
class Organizer(Protocol):
    """AI 整理器协议"""

    def organize(self, transcript: str, title: str | None = None, **kwargs: Any) -> dict[str, Any]:
        """整理转录文本，返回结构化摘要"""
        ...
