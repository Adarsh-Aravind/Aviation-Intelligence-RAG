from pathlib import Path

import pytest

from app.models.domain import PageText
from app.services.pdf import (
    PdfValidationError,
    clean_text,
    extract_pdf,
    strip_repeated_headers_footers,
)
from tests.conftest import make_pdf


def _write(tmp_path: Path, data: bytes) -> Path:
    p = tmp_path / "doc.pdf"
    p.write_bytes(data)
    return p


def test_extracts_text_per_page(tmp_path, pdf_bytes):
    result = extract_pdf(_write(tmp_path, pdf_bytes), max_pages=50)
    assert result.page_count == 4
    assert [p.page_number for p in result.pages] == [1, 2, 3, 4]
    assert "Density altitude" in result.pages[1].text
    assert "Stall" in result.pages[2].text


def test_repeated_header_and_page_numbers_removed(tmp_path, pdf_bytes):
    result = extract_pdf(_write(tmp_path, pdf_bytes), max_pages=50)
    for page in result.pages:
        assert "FAA-H-8083 Test Handbook" not in page.text
        assert f"Page {page.page_number}" not in page.text


def test_rejects_non_pdf(tmp_path):
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"MZ\x90\x00 this is an executable")
    with pytest.raises(PdfValidationError, match="not a valid PDF"):
        extract_pdf(p, max_pages=50)


def test_rejects_too_many_pages(tmp_path, pdf_bytes):
    with pytest.raises(PdfValidationError, match="limit is 2"):
        extract_pdf(_write(tmp_path, pdf_bytes), max_pages=2)


def test_rejects_pdf_without_text(tmp_path):
    empty = make_pdf([[], []], header=None)
    with pytest.raises(PdfValidationError, match="scanned"):
        extract_pdf(_write(tmp_path, empty), max_pages=50)


def test_clean_text_dehyphenates_and_normalises():
    assert clean_text("aero-\nnautical  ﬁeld") == "aeronautical field"


def test_strip_headers_needs_enough_pages():
    pages = [PageText(1, "HEADER\nbody one"), PageText(2, "HEADER\nbody two")]
    assert strip_repeated_headers_footers(pages) == pages
