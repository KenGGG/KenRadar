from __future__ import annotations

from typing import Any

from kenradar.processing.base import StageHandler, StageContext, ResourceRequirement


class DownloadHandler(StageHandler):
    """视频下载 handler"""

    name = "download"
    requirements = [
        ResourceRequirement(pool="io:download", capacity=1, exclusive=False),
    ]

    def __init__(self, workflow: Any, database: Any, config: dict[str, Any]):
        self._workflow = workflow
        self._database = database
        self._config = config

    async def execute(self, ctx: StageContext) -> dict[str, Any]:
        aweme_id = ctx.payload.get("aweme_id")
        url = ctx.payload.get("url", "")
        if not aweme_id:
            return {"error": "missing aweme_id"}
        result = self._workflow.downloader.download(aweme_id, url)
        return {"aweme_id": aweme_id, "downloaded": result is not None, "path": str(result or "")}
