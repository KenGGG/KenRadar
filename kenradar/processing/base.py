from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ResourceRequirement:
    """资源需求定义"""
    pool: str           # 资源池名称
    capacity: int = 1   # 所需容量
    exclusive: bool = False  # 是否需要独占
    priority: int = 50  # 优先级


@dataclass
class StageContext:
    """Stage 执行上下文"""
    task_run_id: int | None = None
    content_item_id: int | None = None
    creator_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class StageHandler(Protocol):
    """Stage handler 协议"""
    name: str
    requirements: list[ResourceRequirement]

    async def execute(self, ctx: StageContext) -> dict[str, Any]:
        """执行 stage 任务"""
        ...
