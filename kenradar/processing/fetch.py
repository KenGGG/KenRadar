from __future__ import annotations

from typing import Any

from kenradar.processing.base import StageHandler, StageContext, ResourceRequirement


class FetchHandler(StageHandler):
    """博主最新内容抓取 handler"""

    name = "fetch"
    requirements = [
        ResourceRequirement(pool="io:douyin_fetch", capacity=1, exclusive=False),
    ]

    def __init__(self, workflow: Any, database: Any, config: dict[str, Any]):
        self._workflow = workflow
        self._database = database
        self._config = config

    async def execute(self, ctx: StageContext) -> dict[str, Any]:
        sec_uid = ctx.payload.get("sec_uid")
        max_count = int(ctx.payload.get("max_count", 30))
        if not sec_uid:
            return {"error": "missing sec_uid", "fetched": 0}
        result = await self._workflow._fetch_latest_videos(sec_uid, max_count=max_count)
        return {
            "fetched": len(result.get("items", [])),
            "items": result.get("items", []),
        }
