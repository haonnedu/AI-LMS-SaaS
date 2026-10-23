"""Bounded document parsing (KNOW-04): a MIME-keyed parser registry with resource limits.

Parsers never execute document content. Each run is bounded by input bytes (the upload
limit), output characters, archive expansion (DOCX) and page count (PDF), and a wall-clock
timeout enforced by running the parser in a daemon thread. A thread cannot be killed: after a
timeout the worker abandons it and fails the version, and the Celery hard time limit remains
the backstop. This is *not* an OS sandbox (no seccomp/rlimit/subprocess isolation yet).

Errors are ``DocumentRejected`` with a stable, client-visible ``code``; raw parser messages and
document text are never logged or returned.
"""

import codecs
import io
import re
import threading
import unicodedata
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF = "application/pdf"
TEXT = "text/plain"

MAX_CHARS = 2_000_000
DEFAULT_TIMEOUT_SECONDS = 30.0
# DOCX (zip) expansion guards.
MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_TOTAL_UNCOMPRESSED = 128 * 1024 * 1024
MAX_ZIP_PART_BYTES = 32 * 1024 * 1024
MAX_ZIP_RATIO = 200
ZIP_RATIO_MIN_SIZE = 1024 * 1024
# PDF guards.
MAX_PDF_PAGES = 1_000
MIN_TEXT_LAYER_CHARS = 16


class DocumentRejected(Exception):
    """Permanent, deterministic parse failure with a safe ``code``."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class UnsupportedDocument(DocumentRejected):
    """Valid file we cannot index (no parser available, scanned PDF, encrypted)."""


class MalformedDocument(DocumentRejected):
    """Corrupt, truncated or hostile input."""


@dataclass(frozen=True)
class ParsedSection:
    """``[start, end)`` offsets into the page text; ``path`` like ``"Chương 1 > Bài 2"``."""

    start: int
    end: int
    path: str | None


@dataclass(frozen=True)
class ParsedPage:
    page_no: int | None
    text: str
    sections: list[ParsedSection] = field(default_factory=list)


@dataclass(frozen=True)
class ParsedDocument:
    pages: list[ParsedPage]
    parser: str
    parser_version: str

    @property
    def page_count(self) -> int | None:
        numbered = [page.page_no for page in self.pages if page.page_no is not None]
        return len(numbered) if numbered else None


@dataclass(frozen=True)
class Parser:
    name: str
    version: str
    run: Callable[[bytes], list[ParsedPage]]
    version_suffix: Callable[[], str] | None = None

    def full_version(self) -> str:
        suffix = self.version_suffix() if self.version_suffix else ""
        return self.version + suffix


# ---------------------------------------------------------------- normalization

_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b-\u200d\u2060\ufeff]")
_TRAILING_SPACE = re.compile(r" +\n")
_SPACES = re.compile(r" {2,}")
_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(raw: str) -> str:
    """NFC (Vietnamese diacritics may arrive decomposed), LF newlines, no control chars."""
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ").replace("\u00a0", " ")
    text = _CONTROL.sub("", text)
    text = _SPACES.sub(" ", text)
    text = _TRAILING_SPACE.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _check_length(chars: int) -> None:
    if chars > MAX_CHARS:
        raise UnsupportedDocument("document_too_long")


# ---------------------------------------------------------------- text/plain


def decode_text(data: bytes) -> str:
    """BOM-aware UTF-8/UTF-16, then strict UTF-8, then cp1258 (Vietnamese ANSI), then latin-1."""
    if data.startswith(codecs.BOM_UTF8):
        candidates = ("utf-8-sig",)
    elif data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        candidates = ("utf-16",)
    else:
        candidates = ("utf-8", "cp1258", "latin-1")
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise MalformedDocument("invalid_text_encoding")


def parse_text(data: bytes) -> list[ParsedPage]:
    if b"\x00" in data and not data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        raise MalformedDocument("invalid_text_encoding")
    raw = decode_text(data)
    _check_length(len(raw))
    return [ParsedPage(page_no=None, text=normalize_text(raw))]


# ---------------------------------------------------------------- DOCX (stdlib only)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
W_BODY, W_P, W_T, W_TAB, W_BR, W_CR = (W + t for t in ("body", "p", "t", "tab", "br", "cr"))
W_PPR, W_PSTYLE, W_OUTLINE, W_VAL = W + "pPr", W + "pStyle", W + "outlineLvl", W + "val"
_HEADING_NAME = re.compile(r"^\s*heading\s*([1-9])\s*$", re.IGNORECASE)
_HEADING_ID = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)
MAX_HEADING_CHARS = 200


def _read_part(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_ZIP_PART_BYTES:
        raise MalformedDocument("archive_too_large")
    with archive.open(info) as handle:  # bounded by the declared size; CRC checked at EOF
        data = handle.read(MAX_ZIP_PART_BYTES + 1)
    if len(data) > MAX_ZIP_PART_BYTES:
        raise MalformedDocument("archive_too_large")
    return data


def _xml(data: bytes) -> ET.Element:
    # DOCX parts never need a DTD; refusing one blocks entity-expansion attacks outright.
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise MalformedDocument("malformed_document")
    return ET.fromstring(data)


def _check_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise MalformedDocument("archive_too_large")
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise UnsupportedDocument("encrypted_document")
        total += info.file_size
        if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
            raise MalformedDocument("archive_too_large")
        if info.file_size > ZIP_RATIO_MIN_SIZE and info.file_size > MAX_ZIP_RATIO * max(
            info.compress_size, 1
        ):
            raise MalformedDocument("archive_too_large")


def _style_levels(styles_xml: bytes | None) -> dict[str, int]:
    """styleId -> heading level, from built-in names ("heading 1") or ``outlineLvl``.

    Localized Word (e.g. Vietnamese) uses opaque style IDs such as ``u1``, so the ID alone is
    not enough; styles.xml keeps the built-in English name.
    """
    if not styles_xml:
        return {}
    levels: dict[str, int] = {}
    for style in _xml(styles_xml).iter(W + "style"):
        style_id = style.get(W + "styleId")
        if not style_id:
            continue
        name = style.find(W + "name")
        match = _HEADING_NAME.match(name.get(W_VAL, "")) if name is not None else None
        if match:
            levels[style_id] = int(match.group(1))
            continue
        outline = style.find(f"{W_PPR}/{W_OUTLINE}")
        if outline is not None:
            level = _int(outline.get(W_VAL))
            if level is not None and 0 <= level <= 8:
                levels[style_id] = level + 1
    return levels


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _heading_level(paragraph: ET.Element, styles: dict[str, int]) -> int | None:
    ppr = paragraph.find(W_PPR)
    if ppr is None:
        return None
    outline = ppr.find(W_OUTLINE)
    if outline is not None:
        level = _int(outline.get(W_VAL))
        if level is not None and 0 <= level <= 8:
            return level + 1
    style = ppr.find(W_PSTYLE)
    if style is None:
        return None
    style_id = style.get(W_VAL, "")
    if style_id in styles:
        return styles[style_id]
    match = _HEADING_ID.match(style_id)
    return int(match.group(1)) if match else None


def _paragraph_text(paragraph: ET.Element, nested: list[ET.Element]) -> str:
    """Text of runs that belong to this paragraph; text-box paragraphs are emitted after it."""
    parts: list[str] = []

    def visit(element: ET.Element) -> None:
        for child in element:
            if child.tag == W_P:
                nested.append(child)
                continue
            if child.tag == W_T:
                parts.append(child.text or "")
            elif child.tag == W_TAB:
                parts.append(" ")
            elif child.tag in (W_BR, W_CR):
                parts.append("\n")
            visit(child)

    visit(paragraph)
    return "".join(parts)


def _iter_paragraphs(body: ET.Element):
    stack = list(reversed(list(body)))
    while stack:
        element = stack.pop()
        if element.tag == W_P:
            nested: list[ET.Element] = []
            yield element, _paragraph_text(element, nested)
            stack.extend(reversed(nested))
        else:
            stack.extend(reversed(list(element)))


def parse_docx(data: bytes) -> list[ParsedPage]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError):
        raise MalformedDocument("malformed_document") from None
    with archive:
        _check_archive(archive)
        document_xml = _read_part(archive, "word/document.xml")
        if document_xml is None:
            raise MalformedDocument("malformed_document")
        styles = _style_levels(_read_part(archive, "word/styles.xml"))
        root = _xml(document_xml)
    body = root.find(W_BODY)
    if body is None:
        raise MalformedDocument("malformed_document")

    lines: list[str] = []
    sections: list[ParsedSection] = []
    headings: list[tuple[int, str]] = []
    offset = 0
    section_start, section_path = 0, None
    total = 0
    for paragraph, raw in _iter_paragraphs(body):
        line = normalize_text(raw)
        if not line:
            continue
        total += len(line) + 1
        _check_length(total)
        level = _heading_level(paragraph, styles)
        if level is not None:
            if offset > section_start:
                sections.append(ParsedSection(section_start, offset - 1, section_path))
            title = " ".join(line.split())[:MAX_HEADING_CHARS]
            headings = [(lvl, name) for lvl, name in headings if lvl < level] + [(level, title)]
            section_start = offset
            section_path = " > ".join(name for _, name in headings)
        lines.append(line)
        offset += len(line) + 1
    text = "\n".join(lines)
    if len(text) > section_start:
        sections.append(ParsedSection(section_start, len(text), section_path))
    return [ParsedPage(page_no=None, text=text, sections=sections)]


# ---------------------------------------------------------------- PDF (optional pypdf)


def _pypdf():
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError:
        raise UnsupportedDocument("pdf_parser_unavailable") from None
    return pypdf


def _pypdf_version() -> str:
    try:
        return "+pypdf-" + str(_pypdf().__version__)
    except UnsupportedDocument:
        return ""


def parse_pdf(data: bytes) -> list[ParsedPage]:
    pypdf = _pypdf()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise UnsupportedDocument("encrypted_document")
        page_objects = list(reader.pages)
    except DocumentRejected:
        raise
    except Exception:
        raise MalformedDocument("malformed_document") from None
    if len(page_objects) > MAX_PDF_PAGES:
        raise UnsupportedDocument("too_many_pages")
    pages: list[ParsedPage] = []
    total = 0
    for number, page in enumerate(page_objects, start=1):
        try:
            text = normalize_text(page.extract_text() or "")
        except Exception:
            raise MalformedDocument("malformed_document") from None
        total += len(text)
        _check_length(total)
        pages.append(ParsedPage(page_no=number, text=text))
    visible = sum(len("".join(page.text.split())) for page in pages)
    if visible < MIN_TEXT_LAYER_CHARS:
        raise UnsupportedDocument("no_text_layer")  # scanned/image-only: OCR is not enabled
    return pages


# ---------------------------------------------------------------- registry and limits

PARSERS: dict[str, Parser] = {
    TEXT: Parser("text", "1", parse_text),
    DOCX: Parser("docx", "1", parse_docx),
    PDF: Parser("pdf", "1", parse_pdf, version_suffix=_pypdf_version),
}


def parser_for(mime: str | None) -> Parser | None:
    return PARSERS.get((mime or "").lower())


def _run_with_timeout(fn: Callable[[bytes], list[ParsedPage]], data: bytes, timeout: float):
    outcome: dict[str, object] = {}

    def target() -> None:
        try:
            outcome["value"] = fn(data)
        except BaseException as exc:  # handed back to the calling thread
            outcome["error"] = exc

    worker = threading.Thread(target=target, name="eduvia-parser", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise DocumentRejected("parse_timeout")
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]
    return outcome["value"]


def parse_document(
    data: bytes, mime: str, *, max_bytes: int, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> ParsedDocument:
    parser = parser_for(mime)
    if parser is None:
        raise UnsupportedDocument("unsupported_media_type")
    if not data:
        raise UnsupportedDocument("empty_document")
    if len(data) > max_bytes:
        raise DocumentRejected("document_too_large")
    try:
        pages = _run_with_timeout(parser.run, data, timeout)
    except DocumentRejected:
        raise
    except MemoryError:
        raise DocumentRejected("parse_resource_limit") from None
    except RecursionError:
        raise MalformedDocument("malformed_document") from None
    except Exception:
        raise MalformedDocument("malformed_document") from None
    if not any(page.text for page in pages):
        raise UnsupportedDocument("empty_document")
    return ParsedDocument(pages=pages, parser=parser.name, parser_version=parser.full_version())
