"""PDF validation and page-wise text extraction.

Uses PDFium (via pypdfium2) — Chrome's PDF engine. On the FAA PHAK, pypdf needed 26 s and ~1.2 GB
for a single vector-heavy page; PDFium extracts the whole 30-page chapter in ~1 s under ~250 MB,
which matters on a 4 GB host.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

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
        doc = pdfium.PdfDocument(str(path))
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise PdfValidationError("PDF is password-protected.") from exc
        raise PdfValidationError(f"Could not read PDF: {exc}") from exc

    try:
        page_count = len(doc)
        if page_count == 0:
            raise PdfValidationError("PDF has no pages.")
        if page_count > max_pages:
            raise PdfValidationError(f"PDF has {page_count} pages; the limit is {max_pages}.")

        title = None
        try:
            title = (doc.get_metadata_dict().get("Title") or "").strip() or None
        except Exception:  # noqa: S110 — malformed metadata is common and non-fatal
            pass

        pages: list[PageText] = []
        for i in range(page_count):
            raw = ""
            try:
                page = doc[i]
                textpage = page.get_textpage()
                try:
                    raw = textpage.get_text_range() or ""
                finally:
                    textpage.close()
                    page.close()
            except Exception:
                logger.warning("failed to extract page %s", i + 1)
            pages.append(PageText(i + 1, clean_text(raw)))
    finally:
        doc.close()

    pages = strip_repeated_headers_footers(pages)
    total_chars = sum(len(p.text) for p in pages)
    if total_chars < 50:
        raise PdfValidationError(
            "No extractable text found — this looks like a scanned PDF (OCR is not supported)."
        )
    return ExtractedPdf(pages=pages, page_count=page_count, title=title)
