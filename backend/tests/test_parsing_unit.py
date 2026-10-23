"""Bounded parsers (KNOW-04): TXT/DOCX via stdlib, optional PDF, malformed and hostile inputs."""

import io
import sys
import threading
import time
import types
import zipfile

import pytest

from app.services import parsing
from app.services.parsing import (
    DOCX,
    PDF,
    TEXT,
    DocumentRejected,
    MalformedDocument,
    UnsupportedDocument,
    parse_document,
)

MAX = 1024 * 1024
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def paragraph(text: str, style: str | None = None, outline: int | None = None) -> str:
    ppr = ""
    if style or outline is not None:
        inner = f'<w:pStyle w:val="{style}"/>' if style else ""
        inner += f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else ""
        ppr = f"<w:pPr>{inner}</w:pPr>"
    return f"<w:p>{ppr}<w:r><w:t xml:space='preserve'>{text}</w:t></w:r></w:p>"


def make_docx(body: str, styles: str | None = None, extra: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W_NS}">'
            f"<w:body>{body}</w:body></w:document>",
        )
        if styles is not None:
            archive.writestr("word/styles.xml", f'<w:styles xmlns:w="{W_NS}">{styles}</w:styles>')
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


def parse(data: bytes, mime: str, **kwargs):
    return parse_document(data, mime, max_bytes=kwargs.pop("max_bytes", MAX), **kwargs)


def rejected(data: bytes, mime: str, **kwargs) -> DocumentRejected:
    with pytest.raises(DocumentRejected) as error:
        parse(data, mime, **kwargs)
    return error.value


# ---------------------------------------------------------------- text/plain


def test_text_utf8_with_bom_and_nfc_normalization():
    decomposed = "Hàm số".encode()  # NFD input: a + combining grave
    result = parse(b"\xef\xbb\xbf" + decomposed + b"\r\nb\xc3\xa0i  1\t\r\n\r\n\r\n\r\nend", TEXT)
    assert result.parser == "text" and result.parser_version == "1"
    assert result.page_count is None
    assert result.pages[0].text == "Hàm số\nbài 1\n\nend"


def test_text_utf16_bom_and_cp1258_fallback():
    assert parse("Toán 10".encode("utf-16"), TEXT).pages[0].text == "Toán 10"
    # Windows-1258 (base letter + combining tone mark), not valid UTF-8; NFC recombines.
    cp1258 = bytes([0xD0, 0xEA, 0xCC]) + b" ki" + bytes([0xEA, 0xD2]) + b"m tra"
    assert parse(cp1258, TEXT).pages[0].text == "Đề kiểm tra"


def test_text_latin1_last_resort_never_crashes():
    assert parse(b"caf\xe9 \x81", TEXT).pages[0].text  # 0x81 is undefined in cp1258


@pytest.mark.parametrize(
    "data,code",
    [
        (b"", "empty_document"),
        (b"   \r\n\t  ", "empty_document"),
        (b"abc\x00def", "invalid_text_encoding"),
    ],
)
def test_text_rejections(data, code):
    assert rejected(data, TEXT).code == code


def test_text_too_long(monkeypatch):
    monkeypatch.setattr(parsing, "MAX_CHARS", 10)
    error = rejected(b"x" * 11, TEXT)
    assert isinstance(error, UnsupportedDocument) and error.code == "document_too_long"


def test_input_bytes_limit():
    assert rejected(b"x" * 11, TEXT, max_bytes=10).code == "document_too_large"


def test_unknown_mime_is_unsupported():
    assert parsing.parser_for("image/png") is None
    error = rejected(b"\x89PNG", "image/png")
    assert isinstance(error, UnsupportedDocument) and error.code == "unsupported_media_type"


# ---------------------------------------------------------------- DOCX


def test_docx_paragraphs_headings_and_section_paths():
    styles = (
        '<w:style w:styleId="u1"><w:name w:val="heading 1"/></w:style>'
        '<w:style w:styleId="u2"><w:name w:val="heading 2"/></w:style>'
    )
    body = (
        paragraph("Lời nói đầu")
        + paragraph("Chương 1. Mệnh đề", style="u1")
        + paragraph("Mệnh đề là một câu khẳng định.")
        + paragraph("Bài 1. Tập hợp", style="u2")
        + paragraph("Tập hợp là khái niệm cơ bản.")
        + paragraph("")
        + paragraph("Chương 2. Vectơ", style="Heading1")
        + paragraph("Vectơ là đoạn thẳng có hướng.")
    )
    result = parse(make_docx(body, styles), DOCX)
    page = result.pages[0]
    assert result.parser == "docx" and page.page_no is None
    assert page.text.split("\n")[0] == "Lời nói đầu"
    paths = [(page.text[s.start : s.end], s.path) for s in page.sections]
    assert paths == [
        ("Lời nói đầu", None),
        ("Chương 1. Mệnh đề\nMệnh đề là một câu khẳng định.", "Chương 1. Mệnh đề"),
        (
            "Bài 1. Tập hợp\nTập hợp là khái niệm cơ bản.",
            "Chương 1. Mệnh đề > Bài 1. Tập hợp",
        ),
        ("Chương 2. Vectơ\nVectơ là đoạn thẳng có hướng.", "Chương 2. Vectơ"),
    ]


def test_docx_outline_level_tables_and_text_boxes():
    cells = "".join(f"<w:tc>{paragraph(text)}</w:tc>" for text in ("Ô một", "Ô hai"))
    table = f"<w:tbl><w:tr>{cells}</w:tr></w:tbl>"
    textbox = (
        "<w:p><w:r><w:t>Ngoài</w:t></w:r><w:r><w:pict><w:txbxContent>"
        + paragraph("Trong hộp")
        + "</w:txbxContent></w:pict></w:r></w:p>"
    )
    body = paragraph("Mục A", outline=0) + table + textbox
    page = parse(make_docx(body), DOCX).pages[0]
    assert page.text == "Mục A\nÔ một\nÔ hai\nNgoài\nTrong hộp"
    assert page.sections[0].path == "Mục A"


def test_docx_without_headings_has_single_untitled_section():
    page = parse(make_docx(paragraph("Một") + paragraph("Hai")), DOCX).pages[0]
    assert page.sections == [parsing.ParsedSection(0, len("Một\nHai"), None)]


def test_docx_truncated_zip_is_malformed():
    data = make_docx(paragraph("Nội dung"))
    error = rejected(data[: len(data) // 2], DOCX)
    assert isinstance(error, MalformedDocument) and error.code == "malformed_document"


def test_docx_missing_document_part_and_garbage():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("other.xml", "<x/>")
    assert rejected(buffer.getvalue(), DOCX).code == "malformed_document"
    assert rejected(b"PK\x03\x04garbage", DOCX).code == "malformed_document"


def test_docx_invalid_xml_is_malformed():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><unclosed>")
    assert rejected(buffer.getvalue(), DOCX).code == "malformed_document"


def test_docx_entity_expansion_is_refused():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>&b;</w:t></w:r></w:p>'
        "</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", bomb)
    assert rejected(buffer.getvalue(), DOCX).code == "malformed_document"


def test_docx_zip_bomb_ratio_is_refused():
    # 4 MiB of zeros compresses to a few KiB: ratio far above MAX_ZIP_RATIO.
    data = make_docx(paragraph("x"), extra={"word/media/pad.bin": b"\0" * (4 * 1024 * 1024)})
    error = rejected(data, DOCX, max_bytes=MAX)
    assert isinstance(error, MalformedDocument) and error.code == "archive_too_large"


def test_docx_total_uncompressed_limit(monkeypatch):
    monkeypatch.setattr(parsing, "MAX_ZIP_TOTAL_UNCOMPRESSED", 100)
    assert rejected(make_docx(paragraph("x" * 200)), DOCX).code == "archive_too_large"


def test_docx_entry_count_limit(monkeypatch):
    monkeypatch.setattr(parsing, "MAX_ZIP_ENTRIES", 2)
    data = make_docx(paragraph("x"), extra={"a.xml": "<a/>", "b.xml": "<b/>"})
    assert rejected(data, DOCX).code == "archive_too_large"


def test_docx_empty_body_is_empty_document():
    assert rejected(make_docx(paragraph("   ")), DOCX).code == "empty_document"


# ---------------------------------------------------------------- PDF (optional dependency)


def test_pdf_without_pypdf_is_unsupported(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import raises ImportError
    error = rejected(b"%PDF-1.7\n", PDF)
    assert isinstance(error, UnsupportedDocument) and error.code == "pdf_parser_unavailable"
    assert parsing.parser_for(PDF).full_version() == "1"


def fake_pypdf(pages, encrypted=False, decrypts=False, broken=False):
    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        def __init__(self, stream, strict=False):
            if broken:
                raise ValueError("bad xref")
            self.is_encrypted = encrypted
            self.pages = [Page(text) for text in pages]

        def decrypt(self, _password):
            return decrypts

    return types.SimpleNamespace(PdfReader=Reader, __version__="9.9.9")


def test_pdf_pages_with_text_layer(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf(["Trang một có chữ.", "", "Trang ba."]))
    result = parse(b"%PDF-1.7\n", PDF)
    assert result.parser_version == "1+pypdf-9.9.9"
    assert [(p.page_no, p.text) for p in result.pages] == [
        (1, "Trang một có chữ."),
        (2, ""),
        (3, "Trang ba."),
    ]
    assert result.page_count == 3


@pytest.mark.parametrize(
    "module,code",
    [
        (fake_pypdf(["", " ", "\n"]), "no_text_layer"),
        (fake_pypdf(["x"], encrypted=True), "encrypted_document"),
        (fake_pypdf([], broken=True), "malformed_document"),
    ],
)
def test_pdf_rejections(monkeypatch, module, code):
    monkeypatch.setitem(sys.modules, "pypdf", module)
    assert rejected(b"%PDF-1.7\n", PDF).code == code


def test_pdf_page_limit(monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf(["a"] * 5))
    monkeypatch.setattr(parsing, "MAX_PDF_PAGES", 4)
    assert rejected(b"%PDF-1.7\n", PDF).code == "too_many_pages"


# ---------------------------------------------------------------- resource limits


def test_wall_clock_timeout(monkeypatch):
    release = threading.Event()

    def slow(_data):
        release.wait(5)
        return [parsing.ParsedPage(None, "late")]

    monkeypatch.setitem(parsing.PARSERS, TEXT, parsing.Parser("text", "1", slow))
    started = time.monotonic()
    try:
        assert rejected(b"x", TEXT, timeout=0.05).code == "parse_timeout"
    finally:
        release.set()
    assert time.monotonic() - started < 2


@pytest.mark.parametrize(
    "exc,code",
    [(MemoryError(), "parse_resource_limit"), (RecursionError(), "malformed_document")],
)
def test_parser_crashes_map_to_safe_codes(monkeypatch, exc, code):
    def boom(_data):
        raise exc

    monkeypatch.setitem(parsing.PARSERS, TEXT, parsing.Parser("text", "1", boom))
    assert rejected(b"x", TEXT).code == code


def test_unexpected_parser_error_is_malformed_without_leaking_message(monkeypatch):
    def boom(_data):
        raise KeyError("secret document text")

    monkeypatch.setitem(parsing.PARSERS, TEXT, parsing.Parser("text", "1", boom))
    error = rejected(b"x", TEXT)
    assert error.code == "malformed_document" and "secret" not in str(error)
