"""Deterministic, versioned chunking (KNOW-05).

Same ``ParsedDocument`` + same ``CHUNKER_VERSION`` => byte-identical chunks. Any change to the
algorithm or its constants must bump ``CHUNKER_VERSION`` (and regenerate the golden fixtures
under ``tests/fixtures/chunking/``) so re-ingest can tell old and new chunk sets apart.

Algorithm (version "1"):

* The version's full text is the page texts joined by ``PAGE_SEPARATOR``; every chunk records
  ``char_start``/``char_end`` into that full text and ``text == full_text[char_start:char_end]``.
* Chunks never cross a page or a section boundary, so each carries one ``page_no`` and one
  ``section_path``.
* Within a page/section, text is split into sentences (``. ! ? …`` followed by whitespace, or a
  newline; a "sentence" of fewer than ``MIN_SENTENCE_WORDS`` words, such as the exam label
  ``Câu 1.``, is joined to what follows) and sentences are packed greedily up to
  ``TARGET_TOKENS``. A sentence longer than the target is split on word boundaries (the only
  case where a sentence is split).
* Consecutive chunks in the same page/section overlap by whole trailing sentences worth at most
  ``OVERLAP_RATIO`` of the target, never so much that the next new sentence does not fit (so
  there are no overlap-only chunks).
* Token estimate = ``round(len(text.split()) * 1.3)``. Vietnamese is written with spaces between
  syllables, so whitespace "words" are syllables; ~1.3 sub-word tokens per syllable is a rough,
  provider-neutral estimate (chars/4 badly under-counts diacritic-heavy text). Real token counts
  come from the embedding provider in KNOW-06.
* Chunks whose text is byte-identical to an earlier chunk of the same version are dropped
  (repeated headers/footers, duplicated paragraphs); ``chunk_index`` stays dense.
"""

import hashlib
import math
import re
from dataclasses import asdict, dataclass

from app.services.parsing import ParsedDocument, ParsedSection

CHUNKER_VERSION = "1"
TARGET_TOKENS = 800
OVERLAP_RATIO = 0.15
TOKENS_PER_WORD = 1.3
PAGE_SEPARATOR = "\n\n"
MIN_SENTENCE_WORDS = 3

_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s|$)|\n")
_WORD = re.compile(r"\S+")


def estimate_tokens(text: str) -> int:
    return round(len(text.split()) * TOKENS_PER_WORD)


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    page_no: int | None
    section_path: str | None
    char_start: int
    char_end: int
    text: str
    text_sha256: bytes
    token_estimate: int

    def as_dict(self) -> dict:
        data = asdict(self)
        data["text_sha256"] = self.text_sha256.hex()
        return data


@dataclass(frozen=True)
class ChunkedDocument:
    text: str
    text_sha256: bytes
    chunks: list[Chunk]
    chunker_version: str = CHUNKER_VERSION


@dataclass(frozen=True)
class _Unit:
    start: int
    end: int
    tokens: int


def _trimmed(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _sentence_spans(text: str, start: int, end: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = start
    for match in _SENTENCE_END.finditer(text, start, end):
        newline = match.group() == "\n"
        stop = match.start() if newline else match.end()
        if not newline and len(text[cursor:stop].split()) < MIN_SENTENCE_WORDS:
            continue  # "Câu 1.", "Bài 2.", "I." are labels, not sentences
        span = _trimmed(text, cursor, stop)
        if span:
            spans.append(span)
        cursor = match.end()
    span = _trimmed(text, cursor, end)
    if span:
        spans.append(span)
    return spans


def _units(text: str, start: int, end: int, target: int) -> list[_Unit]:
    max_words = max(1, math.floor(target / TOKENS_PER_WORD))
    units: list[_Unit] = []
    for s_start, s_end in _sentence_spans(text, start, end):
        tokens = estimate_tokens(text[s_start:s_end])
        if tokens <= target:
            units.append(_Unit(s_start, s_end, tokens))
            continue
        words = list(_WORD.finditer(text, s_start, s_end))
        for i in range(0, len(words), max_words):
            piece = words[i : i + max_words]
            p_start, p_end = piece[0].start(), piece[-1].end()
            units.append(_Unit(p_start, p_end, estimate_tokens(text[p_start:p_end])))
    return units


def _pack(units: list[_Unit], target: int, overlap: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i, n = 0, len(units)
    while i < n:
        j, tokens = i, 0
        while j < n and (j == i or tokens + units[j].tokens <= target):
            tokens += units[j].tokens
            j += 1
        spans.append((units[i].start, units[j - 1].end))
        if j >= n:
            break
        k, carried = j, 0
        while (
            k - 1 > i
            and carried + units[k - 1].tokens <= overlap
            and carried + units[k - 1].tokens + units[j].tokens <= target
        ):
            k -= 1
            carried += units[k].tokens
        i = k
    return spans


def _segments(sections: list[ParsedSection], length: int) -> list[tuple[int, int, str | None]]:
    """Page-relative ``(start, end, path)``; gaps not covered by a section get ``None``."""
    segments: list[tuple[int, int, str | None]] = []
    cursor = 0
    for section in sorted(sections, key=lambda s: (s.start, s.end)):
        start, end = max(section.start, cursor), min(section.end, length)
        if start > cursor:
            segments.append((cursor, start, None))
        if end > start:
            segments.append((start, end, section.path))
            cursor = end
    if cursor < length:
        segments.append((cursor, length, None))
    return segments


def chunk_document(
    parsed: ParsedDocument,
    *,
    target_tokens: int = TARGET_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
) -> ChunkedDocument:
    if target_tokens < 1 or not 0 <= overlap_ratio < 1:
        raise ValueError("invalid chunking parameters")
    overlap = int(target_tokens * overlap_ratio)
    full_text = PAGE_SEPARATOR.join(page.text for page in parsed.pages)
    chunks: list[Chunk] = []
    seen: set[bytes] = set()
    offset = 0
    for page in parsed.pages:
        for seg_start, seg_end, path in _segments(page.sections, len(page.text)):
            units = _units(full_text, offset + seg_start, offset + seg_end, target_tokens)
            for start, end in _pack(units, target_tokens, overlap):
                text = full_text[start:end]
                digest = hashlib.sha256(text.encode("utf-8")).digest()
                if digest in seen:
                    continue
                seen.add(digest)
                chunks.append(
                    Chunk(
                        chunk_index=len(chunks),
                        page_no=page.page_no,
                        section_path=path,
                        char_start=start,
                        char_end=end,
                        text=text,
                        text_sha256=digest,
                        token_estimate=estimate_tokens(text),
                    )
                )
        offset += len(page.text) + len(PAGE_SEPARATOR)
    return ChunkedDocument(
        text=full_text,
        text_sha256=hashlib.sha256(full_text.encode("utf-8")).digest(),
        chunks=chunks,
        chunker_version=CHUNKER_VERSION,
    )
