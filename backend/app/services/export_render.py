"""Stdlib-only rendering of lesson content and exams to DOCX and PDF (EXPORT-01).

* DOCX: a minimal OOXML package written with ``zipfile`` (``[Content_Types].xml``,
  ``_rels/.rels``, ``word/document.xml``) using direct run formatting, so no styles/numbering
  parts are needed. Output is byte-for-byte deterministic (fixed zip timestamps) which makes the
  golden ``document.xml`` fixtures meaningful. Vietnamese text is plain UTF-8 XML.
* PDF: a minimal PDF 1.4 writer using the standard Helvetica font with ``WinAnsiEncoding``.
  WinAnsi cannot represent most Vietnamese letters (ă, đ, ơ, ư, ạ, ...), and embedding a
  Unicode font needs a font file plus a TrueType subsetter (e.g. ``fpdf2``/``reportlab``), which
  the pilot does not add. Therefore ``render_pdf`` raises ``PdfUnicodeUnsupported`` whenever a
  character is not WinAnsi-representable; the export job fails with
  ``pdf_unicode_unsupported`` instead of silently dropping or transliterating characters.

Audience separation is structural: ``student_exam_document`` accepts ``StudentExamItem``, a type
with no key/explanation fields, and never reads such attributes even if given a subclass.
"""

import io
import re
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from xml.sax.saxutils import escape

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME = "application/pdf"
ZIP_DATE = (2000, 1, 1, 0, 0, 0)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")
AUDIENCE_LABELS = {"teacher": "Bản dành cho giáo viên", "student": "Bản dành cho học sinh"}


class PdfUnicodeUnsupported(Exception):
    """The text needs glyphs outside WinAnsi; a font-embedding dependency is required."""


@dataclass(frozen=True)
class Block:
    kind: str  # title | subtitle | heading | paragraph | list_item | question | choice | answer
    text: str


@dataclass(frozen=True)
class RenderDocument:
    title: str
    blocks: tuple[Block, ...]


@dataclass(frozen=True)
class StudentExamItem:
    """Student-safe projection: deliberately has no key or explanation fields."""

    position: int
    stem: str
    choices: tuple[tuple[str, str], ...]
    points: Decimal


@dataclass(frozen=True)
class TeacherExamItem(StudentExamItem):
    correct_key: str | None = None
    explanation: str | None = None


def _points(value: Decimal) -> str:
    text = format(Decimal(value).quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _question_blocks(item: StudentExamItem) -> list[Block]:
    blocks = [Block("question", f"Câu {item.position} ({_points(item.points)} điểm). {item.stem}")]
    blocks.extend(Block("choice", f"{key}. {text}") for key, text in item.choices)
    return blocks


def student_exam_document(title: str, items: Sequence[StudentExamItem]) -> RenderDocument:
    blocks = [Block("title", title), Block("subtitle", AUDIENCE_LABELS["student"])]
    for item in sorted(items, key=lambda i: i.position):
        # Only StudentExamItem fields are read here, whatever the runtime type.
        blocks.extend(
            _question_blocks(
                StudentExamItem(item.position, item.stem, tuple(item.choices), item.points)
            )
        )
    return RenderDocument(title, tuple(blocks))


def teacher_exam_document(title: str, items: Sequence[TeacherExamItem]) -> RenderDocument:
    blocks = [Block("title", title), Block("subtitle", AUDIENCE_LABELS["teacher"])]
    for item in sorted(items, key=lambda i: i.position):
        blocks.extend(_question_blocks(item))
        blocks.append(Block("answer", f"Đáp án: {item.correct_key or '(chưa có)'}"))
        if item.explanation:
            blocks.append(Block("answer", f"Giải thích: {item.explanation}"))
    return RenderDocument(title, tuple(blocks))


def content_document(title: str, body: Mapping[str, Any], audience: str) -> RenderDocument:
    blocks = [Block("title", title), Block("subtitle", AUDIENCE_LABELS[audience])]
    for section in body.get("sections", []):
        blocks.append(Block("heading", section["heading"]))
        for block in section.get("blocks", []):
            labels = "".join(f" {c['label']}" for c in block.get("citations", []) if c.get("label"))
            text = (block.get("text") or "") + labels
            kind = "list_item" if block.get("type") == "list" else "paragraph"
            blocks.append(Block(kind, text))
    return RenderDocument(title, tuple(blocks))


# ---- DOCX -----------------------------------------------------------------------------------

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/'
    'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)
_STYLE = {
    "title": ('<w:jc w:val="center"/>', '<w:b/><w:sz w:val="32"/>'),
    "subtitle": ('<w:jc w:val="center"/>', '<w:i/><w:sz w:val="22"/>'),
    "heading": ("", '<w:b/><w:sz w:val="28"/>'),
    "paragraph": ("", ""),
    "list_item": ('<w:ind w:left="720"/>', ""),
    "question": ('<w:spacing w:before="200"/>', "<w:b/>"),
    "choice": ('<w:ind w:left="720"/>', ""),
    "answer": ('<w:ind w:left="720"/>', "<w:i/>"),
}


def _clean(text: str) -> str:
    return _INVALID_XML.sub("", text)


def _paragraph(block: Block) -> str:
    p_props, r_props = _STYLE.get(block.kind, ("", ""))
    text = _clean(block.text)
    if block.kind == "list_item":
        text = "• " + text
    runs = []
    for index, line in enumerate(text.split("\n")):
        if index:
            runs.append("<w:br/>")
        runs.append(f'<w:t xml:space="preserve">{escape(line)}</w:t>')
    r_pr = f"<w:rPr>{r_props}</w:rPr>" if r_props else ""
    p_pr = f"<w:pPr>{p_props}</w:pPr>" if p_props else ""
    return f"<w:p>{p_pr}<w:r>{r_pr}{''.join(runs)}</w:r></w:p>"


def document_xml(document: RenderDocument) -> str:
    body = "\n".join(_paragraph(block) for block in document.blocks)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:document xmlns:w="{W_NS}"><w:body>\n{body}\n'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>\n"
    )


def render_docx(document: RenderDocument) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in (
            ("[Content_Types].xml", CONTENT_TYPES),
            ("_rels/.rels", RELS),
            ("word/document.xml", document_xml(document)),
        ):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data.encode("utf-8"))
    return buffer.getvalue()


# ---- PDF (WinAnsi only) ---------------------------------------------------------------------

PAGE_WIDTH, PAGE_HEIGHT = 595, 842
MARGIN = 56
FONT_SIZE = 11
LEADING = 15
WRAP = 90
LINES_PER_PAGE = (PAGE_HEIGHT - 2 * MARGIN) // LEADING


def _lines(document: RenderDocument) -> list[str]:
    lines: list[str] = []
    for block in document.blocks:
        prefix = {"list_item": "  - ", "choice": "    ", "answer": "    "}.get(block.kind, "")
        if block.kind in {"heading", "question", "title"} and lines:
            lines.append("")
        for raw in block.text.split("\n"):
            words, current = raw.split(" "), prefix
            for word in words:
                candidate = (current + " " + word) if current.strip() else current + word
                if len(candidate) > WRAP and current.strip():
                    lines.append(current)
                    current = prefix + word
                else:
                    current = candidate
            lines.append(current)
    return lines


def _pdf_string(line: str) -> bytes:
    data = line.encode("cp1252")
    return b"(" + data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def ensure_winansi(document: RenderDocument) -> None:
    for block in (Block("title", document.title), *document.blocks):
        try:
            block.text.encode("cp1252")
        except UnicodeEncodeError:
            raise PdfUnicodeUnsupported() from None


def render_pdf(document: RenderDocument) -> bytes:
    ensure_winansi(document)
    lines = _lines(document)
    pages = [lines[i : i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[]]
    objects: list[bytes] = []
    page_ids = []
    first_page_object = 4
    for index, page in enumerate(pages):
        content_id = first_page_object + 2 * index + 1
        page_ids.append(first_page_object + 2 * index)
        stream = [b"BT", f"/F1 {FONT_SIZE} Tf {LEADING} TL".encode()]
        stream.append(f"{MARGIN} {PAGE_HEIGHT - MARGIN} Td".encode())
        for line in page:
            stream.append(_pdf_string(line) + b" Tj T*")
        stream.append(b"ET")
        data = b"\n".join(stream)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode()
        )
        objects.append(b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    head = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(head + objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    total = len(offsets) + 1
    out.write(f"xref\n0 {total}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def render(document: RenderDocument, fmt: str) -> tuple[bytes, str, str]:
    """Returns ``(data, mime, extension)``; raises ``PdfUnicodeUnsupported`` for PDF."""
    if fmt == "pdf":
        return render_pdf(document), PDF_MIME, "pdf"
    return render_docx(document), DOCX_MIME, "docx"
