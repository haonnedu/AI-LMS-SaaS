"""Durable Word/PDF exports (EXPORT-01): ``export.render`` jobs.

API side ``enqueue_export`` checks the source (content revision XOR exam version) inside the
caller's workspace and the audience rules, then enqueues the job and an ``export_jobs`` row:

* student audience of a content revision: only a ``published`` revision whose own audience is
  ``student`` (a teacher revision is never re-labelled as student material);
* student audience of an exam: only a published version; the student renderer has no access to
  keys or explanations (separate code path and item type);
* teacher audience: any revision/version of the workspace (teacher roles only, at the API).

Worker side ``run_export`` renders under the job actor's RLS context, uploads to the private
bucket under the server-chosen key ``ws/{workspace}/export/{export_id}.{ext}`` and marks the row
``succeeded``. Object keys and signed URLs are never logged.
"""

import hashlib
import io
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.authoring import ContentItem, ContentRevision
from app.models.generation import Exam, ExamItem, ExamVersion, ExportJob
from app.services import export_render
from app.services import jobs as job_service
from app.services.authoring_common import Conflict, Invalid, NotFound, Scope, utcnow

KIND = "export.render"
FORMATS = frozenset({"docx", "pdf"})
AUDIENCES = frozenset({"teacher", "student"})
EXPORT_NOT_FOUND = ("export_not_found", "Không tìm thấy yêu cầu xuất tệp.")


class ExportFailed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def object_key(workspace_id: UUID, export_id: UUID, extension: str) -> str:
    return f"ws/{UUID(str(workspace_id))}/export/{UUID(str(export_id))}.{extension}"


def file_name(export: ExportJob) -> str:
    source = "de-kiem-tra" if export.exam_version_id else "noi-dung"
    audience = "giao-vien" if export.audience == "teacher" else "hoc-sinh"
    return f"eduvia-{source}-{audience}.{export.format}"


def mime_for(fmt: str) -> str:
    return export_render.PDF_MIME if fmt == "pdf" else export_render.DOCX_MIME


# ---- API side -------------------------------------------------------------------------------


async def enqueue_export(
    db,
    scope: Scope,
    *,
    content_revision_id: UUID | None,
    exam_version_id: UUID | None,
    fmt: str,
    audience: str,
    idempotency_key: str,
):
    if (content_revision_id is None) == (exam_version_id is None):
        raise Invalid("invalid_export_source", "Cần chọn đúng một nguồn: nội dung hoặc đề.")
    if fmt not in FORMATS or audience not in AUDIENCES:
        raise Invalid("invalid_export_options", "Định dạng hoặc đối tượng không hợp lệ.")
    payload: dict[str, Any] = {"format": fmt, "audience": audience}
    if content_revision_id is not None:
        revision = await db.scalar(
            select(ContentRevision).where(
                ContentRevision.id == content_revision_id,
                ContentRevision.workspace_id == scope.workspace.id,
            )
        )
        if revision is None:
            raise NotFound("revision_not_found", "Không tìm thấy phiên bản nội dung.")
        if audience == "student" and (
            revision.audience != "student" or revision.status != "published"
        ):
            raise Conflict(
                "audience_not_allowed",
                "Chỉ phiên bản đã xuất bản dành cho học sinh mới được xuất bản học sinh.",
            )
        payload["contentRevisionId"] = str(revision.id)
    else:
        version = await db.scalar(
            select(ExamVersion).where(
                ExamVersion.id == exam_version_id,
                ExamVersion.workspace_id == scope.workspace.id,
            )
        )
        if version is None:
            raise NotFound("exam_version_not_found", "Không tìm thấy phiên bản đề kiểm tra.")
        if audience == "student" and version.published_at is None:
            raise Conflict(
                "audience_not_allowed", "Chỉ đề đã xuất bản mới được xuất bản cho học sinh."
            )
        payload["examVersionId"] = str(version.id)
    job, created = await job_service.enqueue_job(db, scope, KIND, payload, idempotency_key)
    if not created:
        existing = await db.scalar(
            select(ExportJob).where(
                ExportJob.workspace_id == scope.workspace.id,
                ExportJob.background_job_id == job.id,
            )
        )
        if existing is None:
            raise NotFound(*EXPORT_NOT_FOUND)
        return existing, job, False
    export = ExportJob(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        background_job_id=job.id,
        content_revision_id=content_revision_id,
        exam_version_id=exam_version_id,
        format=fmt,
        audience=audience,
        status="queued",
        created_at=utcnow(),
    )
    db.add(export)
    await db.flush()
    return export, job, True


async def load_export(db, workspace_id: UUID, export_id: UUID) -> ExportJob:
    export = await db.scalar(
        select(ExportJob).where(ExportJob.id == export_id, ExportJob.workspace_id == workspace_id)
    )
    if export is None:
        raise NotFound(*EXPORT_NOT_FOUND)
    return export


# ---- Worker side ----------------------------------------------------------------------------


def _content_document(db: Session, export: ExportJob) -> export_render.RenderDocument:
    row = db.execute(
        select(ContentRevision, ContentItem)
        .join(
            ContentItem,
            (ContentItem.workspace_id == ContentRevision.workspace_id)
            & (ContentItem.id == ContentRevision.content_item_id),
        )
        .where(
            ContentRevision.workspace_id == export.workspace_id,
            ContentRevision.id == export.content_revision_id,
        )
    ).first()
    if row is None:
        raise ExportFailed("source_not_found")
    revision, item = row
    if export.audience == "student" and (
        revision.audience != "student" or revision.status != "published"
    ):
        raise ExportFailed("audience_not_allowed")
    return export_render.content_document(item.title, revision.body, export.audience)


def _exam_rows(db: Session, export: ExportJob) -> tuple[Exam, ExamVersion, list[ExamItem]]:
    version = db.scalar(
        select(ExamVersion).where(
            ExamVersion.workspace_id == export.workspace_id,
            ExamVersion.id == export.exam_version_id,
        )
    )
    if version is None:
        raise ExportFailed("source_not_found")
    exam = db.scalar(
        select(Exam).where(Exam.workspace_id == version.workspace_id, Exam.id == version.exam_id)
    )
    items = list(
        db.scalars(
            select(ExamItem)
            .where(
                ExamItem.workspace_id == version.workspace_id,
                ExamItem.exam_version_id == version.id,
            )
            .order_by(ExamItem.position)
        ).all()
    )
    return exam, version, items


def _choices(item: ExamItem) -> tuple[tuple[str, str], ...]:
    return tuple((choice["key"], choice["text"]) for choice in item.choices)


def student_exam_document(db: Session, export: ExportJob) -> export_render.RenderDocument:
    """Never references the key/explanation readers."""
    exam, version, items = _exam_rows(db, export)
    if version.published_at is None:
        raise ExportFailed("audience_not_allowed")
    return export_render.student_exam_document(
        exam.title,
        [
            export_render.StudentExamItem(
                position=item.position,
                stem=item.stem,
                choices=_choices(item),
                points=Decimal(item.points),
            )
            for item in items
        ],
    )


def teacher_exam_document(db: Session, export: ExportJob) -> export_render.RenderDocument:
    exam, _, items = _exam_rows(db, export)
    teacher_items = []
    for item in items:
        key = db.scalar(select(func.edu.exam_item_key(item.id)))
        explanation = db.scalar(select(func.edu.exam_item_explanation(item.id)))
        teacher_items.append(
            export_render.TeacherExamItem(
                position=item.position,
                stem=item.stem,
                choices=_choices(item),
                points=Decimal(item.points),
                correct_key=key.strip() if isinstance(key, str) else None,
                explanation=explanation,
            )
        )
    return export_render.teacher_exam_document(exam.title, teacher_items)


def build_document(db: Session, export: ExportJob) -> export_render.RenderDocument:
    if export.content_revision_id is not None:
        return _content_document(db, export)
    if export.audience == "student":
        return student_exam_document(db, export)
    return teacher_exam_document(db, export)


def _load(db: Session, job) -> ExportJob | None:
    return db.scalar(
        select(ExportJob)
        .where(
            ExportJob.workspace_id == job.workspace_id,
            ExportJob.background_job_id == job.id,
        )
        .with_for_update()
    )


def run_export(ctx) -> dict[str, Any]:
    db: Session = ctx.db
    export = _load(db, ctx.job)
    if export is None:
        raise ExportFailed("invalid_job_input")
    if export.status != "queued":
        return {"exportId": str(export.id), "status": export.status, "replay": True}
    document = build_document(db, export)
    try:
        data, mime, extension = export_render.render(document, export.format)
    except export_render.PdfUnicodeUnsupported:
        raise ExportFailed("pdf_unicode_unsupported") from None
    key = object_key(export.workspace_id, export.id, extension)
    ctx.store.put(
        key, io.BytesIO(data), mime=mime, size=len(data), sha256=hashlib.sha256(data).digest()
    )
    now: datetime = ctx.clock()
    export.object_key = key
    export.status = "succeeded"
    export.finished_at = now
    db.flush()
    return {"exportId": str(export.id), "status": "succeeded", "sizeBytes": len(data)}


def mark_failed(ctx, error: Exception) -> None:
    export = _load(ctx.db, ctx.job)
    if export is None or export.status != "queued":
        return
    export.status = "failed"
    export.error_code = str(getattr(error, "code", "transient_error"))[:64]
    export.finished_at = ctx.clock()
    ctx.db.flush()
