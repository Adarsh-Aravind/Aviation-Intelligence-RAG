import pytest

from app.models.domain import Chunk, PageText
from app.services.chunking import chunk_pages, embedding_text, is_heading

LOREM = (
    "The pilot in command is directly responsible for the operation of the aircraft. "
    "Preflight action includes reviewing weather reports, fuel requirements and alternatives. "
)


def test_headings_detected():
    assert is_heading("4.2 Weight and Balance")
    assert is_heading("CHAPTER 3 Aircraft Performance")
    assert is_heading("EMERGENCY PROCEDURES")
    assert not is_heading("The airplane must be loaded within limits.")
    assert not is_heading("ok")


def test_chunks_preserve_page_ranges_and_size():
    pages = [PageText(i, LOREM * 6) for i in range(1, 6)]
    chunks = chunk_pages(pages, chunk_size=500, overlap=100)
    assert len(chunks) > 5
    assert all(len(c.content) <= 500 + 10 for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].page_start == 1
    assert chunks[-1].page_end == 5
    for c in chunks:
        assert 1 <= c.page_start <= c.page_end <= 5


def test_every_page_is_covered():
    pages = [PageText(i, f"Unique marker page{i}. " + LOREM * 3) for i in range(1, 8)]
    chunks = chunk_pages(pages, chunk_size=400, overlap=80)
    text = " ".join(c.content for c in chunks)
    for i in range(1, 8):
        assert f"page{i}" in text


def test_overlap_repeats_trailing_text():
    pages = [PageText(1, LOREM * 10)]
    chunks = chunk_pages(pages, chunk_size=400, overlap=120)
    assert len(chunks) >= 2
    tail_of_first = chunks[0].content[-60:]
    assert any(tail_of_first[-30:] in c.content for c in chunks[1:2])


def test_section_is_tracked_across_pages():
    pages = [
        PageText(1, "2.1 Density Altitude\n" + LOREM * 2),
        PageText(2, LOREM * 2),
        PageText(3, "2.2 Stall Recovery\n" + LOREM * 2),
    ]
    chunks = chunk_pages(pages, chunk_size=300, overlap=50)
    page2 = [c for c in chunks if c.page_start == c.page_end == 2]
    assert page2 and all(c.section == "2.1 Density Altitude" for c in page2)
    assert chunks[-1].section == "2.2 Stall Recovery"


def test_empty_pages_produce_no_chunks():
    assert chunk_pages([PageText(1, ""), PageText(2, "   ")]) == []


def test_invalid_overlap_rejected():
    with pytest.raises(ValueError):
        chunk_pages([PageText(1, LOREM)], chunk_size=100, overlap=100)


def test_embedding_text_includes_title_and_section():
    c = Chunk(0, "Body text", 1, 1, section="2.1 Density Altitude")
    assert embedding_text(c, "PHAK") == "PHAK — 2.1 Density Altitude\nBody text"
    assert embedding_text(Chunk(0, "Body", 1, 1)) == "Body"
