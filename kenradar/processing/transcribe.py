from __future__ import annotations

from typing import Any

from kenradar.processing.base import StageHandler, StageContext, ResourceRequirement


class TranscribeHandler(StageHandler):
    """音频转录 handler"""

    name = "transcribe"
    requirements = [
        ResourceRequirement(pool="cpu:transcribe", capacity=2, exclusive=False),
        ResourceRequirement(pool="gpu:0", capacity=1, exclusive=True, priority=30),
    ]

    def __init__(self, workflow: Any, database: Any, config: dict[str, Any]):
        self._workflow = workflow
        self._database = database
        self._config = config

    async def execute(self, ctx: StageContext) -> dict[str, Any]:
        return await self._workflow._transcribe_single(ctx.payload.get("aweme_id", ""))
