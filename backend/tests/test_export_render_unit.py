"""EXPORT-01 rendering: golden DOCX layout, student editions without keys, the PDF Unicode rule
and the ``export.render`` worker handler over in-memory fakes."""

import io
import re
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import export_samples as samples
import pytest
from generation_fakes import FakeStore, GenFakeSession, SyncSession, job

from app.models.authoring import ContentItem, ContentRevision
from app.models.generation import Exam, ExamItem, ExamVersion, ExportJob
from app.services import export_render as render
from app.services import exports
from app.tasks import jobs as tasks

FIXTURES = Path(__file__).parent / "fixtures" / "export"
NOW = datetime(2026, 10, 23, tzinfo=UTC)


@pytest.mark.parametrize(
    "name,factory",
    [
        ("teacher_exam", samples.teacher_exam),
        ("student_exam", samples.student_exam),
        ("lesson_teacher", samples.lesson),
    ],
)
def test_golden_document_xml(name, factory):
    expected = (FIXTURES / f"{name}_document.xml").read_text(encoding="utf-8")
    assert render.document_xml(factory()) == expected


def test_docx_package_is_minimal_valid_and_deterministic():
    data = render.render_docx(samples.teacher_exam())
    assert data == render.render_docx(samples.teacher_exam())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == ["[Content_Types].xml", "_rels/.rels", "word/document.xml"]
        assert archive.testzip() is None
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Phân số nào bằng một nửa?" in xml and "Đáp án: D" in xml


def test_student_edition_never_contains_keys_or_explanations():
    data = render.render_docx(samples.student_exam())  # built from TEACHER items on purpose
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Đáp án" not in xml and "Giải thích" not in xml and "Bí mật" not in xml
    assert "Bản dành cho học sinh" in xml
    assert not any(hasattr(render.StudentExamItem, f) for f in ("correct_key", "explanation"))
    assert "correct_key" not in render.StudentExamItem.__dataclass_fields__


def test_pdf_refuses_vietnamese_glyphs():
    with pytest.raises(render.PdfUnicodeUnsupported):
        render.render_pdf(samples.student_exam())


def ascii_document(count=1, words=3):
    blocks = [render.Block("title", "Quiz (draft)")]
    for i in range(1, count + 1):
        blocks.append(render.Block("question", f"{i}. Which is 1/2? \\ ok " + "word " * words))
        blocks.extend(render.Block("choice", f"{k}. {k.lower()}") for k in "AB")
    return render.RenderDocument("Quiz (draft)", tuple(blocks))


def test_pdf_writer_for_winansi_text():
    data = render.render_pdf(ascii_document())
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert rb"(Quiz \(draft\))" in data and rb"\\ ok" in data
    xref = int(re.search(rb"startxref\n(\d+)", data).group(1))
    assert data[xref:].startswith(b"xref")
    offsets = [int(o) for o in re.findall(rb"(\d{10}) 00000 n", data)]
    for number, offset in enumerate(offsets, start=1):
        assert data[offset:].startswith(f"{number} 0 obj".encode())


def test_long_content_paginates():
    data = render.render_pdf(ascii_document(count=60, words=40))
    assert int(re.search(rb"/Count (\d+)", data).group(1)) > 1


def test_vietnamese_labels_make_every_real_pdf_unsupported():
    # Even an all-ASCII exam carries Vietnamese labels ("điểm", audience line), so PDF exports
    # fail until a font-embedding dependency is approved; this is the documented limitation.
    items = [render.StudentExamItem(1, "1 + 1 = ?", (("A", "2"), ("B", "3")), Decimal(1))]
    with pytest.raises(render.PdfUnicodeUnsupported):
        render.render_pdf(render.student_exam_document("Quiz", items))


# ---- Worker handler -------------------------------------------------------------------------


class Ctx(SimpleNamespace):
    def clock(self):
        return NOW


def exam_fixture(published=True, audience="student", fmt="docx"):
    fake = GenFakeSession()
    workspace, user = uuid4(), uuid4()
    exam = Exam(id=uuid4(), workspace_id=workspace, title="Kiểm tra", status="published")
    version = ExamVersion(
        id=uuid4(),
        workspace_id=workspace,
        exam_id=exam.id,
        version_no=1,
        status="published" if published else "draft",
        total_points=Decimal("10"),
        published_at=NOW if published else None,
    )
    item = ExamItem(
        id=uuid4(),
        workspace_id=workspace,
        exam_version_id=version.id,
        position=1,
        item_type="single_choice",
        stem="Câu hỏi bí ẩn",
        choices=[{"key": k, "text": f"Phương án {k}"} for k in "ABC"],
        points=Decimal("10"),
    )
    fake.exam_keys[item.id] = ("B", "Lời giải chi tiết")
    background = job(workspace, user, "export.render")
    export = ExportJob(
        id=uuid4(),
        workspace_id=workspace,
        background_job_id=background.id,
        exam_version_id=version.id,
        format=fmt,
        audience=audience,
        status="queued",
    )
    for row in (exam, version, item, export):
        fake.add(row)
    store = FakeStore()
    return fake, Ctx(db=SyncSession(fake), job=background, store=store), export, store


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_student_export_uploads_without_key_reads():
    fake, ctx, export, store = exam_fixture()
    result = exports.run_export(ctx)
    assert result["status"] == "succeeded" and fake.exam_key_reads == 0
    key = f"ws/{export.workspace_id}/export/{export.id}.docx"
    assert export.object_key == key and export.status == "succeeded" and export.finished_at
    data, mime = store.objects[key]
    assert mime == render.DOCX_MIME
    xml = docx_text(data)
    assert "Câu hỏi bí ẩn" in xml and "Lời giải" not in xml and "Đáp án" not in xml
    assert exports.run_export(ctx)["replay"] is True


def test_teacher_export_reads_keys_through_functions():
    fake, ctx, export, store = exam_fixture(audience="teacher")
    exports.run_export(ctx)
    xml = docx_text(store.objects[export.object_key][0])
    assert "Đáp án: B" in xml and "Lời giải chi tiết" in xml and fake.exam_key_reads == 2


def test_student_export_of_unpublished_exam_fails():
    _, ctx, _, _ = exam_fixture(published=False)
    with pytest.raises(exports.ExportFailed) as error:
        exports.run_export(ctx)
    assert error.value.code == "audience_not_allowed"


def test_vietnamese_pdf_export_fails_with_clear_code():
    _, ctx, export, store = exam_fixture(fmt="pdf")
    with pytest.raises(tasks.PermanentJobError) as error:
        tasks.render_export(ctx)
    assert error.value.code == "pdf_unicode_unsupported" and store.objects == {}
    exports.mark_failed(ctx, error.value)
    assert export.status == "failed" and export.error_code == "pdf_unicode_unsupported"
    assert tasks.HANDLERS["export.render"].on_permanent_failure is exports.mark_failed


def test_content_export_renders_revision():
    fake = GenFakeSession()
    workspace = uuid4()
    item = ContentItem(id=uuid4(), workspace_id=workspace, kind="lesson_plan", title="Giáo án")
    revision = ContentRevision(
        id=uuid4(),
        workspace_id=workspace,
        content_item_id=item.id,
        revision_no=1,
        body=samples.LESSON_BODY,
        audience="teacher",
        status="draft",
    )
    export = ExportJob(
        id=uuid4(),
        workspace_id=workspace,
        content_revision_id=revision.id,
        format="docx",
        audience="teacher",
        status="queued",
    )
    document = exports.build_document(_JoinDb(fake, revision, item), export)
    assert document.title == "Giáo án" and any("[1]" in b.text for b in document.blocks)
    export.audience = "student"
    with pytest.raises(exports.ExportFailed):
        exports.build_document(_JoinDb(fake, revision, item), export)


class _JoinDb:
    """The content export joins revision+item; return that row directly."""

    def __init__(self, fake, revision, item):
        self.row = (revision, item)

    def execute(self, statement):
        return SimpleNamespace(first=lambda: self.row)


def test_object_keys_and_file_names_are_server_chosen():
    workspace, export_id = uuid4(), uuid4()
    assert (
        exports.object_key(workspace, export_id, "pdf") == f"ws/{workspace}/export/{export_id}.pdf"
    )
    export = ExportJob(exam_version_id=uuid4(), audience="student", format="docx")
    assert exports.file_name(export) == "eduvia-de-kiem-tra-hoc-sinh.docx"
