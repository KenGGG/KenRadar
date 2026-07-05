from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CleanupManager:
    def __init__(self, workflow: Any):
        self.workflow = workflow

    def cleanup_processed_downloads(self, dry_run: bool = False) -> dict[str, Any]:
        workflow = self.workflow
        download_root = workflow.config.download_dir.resolve()
        stats: dict[str, Any] = {"scanned": 0, "eligible_items": 0, "files": 0, "bytes": 0, "dry_run": dry_run}
        grouped: dict[str, list[Path]] = {}
        try:
            files = [path for path in download_root.glob("**/*") if path.is_file()]
        except OSError as exc:
            logger.warning("扫描下载目录失败: %s", exc)
            return stats

        for path in files:
            if not self.is_download_artifact(path):
                continue
            aweme_id = self.extract_aweme_id_from_artifact(path)
            if not aweme_id:
                continue
            grouped.setdefault(aweme_id, []).append(path)

        list_download_paths = getattr(workflow.database, "list_aweme_download_paths", None)
        if callable(list_download_paths):
            for row in list_download_paths():
                aweme_id = str(row.get("aweme_id") or "").strip()
                local_path = self.resolve_download_artifact_path(row.get("local_path"), download_root)
                if not aweme_id or local_path is None or not local_path.is_file():
                    continue
                paths = grouped.setdefault(aweme_id, [])
                if local_path not in paths:
                    paths.append(local_path)

        stats["scanned"] = sum(len(paths) for paths in grouped.values())
        for aweme_id, paths in grouped.items():
            if not self.has_persisted_note_and_transcript(aweme_id):
                continue
            stats["eligible_items"] += 1
            stats["files"] += len(paths)
            stats["bytes"] += sum(path.stat().st_size for path in paths if path.exists())
            if not dry_run:
                self.cleanup_download_artifacts(aweme_id)
        return stats

    def cleanup_download_artifacts(
        self,
        aweme_id: str,
        video_path: Path | str | None = None,
        transcript: dict[str, Any] | None = None,
    ) -> int:
        workflow = self.workflow
        if not aweme_id or not workflow.config.get("ai.whisper.cleanup_video", True):
            return 0

        download_root = workflow.config.download_dir.resolve()
        candidates: set[Path] = set()

        def add_candidate(value: Any) -> None:
            if not value:
                return
            path = Path(str(value))
            try:
                resolved = path.resolve()
            except OSError:
                return
            try:
                if not resolved.is_relative_to(download_root):
                    return
            except AttributeError:
                if download_root not in resolved.parents and resolved != download_root:
                    return
            candidates.add(resolved)

        add_candidate(video_path)
        get_local_path = getattr(workflow.database, "get_aweme_local_path", None)
        if callable(get_local_path):
            add_candidate(get_local_path(aweme_id))
        for key in ("text_path", "txt_path", "json_path"):
            add_candidate((transcript or {}).get(key))
        try:
            for candidate in download_root.glob(f"**/*{aweme_id}*"):
                if candidate.is_file() and self.is_download_artifact(candidate):
                    add_candidate(candidate)
        except OSError as exc:
            logger.debug("扫描下载临时文件失败: aweme_id=%s error=%s", aweme_id, exc)

        removed = 0
        for path in sorted(candidates):
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    removed += 1
            except OSError as exc:
                logger.warning("清理下载临时文件失败: aweme_id=%s path=%s error=%s", aweme_id, path, exc)
                try:
                    workflow.alerts.warning(
                        "download_cleanup",
                        f"已完成内容的下载临时文件清理失败: {exc}",
                        aweme_id=aweme_id,
                        context={"path": str(path)},
                    )
                except Exception:
                    logger.exception("记录下载临时文件清理告警失败: aweme_id=%s path=%s", aweme_id, path)

        if removed:
            logger.info("已清理下载临时文件: aweme_id=%s files=%s", aweme_id, removed)
        clear_paths = getattr(workflow.database, "clear_transcript_paths", None)
        if callable(clear_paths):
            clear_paths(aweme_id)
        self.prune_empty_download_dirs(download_root)
        return removed

    @staticmethod
    def is_download_artifact(path: Path) -> bool:
        return (
            path.name.endswith(".mp4")
            or path.name.endswith(".tmp")
            or path.name.endswith(".transcript.txt")
            or path.name.endswith(".transcript.json")
        )

    @staticmethod
    def extract_aweme_id_from_artifact(path: Path) -> str:
        matches = re.findall(r"(?<!\d)(\d{16,20})(?!\d)", path.name)
        return matches[-1] if matches else ""

    @staticmethod
    def resolve_download_artifact_path(value: Any, download_root: Path) -> Path | None:
        if not value:
            return None
        path = Path(str(value))
        try:
            resolved = path.resolve()
        except OSError:
            return None
        try:
            if not resolved.is_relative_to(download_root):
                return None
        except AttributeError:
            if download_root not in resolved.parents and resolved != download_root:
                return None
        return resolved

    def has_persisted_note_and_transcript(self, aweme_id: str) -> bool:
        workflow = self.workflow
        transcript = workflow.database.get_successful_transcript(aweme_id)
        if not transcript or not str(transcript.get("text_content") or "").strip():
            return False
        summary = workflow.database.get_summary(aweme_id)
        summary_path = str((summary or {}).get("summary_path") or "").strip()
        if not summary_path:
            return False
        path = Path(summary_path)
        if not path.is_absolute():
            path = workflow.config.root_dir / path
        return path.exists()

    @staticmethod
    def prune_empty_download_dirs(download_root: Path) -> None:
        try:
            dirs = sorted((path for path in download_root.glob("**/*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True)
        except OSError:
            return
        for path in dirs:
            try:
                path.rmdir()
            except OSError:
                pass
