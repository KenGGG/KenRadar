"""Private note/brief snapshot files with explicit root mapping and no overwrite."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .offline_migration import mapped_path, sha_file


def snapshot_files(data_root, package, *, writers_stopped=False):
    if not writers_stopped:
        raise ValueError("文件快照要求先停止相应写入并显式声明 writers_stopped")
    root, package = Path(data_root).resolve(), Path(package).resolve()
    entries = []
    for folder in ("notes", "briefs"):
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("文件快照拒绝数据根以外的链接")
            if path.name.startswith(".env") or any(word in path.name.lower() for word in ("cookie", "api_key")):
                raise ValueError("笔记目录包含敏感资料文件，请独立处理")
            relative = path.relative_to(root).as_posix()
            target = package / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            before = sha_file(path)
            with path.open("rb") as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            if sha_file(path) != before or sha_file(target) != before:
                raise ValueError("文件在快照期间变化，请停止写入后重新生成包")
            entries.append({"relative": relative, "file": "files/" + relative, "source_path": str(path),
                "sha256": before, "size": path.stat().st_size})
    return {"files_root": str(root), "files": entries, "file_consistency": "operator_declared_writers_stopped"}


def import_files(package, manifest, mappings):
    package = Path(package).resolve()
    entries = manifest.get("files", [])
    result = {"verified": [], "unmapped": [], "missing": []}
    for entry in entries:
        relative = PurePosixPath(entry["file"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "files":
            raise ValueError("文件 manifest 路径不合法")
        source = (package / Path(relative)).resolve()
        if not source.is_relative_to(package):
            raise ValueError("快照文件链接越界")
        if not source.is_file():
            result["missing"].append(entry["relative"])
            continue
        if sha_file(source) != entry["sha256"]:
            raise ValueError("文件快照哈希不一致")
        mapped = mapped_path(entry["source_path"], mappings)
        if mapped == entry["source_path"]:
            result["unmapped"].append(entry["relative"])
            continue
        target = Path(mapped).resolve()
        allowed = [Path(root).resolve() for root in mappings.values()]
        if not any(target.is_relative_to(root) and target != root for root in allowed):
            raise ValueError("文件映射目标越界")
        if target.exists():
            if not target.is_file() or sha_file(target) != entry["sha256"]:
                raise FileExistsError("映射目标已有不同文件，拒绝覆盖")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".kenradar-import-", dir=target.parent)
            temporary = Path(temporary)
            try:
                with os.fdopen(descriptor, "wb") as destination, source.open("rb") as handle:
                    shutil.copyfileobj(handle, destination)
                    destination.flush()
                    os.fsync(destination.fileno())
                if sha_file(temporary) != entry["sha256"]:
                    raise ValueError("复制后的文件哈希不一致")
                # Windows rename refuses an existing target. POSIX rename
                # replaces it, so use an exclusive hard link on that platform.
                if os.name == "nt":
                    os.rename(temporary, target)
                else:
                    os.link(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        result["verified"].append(entry["relative"])
    return result
