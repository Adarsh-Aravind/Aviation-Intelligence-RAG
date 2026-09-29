"""PDF validation and page-wise text extraction (pypdf — pure Python, low memory)."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.models.domain import PageText

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_MULTISPACE = re.compile(r"[ \t ]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")


class PdfValidationError(ValueError):
    """Raised when a file is not a usable PDF (user-facing message)."""


@dataclass(slots=True)
class ExtractedPdf:
    pages: list[PageText]
    page_count: int
    title: str | None


def has_pdf_magic(path: Path) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(1024)
    return PDF_MAGIC in head


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(r"\1\2", text)  # re-join words hyphenated across lines
    text = "\n".join(_MULTISPACE.sub(" ", line).strip() for line in text.split("\n"))
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def _line_key(line: str) -> str:
    # Page numbers differ between pages ("Page 3 of 90"), so mask digits before comparing.
    return re.sub(r"\d+", "#", line.strip().lower())


def strip_repeated_headers_footers(pages: list[PageText], edge_lines: int = 2) -> list[PageText]:
    """Remove lines that repeat at the top/bottom of many pages (running headers, footers, page numbers)."""
    if len(pages) < 4:
        return pages
    counts: Counter[str] = Counter()
    for page in pages:
        lines = [ln for ln in page.text.split("\n") if ln.strip()]
        edges = set(lines[:edge_lines] + lines[-edge_lines:])
        counts.update({_line_key(ln) for ln in edges})
    threshold = max(3, int(len(pages) * 0.5))
    repeated = {k for k, n in counts.items() if n >= threshold}
    # Bare page numbers ("12", "- 12 -", "Page 12") are always noise at page edges.
    bare_number = re.compile(r"^[-–\s]*(page\s*)?#+(\s*of\s*#+)?[-–\s]*$")
    cleaned: list[PageText] = []
    for page in pages:
        lines = page.text.split("\n")
        non_empty = [i for i, ln in enumerate(lines) if ln.strip()]
        edge_idx = set(non_empty[:edge_lines] + non_empty[-edge_lines:])
        kept = [
            ln
            for i, ln in enumerate(lines)
            if not (i in edge_idx and (_line_key(ln) in repeated or bare_number.match(_line_key(ln))))
        ]
        cleaned.append(PageText(page.page_number, "\n".join(kept).strip()))
    return cleaned


def extract_pdf(path: Path, max_pages: int) -> ExtractedPdf:
    """Extract cleaned text per page. Raises PdfValidationError with a user-facing message."""
    if not has_pdf_magic(path):
        raise PdfValidationError("File is not a valid PDF.")
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise PdfValidationError("PDF is password-protected.")
            except PdfValidationError:
                raise
            except Exception as exc:
                raise PdfValidationError("PDF is encrypted and cannot be read.") from exc
        page_count = len(reader.pages)
    except PdfValidationError:
        raise
    except (PdfReadError, Exception) as exc:  # pypdf raises a variety of errors on corrupt files
        raise PdfValidationError(f"Could not read PDF: {exc.__class__.__name__}") from exc

    if page_count == 0:
        raise PdfValidationError("PDF has no pages.")
    if page_count > max_pages:
        raise PdfValidationError(f"PDF has {page_count} pages; the limit is {max_pages}.")

    title = None
    try:
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title).strip() or None
    except Exception:  # noqa: S110 — malformed metadata is common and non-fatal
        pass

    pages: list[PageText] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            logger.warning("failed to extract page %s", i)
            raw = ""
        pages.append(PageText(i, clean_text(raw)))

    pages = strip_repeated_headers_footers(pages)
    total_chars = sum(len(p.text) for p in pages)
    if total_chars < 50:
        raise PdfValidationError(
            "No extractable text found — this looks like a scanned PDF (OCR is not supported)."
        )
    return ExtractedPdf(pages=pages, page_count=page_count, title=title)
