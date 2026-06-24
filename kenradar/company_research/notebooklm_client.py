from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
        client = await self._ensure_client()
        nb = await client.notebooks.create(title)
        return {"id": nb.id, "title": nb.title}

    async def delete_notebook(self, notebook_id: str) -> None:
        client = await self._ensure_client()
        await client.notebooks.delete(notebook_id)

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
        client = await self._ensure_client()
        source = await client.sources.add_file(
            notebook_id,
            str(file_path),
            wait=False,
            title=title,
        )
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
        client = await self._ensure_client()
        ready = await client.sources.wait_for_sources(
            notebook_id,
            source_ids,
            timeout=float(timeout_seconds),
        )
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
        client = await self._ensure_client()
        await client.sources.delete(notebook_id, source_id)

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
        client = await self._ensure_client()
        result = await client.chat.ask(notebook_id, prompt)
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
