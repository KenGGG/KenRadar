from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PdfValidationResult:
    ok: bool
    file_size: int
    file_hash: str
    error: str = ""


def compute_file_hash(file_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_pdf(file_path: str | Path, *, min_size_bytes: int = 20 * 1024, content_type: str = "") -> PdfValidationResult:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return PdfValidationResult(False, 0, "", "pdf_missing")
    size = path.stat().st_size
    file_hash = compute_file_hash(path)
    if size <= min_size_bytes:
        return PdfValidationResult(False, size, file_hash, f"file_too_small:{size}")
    with path.open("rb") as handle:
        header = handle.read(1024)
    if b"%PDF" not in header[:1024]:
        if "pdf" not in str(content_type or "").lower():
            return PdfValidationResult(False, size, file_hash, "invalid_pdf_header")
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        _ = len(reader.pages)
    except ImportError:
        pass
    except Exception as exc:
        return PdfValidationResult(False, size, file_hash, f"pdf_parse_failed:{exc}")
    return PdfValidationResult(True, size, file_hash)
