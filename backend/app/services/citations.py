"""Citations and source preview (KNOW-08).

``build_citations`` labels retrieved chunks ``[1]..[n]`` with the exact version/page/section and a
bounded snippet taken verbatim from the chunk (plus the chunk's SHA-256 so a later reader can
prove the snippet was not altered). ``resolve_citation`` re-reads one chunk under the caller's
workspace transaction for the preview UI. It never fabricates: a missing chunk, a deleted
document or a withdrawn version is a 404, and a superseded version is shown only when the caller
explicitly asks for a historical pin AND owns the document.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.api.identity import ApiError
from app.models.documents import Document
from app.models.knowledge import DocumentChunk, DocumentVersion

SNIPPET_CHARS = 300


@dataclass(frozen=True)
class Citation:
    label: str
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    page_no: int | None
    section_path: str | None
    snippet: str
    text_sha256: str


@dataclass(frozen=True)
class CitationPreview:
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    version_no: int
    version_status: str
    file_name: str
    page_no: int | None
    section_path: str | None
    char_start: int
    char_end: int
    snippet: str
    text: str
    text_sha256: str
    activated_at: datetime | None


def snippet(text: str, limit: int = SNIPPET_CHARS) -> str:
    """Verbatim prefix of the chunk, cut at a word boundary when possible (never paraphrased)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def sha256_hex(text: str, digest: bytes | None = None) -> str:
    return bytes(digest).hex() if digest else hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_citations(chunks: Sequence) -> list[Citation]:
    """One citation per distinct chunk, in retrieval order; labels are stable ``[n]``."""
    citations: list[Citation] = []
    seen: set[UUID] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen:
            continue
        seen.add(chunk.chunk_id)
        citations.append(
            Citation(
                label=f"[{len(citations) + 1}]",
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                version_id=chunk.version_id,
                page_no=chunk.page_no,
                section_path=chunk.section_path,
                snippet=snippet(chunk.text),
                text_sha256=sha256_hex(chunk.text, getattr(chunk, "text_sha256", None)),
            )
        )
    return citations


def _not_found() -> ApiError:
    return ApiError(404, "citation_not_found", "Không tìm thấy nguồn trích dẫn.")


def decide(version: DocumentVersion, document: Document, user_id, allow_superseded: bool) -> None:
    """Pure policy: raise 404 unless this source may be previewed."""
    if document.status != "uploaded" or document.deleted_at is not None:
        raise _not_found()
    if version.status == "active" and document.active_version_id == version.id:
        return
    if version.status == "superseded" and allow_superseded and document.owner_user_id == user_id:
        return
    if version.status == "superseded":
        raise ApiError(
            404,
            "citation_superseded",
            "Nguồn trích dẫn thuộc phiên bản tài liệu cũ, không còn được sử dụng.",
        )
    raise _not_found()


async def resolve_citation(
    db, scope, chunk_id: UUID, *, allow_superseded: bool = False
) -> CitationPreview:
    """Inside ``workspace_transaction``: RLS plus explicit workspace predicates."""
    workspace_id = scope.workspace.id
    row = (
        await db.execute(
            select(DocumentChunk, DocumentVersion, Document)
            .join(
                DocumentVersion,
                (DocumentVersion.workspace_id == DocumentChunk.workspace_id)
                & (DocumentVersion.id == DocumentChunk.document_version_id),
            )
            .join(
                Document,
                (Document.workspace_id == DocumentVersion.workspace_id)
                & (Document.id == DocumentVersion.document_id),
            )
            .where(DocumentChunk.id == chunk_id, DocumentChunk.workspace_id == workspace_id)
        )
    ).first()
    if row is None:
        raise _not_found()
    chunk, version, document = row
    decide(version, document, scope.user.id, allow_superseded)
    return CitationPreview(
        chunk_id=chunk.id,
        document_id=document.id,
        version_id=version.id,
        version_no=version.version_no,
        version_status=version.status,
        file_name=document.file_name,
        page_no=chunk.page_no,
        section_path=chunk.section_path,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        snippet=snippet(chunk.text),
        text=chunk.text,
        text_sha256=bytes(chunk.text_sha256).hex(),
        activated_at=version.activated_at,
    )
