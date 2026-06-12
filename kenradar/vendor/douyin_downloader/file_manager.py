from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileManager:
    def __init__(self, base_path: str = "./Downloaded"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def download_file(
        self,
        url: str,
        save_path: Path,
        session: Any | None = None,
        headers: dict[str, str] | None = None,
        proxy: str | None = None,
    ) -> bool:
        import aiofiles
        import aiohttp

        save_path.parent.mkdir(parents=True, exist_ok=True)
        should_close = False
        if session is None:
            session = aiohttp.ClientSession(headers=headers or {})
            should_close = True

        tmp_path = save_path.with_suffix(save_path.suffix + ".tmp")
        try:
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=1800, sock_read=120),
                headers=headers,
                proxy=proxy or None,
            ) as response:
                if response.status != 200:
                    logger.warning("下载失败: status=%s, url=%s", response.status, url[:160])
                    return False
                expected_size = response.content_length
                written = 0
                async with aiofiles.open(tmp_path, "wb") as file:
                    async for chunk in response.content.iter_chunked(8192):
                        await file.write(chunk)
                        written += len(chunk)
                if expected_size is not None and written != expected_size:
                    logger.warning("下载大小不匹配: expected=%s, got=%s, file=%s", expected_size, written, save_path.name)
                    tmp_path.unlink(missing_ok=True)
                    return False
                os.replace(str(tmp_path), str(save_path))
                return True
        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning("下载异常: %s: %s", type(exc).__name__, exc)
            tmp_path.unlink(missing_ok=True)
            return False
        finally:
            if should_close:
                await session.close()

    def file_exists(self, file_path: Path) -> bool:
        try:
            return file_path.exists() and file_path.stat().st_size > 0
        except OSError:
            return False

    def get_file_size(self, file_path: Path) -> int:
        try:
            return file_path.stat().st_size if self.file_exists(file_path) else 0
        except OSError:
            return 0
