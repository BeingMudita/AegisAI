"""Text extraction from source documents (PDF, TXT, MD)."""

from __future__ import annotations

from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md"}


def extract_pdf(path: Path) -> str:
    """Extract text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise RuntimeError(
            "pypdf is required for PDF extraction. Install with `pip install pypdf`."
        ) from exc

    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def extract_text(path: Path) -> str:
    """Extract plain text from a supported document by suffix."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf(path)
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {suffix} ({path.name})")
