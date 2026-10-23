"""Deterministic versioned chunking (KNOW-05) with golden fixtures.

Golden files live in ``tests/fixtures/chunking/*.json``: ``input`` (pages + parameters) and
``expected`` (chunks). After an intentional algorithm change, bump ``CHUNKER_VERSION`` and run
``EDUVIA_UPDATE_GOLDEN=1 pytest tests/test_chunking_unit.py`` to regenerate, then review the diff.
"""

import json
import os
from pathlib import Path

import pytest

from app.services import chunking
from app.services.chunking import CHUNKER_VERSION, chunk_document, estimate_tokens
from app.services.parsing import ParsedDocument, ParsedPage, ParsedSection

FIXTURES = Path(__file__).parent / "fixtures" / "chunking"
GOLDEN = sorted(FIXTURES.glob("*.json"))


def document_from(spec: dict) -> ParsedDocument:
    pages = [
        ParsedPage(
            page_no=page.get("pageNo"),
            text=page["text"],
            sections=[
                ParsedSection(s["start"], s["end"], s.get("path")) for s in page.get("sections", [])
            ],
        )
        for page in spec["pages"]
    ]
    return ParsedDocument(pages=pages, parser="fixture", parser_version="1")


def run_fixture(spec: dict) -> dict:
    result = chunk_document(
        document_from(spec),
        target_tokens=spec.get("targetTokens", chunking.TARGET_TOKENS),
        overlap_ratio=spec.get("overlapRatio", chunking.OVERLAP_RATIO),
    )
    return {
        "chunkerVersion": result.chunker_version,
        "textSha256": result.text_sha256.hex(),
        "chunks": [chunk.as_dict() for chunk in result.chunks],
    }


def test_golden_fixtures_exist():
    assert len(GOLDEN) >= 3


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
def test_golden_fixture(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    actual = run_fixture(fixture["input"])
    if os.getenv("EDUVIA_UPDATE_GOLDEN") == "1":
        fixture["expected"] = actual
        path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", "utf-8")
    assert actual == fixture["expected"]
    assert actual["chunkerVersion"] == CHUNKER_VERSION


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.stem)
def test_offsets_pages_and_sections_are_preserved(path):
    spec = json.loads(path.read_text(encoding="utf-8"))["input"]
    parsed = document_from(spec)
    result = chunk_document(parsed, target_tokens=spec.get("targetTokens", 800))
    page_ranges = {}
    offset = 0
    for page in parsed.pages:
        page_ranges.setdefault(page.page_no, []).append((offset, offset + len(page.text), page))
        offset += len(page.text) + len(chunking.PAGE_SEPARATOR)
    for index, chunk in enumerate(result.chunks):
        assert chunk.chunk_index == index
        assert result.text[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.text == chunk.text.strip() and chunk.text
        # chunk lies inside one page and inside one section of that page
        start, end, page = next(
            (s, e, p)
            for s, e, p in page_ranges[chunk.page_no]
            if s <= chunk.char_start and chunk.char_end <= e
        )
        if page.sections:
            local = (chunk.char_start - start, chunk.char_end - start)
            owners = [
                sec
                for sec in page.sections
                if sec.start <= local[0] and local[1] <= sec.end and sec.path == chunk.section_path
            ]
            assert owners or chunk.section_path is None
    assert len({c.text_sha256 for c in result.chunks}) == len(result.chunks)


def test_reproducible_across_runs():
    spec = json.loads(GOLDEN[0].read_text(encoding="utf-8"))["input"]
    assert run_fixture(spec) == run_fixture(spec)


def test_estimate_tokens_uses_whitespace_words():
    assert estimate_tokens("") == 0
    assert estimate_tokens("Hàm số bậc hai") == 5  # 4 syllables * 1.3 = 5.2
    assert estimate_tokens("a  b\n\nc") == 4


def sentences(n: int, words: int = 9) -> str:
    return " ".join(
        " ".join(f"từ{i}_{j}" for j in range(words - 1)) + f" cuối{i}." for i in range(n)
    )


def test_sentences_are_not_split_and_overlap_is_bounded():
    text = sentences(40)  # each sentence 9 words ~ 12 tokens
    doc = ParsedDocument([ParsedPage(1, text)], "t", "1")
    result = chunk_document(doc, target_tokens=60, overlap_ratio=0.25)
    assert len(result.chunks) > 3
    for chunk in result.chunks:
        assert chunk.text.endswith(".")
        assert chunk.text.startswith("từ")
        assert chunk.token_estimate <= 60
    for previous, current in zip(result.chunks, result.chunks[1:], strict=False):
        assert current.char_start > previous.char_start  # progress
        overlap = max(0, previous.char_end - current.char_start)
        if overlap:
            assert estimate_tokens(result.text[current.char_start : previous.char_end]) <= 15


def test_overlong_sentence_is_split_on_words():
    text = " ".join(f"w{i}" for i in range(100)) + "."
    result = chunk_document(ParsedDocument([ParsedPage(None, text)], "t", "1"), target_tokens=13)
    assert len(result.chunks) == 10
    assert all(chunk.token_estimate <= 13 for chunk in result.chunks)
    assert " ".join(chunk.text for chunk in result.chunks) == text


def test_duplicate_chunks_are_dropped_and_indexes_stay_dense():
    page = "Trường THPT Chu Văn An. Đề kiểm tra giữa kỳ."
    doc = ParsedDocument(
        [ParsedPage(1, page), ParsedPage(2, "Nội dung khác."), ParsedPage(3, page)], "t", "1"
    )
    result = chunk_document(doc)
    assert [c.page_no for c in result.chunks] == [1, 2]
    assert [c.chunk_index for c in result.chunks] == [0, 1]


def test_empty_pages_produce_no_chunks():
    doc = ParsedDocument([ParsedPage(1, ""), ParsedPage(2, "Có chữ.")], "t", "1")
    result = chunk_document(doc)
    assert [(c.page_no, c.char_start) for c in result.chunks] == [(2, 2)]


def test_invalid_parameters():
    doc = ParsedDocument([ParsedPage(1, "x")], "t", "1")
    with pytest.raises(ValueError):
        chunk_document(doc, target_tokens=0)
    with pytest.raises(ValueError):
        chunk_document(doc, overlap_ratio=1)
