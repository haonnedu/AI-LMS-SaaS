"""Review with provenance (AUTHR-04).

``revision_provenance`` explains where a content revision came from: the generation job
(provider/model/prompt version/validation status) and every source, resolved through
``services.citations.resolve_citation`` under the caller's workspace transaction. Nothing is
fabricated: a chunk that no longer resolves (purged, deleted document, withdrawn version or not
visible) is reported as ``withdrawn`` without text; a superseded version is ``superseded``.

``check_citations`` is the approval hook: every chunk cited in the body must still resolve,
otherwise ``Conflict('citations_unresolved')`` (409).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.api.identity import ApiError
from app.models.authoring import ContentRevision
from app.models.generation import GenerationJob, GenerationSource
from app.services import citations
from app.services.authoring_common import Conflict, Scope


@dataclass(frozen=True)
class SourceProvenance:
    label: str
    chunk_id: UUID | None
    document_id: UUID | None
    version_id: UUID | None
    page_no: int | None
    section_path: str | None
    snippet: str | None
    status: str  # active | superseded | withdrawn
    cited: bool


@dataclass
class Provenance:
    generation_job_id: UUID | None = None
    provider: str | None = None
    model: str | None = None
    prompt_version: str | None = None
    validation_status: str | None = None
    sources: list[SourceProvenance] = field(default_factory=list)


def ordered_citations(body: Mapping[str, Any]) -> list[tuple[UUID, str]]:
    """Distinct cited chunks in first-appearance order with their body label."""
    seen: dict[UUID, str] = {}
    for section in body.get("sections", []):
        for block in section.get("blocks", []):
            for citation in block.get("citations", []):
                chunk = UUID(citation["chunkId"])
                seen.setdefault(chunk, citation["label"])
    return list(seen.items())


async def resolve(db, scope: Scope, chunk_id: UUID | None, label: str, cited: bool):
    if chunk_id is None:
        return SourceProvenance(label, None, None, None, None, None, None, "withdrawn", cited)
    try:
        preview = await citations.resolve_citation(db, scope, chunk_id, allow_superseded=True)
    except ApiError as exc:
        status = "superseded" if exc.code == "citation_superseded" else "withdrawn"
        return SourceProvenance(label, chunk_id, None, None, None, None, None, status, cited)
    status = "active" if preview.version_status == "active" else "superseded"
    return SourceProvenance(
        label=label,
        chunk_id=preview.chunk_id,
        document_id=preview.document_id,
        version_id=preview.version_id,
        page_no=preview.page_no,
        section_path=preview.section_path,
        snippet=preview.snippet,
        status=status,
        cited=cited,
    )


async def generation_for(db, revision: ContentRevision) -> GenerationJob | None:
    if revision.generation_job_id is None:
        return None
    return await db.scalar(
        select(GenerationJob).where(
            GenerationJob.workspace_id == revision.workspace_id,
            GenerationJob.background_job_id == revision.generation_job_id,
        )
    )


async def revision_provenance(db, scope: Scope, revision: ContentRevision) -> Provenance:
    result = Provenance()
    generation = await generation_for(db, revision)
    cited = ordered_citations(revision.body or {})
    cited_ids = {chunk for chunk, _ in cited}
    for chunk, label in cited:
        result.sources.append(await resolve(db, scope, chunk, label, True))
    if generation is not None:
        result.generation_job_id = generation.id
        result.provider = generation.provider
        result.model = generation.model
        result.prompt_version = generation.prompt_version
        result.validation_status = generation.validation_status
        rows = (
            await db.scalars(
                select(GenerationSource)
                .where(
                    GenerationSource.workspace_id == revision.workspace_id,
                    GenerationSource.generation_job_id == generation.id,
                )
                .order_by(GenerationSource.rank)
            )
        ).all()
        for row in rows:
            if row.chunk_id is not None and row.chunk_id in cited_ids:
                continue
            result.sources.append(await resolve(db, scope, row.chunk_id, row.citation_label, False))
    return result


async def unresolved_citations(db, scope: Scope, body: Mapping[str, Any]) -> list[UUID]:
    missing = []
    for chunk, label in ordered_citations(body):
        source = await resolve(db, scope, chunk, label, True)
        if source.status == "withdrawn":
            missing.append(chunk)
    return missing


async def check_citations(db, scope: Scope, body: Mapping[str, Any]) -> None:
    """Approval hook: refuse while any cited chunk cannot be resolved."""
    missing = await unresolved_citations(db, scope, body)
    if missing:
        raise Conflict(
            "citations_unresolved",
            f"Có {len(missing)} trích dẫn không còn truy xuất được nguồn; "
            "hãy sửa hoặc bỏ trích dẫn trước khi duyệt.",
        )
