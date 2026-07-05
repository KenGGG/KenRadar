from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotebookSource:
    source_id: str
    title: str
    status: str = "uploaded"


@dataclass(frozen=True)
class NotebookAnswer:
    text: str
    raw: str
    references: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: str = ""
    source_ids: list[str] = field(default_factory=list)


class NotebookLMClient:
    """Wrapper for notebooklm-py 0.7.x (NotebookLMClient from_storage API).

    Uses the official ``notebooklm.NotebookLMClient.from_storage()`` async
    context manager and calls ``client.notebooks.*``, ``client.sources.*``,
    ``client.chat.*`` directly.  The previous dynamic-probing wrapper has been
    replaced because it assumed wrong method names and parameter conventions.
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._ctx: Any = None
        self._failure_count = 0
        self._circuit_open_until = 0.0

    def _before_request(self) -> None:
        now = time.monotonic()
        if self._circuit_open_until > now:
            remaining = int(self._circuit_open_until - now)
            raise RuntimeError(f"NotebookLM 暂停调用中，约 {remaining}s 后自动恢复；请检查登录状态或服务可用性。")

    def _record_success(self) -> None:
        self._failure_count = 0
        self._circuit_open_until = 0.0

    def _record_failure(self, operation: str, exc: BaseException) -> None:
        self._failure_count += 1
        if self._failure_count >= 3:
            self._circuit_open_until = time.monotonic() + 600
            logger.warning("NotebookLM 连续失败，断路器暂停 10 分钟: operation=%s error=%s", operation, exc)

    async def _guarded(self, operation: str, func: Callable[[], Awaitable[Any]]) -> Any:
        self._before_request()
        try:
            result = await func()
        except Exception as exc:
            self._record_failure(operation, exc)
            raise
        self._record_success()
        return result

    async def _ensure_client(self) -> Any:
        """Lazily create and enter the async context manager exactly once."""
        if self._client is not None:
            return self._client
        try:
            import notebooklm  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "未安装 notebooklm-py，无法创建 NotebookLM 临时笔记。"
                "请执行: pip install 'notebooklm-py[browser]'"
            ) from exc
        self._ctx = notebooklm.NotebookLMClient.from_storage()
        self._client = await self._ctx.__aenter__()
        return self._client

    async def close(self) -> None:
        """Gracefully close the underlying HTTP transport."""
        if self._ctx is not None:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                logger.debug("NotebookLM client close error", exc_info=True)
            finally:
                self._ctx = None
                self._client = None

    # ------------------------------------------------------------------
    # Notebook lifecycle
    # ------------------------------------------------------------------

    async def create_notebook(self, title: str) -> dict[str, str]:
        async def call() -> Any:
            client = await self._ensure_client()
            return await client.notebooks.create(title)

        nb = await self._guarded("create_notebook", call)
        return {"id": nb.id, "title": nb.title}

    async def delete_notebook(self, notebook_id: str) -> None:
        async def call() -> None:
            client = await self._ensure_client()
            await client.notebooks.delete(notebook_id)

        await self._guarded("delete_notebook", call)

    # ------------------------------------------------------------------
    # Source upload
    # ------------------------------------------------------------------

    async def upload_pdf(
        self,
        notebook_id: str,
        file_path: str | Path,
        title: str | None = None,
    ) -> NotebookSource:
        """Upload a single PDF file as a source.

        Sets ``wait=False`` so the call returns as soon as the upload
        completes; the caller must use :meth:`wait_sources_ready` to poll
        for processing completion afterwards.
        """
        async def call() -> Any:
            client = await self._ensure_client()
            return await client.sources.add_file(
                notebook_id,
                str(file_path),
                wait=False,
                title=title,
            )

        source = await self._guarded("upload_pdf", call)
        return NotebookSource(
            source_id=source.id,
            title=source.title or title or Path(file_path).name,
            status="uploaded",
        )

    async def wait_sources_ready(
        self,
        notebook_id: str,
        source_ids: list[str],
        timeout_seconds: int = 900,
    ) -> list[NotebookSource]:
        """Block until all *source_ids* reach READY (or ERROR) status."""
        async def call() -> Any:
            client = await self._ensure_client()
            return await client.sources.wait_for_sources(
                notebook_id,
                source_ids,
                timeout=float(timeout_seconds),
            )

        ready = await self._guarded("wait_sources_ready", call)
        return [
            NotebookSource(
                source_id=s.id,
                title=s.title or s.id,
                status="ready" if s.is_ready else ("error" if s.is_error else "processing"),
            )
            for s in ready
        ]

    async def delete_pdf(self, notebook_id: str, source_id: str) -> None:
        """Delete one uploaded PDF/source from a NotebookLM notebook."""
        async def call() -> None:
            client = await self._ensure_client()
            await client.sources.delete(notebook_id, source_id)

        await self._guarded("delete_pdf", call)

    async def delete_source(self, notebook_id: str, source_id: str) -> None:
        """Alias for callers that use NotebookLM's native source wording."""
        await self.delete_pdf(notebook_id, source_id)

    # ------------------------------------------------------------------
    # Chat / Q&A
    # ------------------------------------------------------------------

    async def ask_question(
        self,
        notebook_id: str,
        prompt: str,
    ) -> NotebookAnswer:
        async def call() -> Any:
            client = await self._ensure_client()
            return await client.chat.ask(notebook_id, prompt)

        result = await self._guarded("ask_question", call)
        refs = [
            {
                "source_id": r.source_id,
                "citation_number": r.citation_number,
                "cited_text": r.cited_text or "",
            }
            for r in (result.references or [])
        ]
        return NotebookAnswer(
            text=result.answer,
            raw=result.raw_response,
            references=refs,
            conversation_id=result.conversation_id,
            source_ids=list({r.source_id for r in (result.references or [])}),
        )
