"""Private-document ingest pipeline (KNOW-02..05): parse -> chunk -> immutable version ->
atomic activation. Worker-side, synchronous session, RLS context already set for the job.

Activation invariant: a new version is written as ``processing`` with all its chunks, then in
the same transaction the previous ``active`` version becomes ``superseded``, the new one
``active`` and ``documents.active_version_id`` points at it. Any failure rolls the whole
transaction back; the caller then records a ``failed`` version (see ``record_failed_version``)
in a separate transaction, so the previously active version is never touched by a failure.

Rights (KNOW-02): only ``rights_attested`` documents with ``rights_scope='private'`` are ever
indexed, and chunks stay in the uploading workspace. There is no shared corpus.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.documents import Document
from app.models.knowledge import DocumentChunk, DocumentVersion
from app.services import chunking, parsing

Mode = Literal["ingest", "reingest"]


class IngestRejected(Exception):
    """Permanent, safe-to-show ingest failure; carries what is needed for a failed version."""

    def __init__(self, code: str, *, parser: str, parser_version: str, suspicious=False):
        super().__init__(code)
        self.code = code
        self.parser = parser
        self.parser_version = parser_version
        # Malformed/hostile input or exhausted limits: quarantine a not-yet-published upload.
        # Merely unsupported input (scanned PDF, no PDF parser) stays downloadable.
        self.suspicious = suspicious


@dataclass(frozen=True)
class Built:
    parsed: parsing.ParsedDocument
    chunked: chunking.ChunkedDocument


def parser_identity(mime: str | None) -> tuple[str, str]:
    parser = parsing.parser_for(mime)
    if parser is None:
        return "none", "0"
    return parser.name, parser.full_version()


def check_rights(document: Document) -> None:
    """KNOW-02: never index unattested or non-private documents (defence in depth; the DB
    also rejects ``active_version_id`` without ``rights_attested``)."""
    if not document.rights_attested or (document.rights_scope or "private") != "private":
        name, version = parser_identity(document.mime_type)
        raise IngestRejected(
            "rights_attestation_required", parser=name, parser_version=version, suspicious=True
        )


def build(
    data: bytes, mime: str, *, max_bytes: int, timeout: float = parsing.DEFAULT_TIMEOUT_SECONDS
) -> Built:
    name, version = parser_identity(mime)
    try:
        parsed = parsing.parse_document(data, mime, max_bytes=max_bytes, timeout=timeout)
    except parsing.DocumentRejected as exc:
        raise IngestRejected(
            exc.code,
            parser=name,
            parser_version=version,
            suspicious=not isinstance(exc, parsing.UnsupportedDocument),
        ) from None
    chunked = chunking.chunk_document(parsed)
    if not chunked.chunks:
        raise IngestRejected(
            "empty_document", parser=parsed.parser, parser_version=parsed.parser_version
        )
    return Built(parsed, chunked)


def active_version(db: Session, document_id) -> DocumentVersion | None:
    return db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id, DocumentVersion.status == "active")
        .with_for_update()
    ).first()


def next_version_no(db: Session, document_id) -> int:
    current = db.scalar(
        select(func.max(DocumentVersion.version_no)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return int(current or 0) + 1


def is_current(active: DocumentVersion | None, built: Built, mode: Mode) -> bool:
    """Idempotency: same text already active => nothing to do. Re-ingest additionally
    requires the same parser and chunker versions (a newer pipeline re-chunks)."""
    if active is None or active.text_sha256 is None:
        return False
    if bytes(active.text_sha256) != built.chunked.text_sha256:
        return False
    if mode == "ingest":
        return True
    return (
        active.parser_version == built.parsed.parser_version
        and active.chunker_version == built.chunked.chunker_version
    )


def activate(
    db: Session,
    document: Document,
    version: DocumentVersion,
    previous: DocumentVersion | None,
    now: datetime,
) -> None:
    """Supersede-then-activate with a flush in between so the partial unique index on
    ``status='active'`` never sees two active rows. Caller owns the transaction."""
    if version.status != "processing":
        raise ValueError("only a processing version can be activated")
    if not document.rights_attested:
        raise ValueError("rights attestation required")
    if previous is not None and previous.id != version.id:
        previous.status = "superseded"
        db.flush()
    version.status = "active"
    version.activated_at = now
    db.flush()
    document.active_version_id = version.id
    if document.status == "pending":
        document.status = "uploaded"
    db.flush()


def _result(version: DocumentVersion, *, unchanged: bool) -> dict[str, Any]:
    return {
        "pages": version.page_count,
        "versionId": str(version.id),
        "versionNo": version.version_no,
        "chunks": version.chunk_count,
        "unchanged": unchanged,
    }


def ingest_bytes(
    db: Session,
    document: Document,
    data: bytes,
    *,
    mode: Mode,
    max_bytes: int,
    now: datetime,
    timeout: float = parsing.DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    check_rights(document)
    built = build(data, document.mime_type, max_bytes=max_bytes, timeout=timeout)
    previous = active_version(db, document.id)
    if is_current(previous, built, mode):
        document.active_version_id = previous.id
        if document.status == "pending":
            document.status = "uploaded"
        db.flush()
        return _result(previous, unchanged=True)

    version = DocumentVersion(
        id=uuid4(),
        workspace_id=document.workspace_id,
        document_id=document.id,
        version_no=next_version_no(db, document.id),
        status="processing",
        parser=built.parsed.parser,
        parser_version=built.parsed.parser_version,
        chunker_version=built.chunked.chunker_version,
        page_count=built.parsed.page_count,
        char_count=len(built.chunked.text),
        chunk_count=len(built.chunked.chunks),
        text_sha256=built.chunked.text_sha256,
        created_at=now,
    )
    db.add(version)
    db.flush()
    db.add_all(
        [
            DocumentChunk(
                id=uuid4(),
                workspace_id=document.workspace_id,
                document_version_id=version.id,
                chunk_index=chunk.chunk_index,
                page_no=chunk.page_no,
                section_path=chunk.section_path,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                text=chunk.text,
                text_sha256=chunk.text_sha256,
                token_estimate=chunk.token_estimate,
                created_at=now,
            )
            for chunk in built.chunked.chunks
        ]
    )
    db.flush()
    activate(db, document, version, previous, now)
    return _result(version, unchanged=False)


def record_failed_version(
    db: Session,
    document: Document,
    *,
    code: str,
    parser: str,
    parser_version: str,
    now: datetime,
) -> DocumentVersion:
    """Runs in the failure transaction: the active version (if any) is left untouched."""
    version = DocumentVersion(
        id=uuid4(),
        workspace_id=document.workspace_id,
        document_id=document.id,
        version_no=next_version_no(db, document.id),
        status="failed",
        parser=parser,
        parser_version=parser_version,
        chunker_version=chunking.CHUNKER_VERSION,
        page_count=None,
        char_count=0,
        chunk_count=0,
        text_sha256=None,
        error_code=code[:64],
        created_at=now,
    )
    db.add(version)
    db.flush()
    return version
