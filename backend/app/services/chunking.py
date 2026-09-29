"""Page-aware chunking.

Pages are split into paragraphs; paragraphs are packed into ~``chunk_size`` character chunks with a
sentence-aligned overlap. Every chunk keeps the page range it came from and the most recent section
heading, so answers can cite "Document X, p. 12–13, §4.2 Weight and Balance".
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from app.models.domain import Chunk, PageText

_NUMBERED_HEADING = re.compile(r"^(\d{1,2}(\.\d{1,3}){0,4}\.?)\s+[A-Z][\w ,/&()'\-]{2,80}$")
_KEYWORD_HEADING = re.compile(
    r"^(chapter|section|appendix|part)\s+[\w.\-]+(\s*[:.\-–]?\s+.*)?$", re.IGNORECASE
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")
_TERMINAL = (".", ":", ";", "?", "!")
MIN_CHUNK_CHARS = 30


@dataclass(slots=True)
class _Piece:
    text: str
    page: int
    section: str | None
    is_overlap: bool = False
    is_heading: bool = False


def is_heading(line: str) -> bool:
    line = line.strip()
    if not (3 <= len(line) <= 90) or line.endswith((".", ",", ";")):
        return False
    if _NUMBERED_HEADING.match(line) or _KEYWORD_HEADING.match(line):
        return True
    letters = [c for c in line if c.isalpha()]
    # ALL-CAPS lines with at least two words, e.g. "WEIGHT AND BALANCE"
    return len(letters) >= 6 and all(c.isupper() for c in letters) and len(line.split()) >= 2


def _paragraphs(text: str) -> Iterator[str]:
    """Group lines into paragraphs. Headings are always their own paragraph."""
    current: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if current:
                yield " ".join(current)
                current = []
            continue
        if is_heading(line):
            if current:
                yield " ".join(current)
                current = []
            yield line
            continue
        current.append(line)
        # A line ending a sentence that is noticeably short usually ends a paragraph.
        if line.endswith(_TERMINAL) and len(line) < 60:
            yield " ".join(current)
            current = []
    if current:
        yield " ".join(current)


def _split_long(text: str, max_len: int) -> Iterator[str]:
    """Split an over-long paragraph by sentences, then by words as a last resort."""
    if len(text) <= max_len:
        yield text
        return
    buf = ""
    for sentence in _SENTENCE_END.split(text):
        if len(sentence) > max_len:
            if buf:
                yield buf
                buf = ""
            words, part = sentence.split(" "), ""
            for w in words:
                if part and len(part) + 1 + len(w) > max_len:
                    yield part
                    part = w
                else:
                    part = f"{part} {w}" if part else w
            if part:
                buf = part
            continue
        if buf and len(buf) + 1 + len(sentence) > max_len:
            yield buf
            buf = sentence
        else:
            buf = f"{buf} {sentence}" if buf else sentence
    if buf:
        yield buf


def _pieces(pages: Iterable[PageText], max_piece: int) -> Iterator[_Piece]:
    section: str | None = None
    for page in pages:
        for para in _paragraphs(page.text):
            if is_heading(para):
                section = para[:120]
                yield _Piece(para, page.page_number, section, is_heading=True)
                continue
            for part in _split_long(para, max_piece):
                yield _Piece(part, page.page_number, section)


def _overlap_tail(buf: list[_Piece], overlap: int) -> list[_Piece]:
    """Return the trailing text of ``buf`` (~``overlap`` chars, sentence/word aligned)."""
    if overlap <= 0:
        return []
    tail: list[_Piece] = []
    total = 0
    for piece in reversed(buf):
        if total >= overlap:
            break
        remaining = overlap - total
        text = piece.text
        if len(text) > remaining:
            cut = text[-remaining:]
            # snap to a sentence start if one exists, otherwise to a word boundary
            m = _SENTENCE_END.search(cut)
            if m:
                cut = cut[m.end() :]
            elif " " in cut:
                cut = cut[cut.index(" ") + 1 :]
            if cut:
                tail.insert(0, _Piece(cut, piece.page, piece.section, is_overlap=True))
            break  # a partial piece is always the start of the overlap — never add fragments before it
        tail.insert(0, _Piece(text, piece.page, piece.section, is_overlap=True))
        total += len(text) + 1
    return tail


def chunk_pages(pages: Iterable[PageText], chunk_size: int = 1100, overlap: int = 200) -> list[Chunk]:
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")
    chunks: list[Chunk] = []
    buf: list[_Piece] = []
    buf_len = 0

    def flush() -> None:
        new_content = [p for p in buf if not p.is_overlap]
        if not new_content:
            return
        text = "\n".join(p.text for p in buf).strip()
        if len(text) < MIN_CHUNK_CHARS:
            return
        section = next((p.section for p in new_content if p.section), None)
        chunks.append(
            Chunk(
                chunk_index=len(chunks),
                content=text,
                page_start=min(p.page for p in buf),
                page_end=max(p.page for p in buf),
                section=section,
            )
        )

    for piece in _pieces(pages, max_piece=chunk_size - overlap):
        starts_section = piece.is_heading
        if starts_section and all(p.is_overlap for p in buf):
            # overlap from the previous section adds noise in front of a new heading
            buf, buf_len = [], 0
        new_len = sum(len(p.text) + 1 for p in buf if not p.is_overlap)
        too_big = buf_len + len(piece.text) + 1 > chunk_size
        # A heading starts a fresh chunk unless the current chunk is still tiny.
        heading_break = starts_section and new_len > chunk_size * 0.25
        if buf and (too_big or heading_break):
            # never leave a heading dangling at the end of a chunk — move it to the next one
            carry = [buf.pop()] if buf[-1].is_heading else []
            flush()
            buf = carry if (starts_section or carry) else _overlap_tail(buf, overlap)
            buf_len = sum(len(p.text) + 1 for p in buf)
        buf.append(piece)
        buf_len += len(piece.text) + 1
    if buf:
        flush()
    return chunks


def embedding_text(chunk: Chunk, document_title: str | None = None) -> str:
    """Text actually embedded — prefixing title/section improves retrieval for short chunks."""
    header = " — ".join(x for x in (document_title, chunk.section) if x)
    return f"{header}\n{chunk.content}" if header else chunk.content
