"""Citations (KNOW-08): labels, verbatim bounded snippets, hashes and the preview policy."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.identity import ApiError
from app.models.documents import Document
from app.models.knowledge import DocumentChunk, DocumentVersion
from app.services import citations
from app.services.retrieval import RetrievedChunk

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
LONG = (
    "Cấp số cộng là dãy số mà mỗi số hạng bằng số hạng đứng trước cộng công sai d. " * 10
).strip()


def retrieved(text="Mệnh đề là một câu khẳng định.", chunk_id=None, digest=None):
    return RetrievedChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        page_no=3,
        section_path="Chương 1 > Mệnh đề",
        text=text,
        score=0.03,
        sources=("lexical",),
        text_sha256=digest,
    )


def test_labels_are_sequential_and_duplicates_collapse():
    first, second = retrieved(), retrieved()
    cited = citations.build_citations([first, second, first])
    assert [c.label for c in cited] == ["[1]", "[2]"]
    assert cited[0].chunk_id == first.chunk_id and cited[0].version_id == first.version_id
    assert (cited[0].page_no, cited[0].section_path) == (3, "Chương 1 > Mệnh đề")


def test_snippet_is_verbatim_bounded_and_hashed():
    chunk = retrieved(LONG)
    (citation,) = citations.build_citations([chunk])
    assert len(citation.snippet) <= citations.SNIPPET_CHARS
    assert citation.snippet.endswith("…")
    assert LONG.startswith(citation.snippet[:-1])
    assert citation.text_sha256 == hashlib.sha256(LONG.encode()).hexdigest()
    stored = hashlib.sha256(b"stored").digest()
    assert citations.build_citations([retrieved(digest=stored)])[0].text_sha256 == stored.hex()


def test_short_snippet_is_unchanged_and_empty_input_has_no_citations():
    assert citations.snippet("Ngắn  gọn\n thôi") == "Ngắn gọn thôi"
    assert citations.build_citations([]) == []


def make(version_status="active", doc_status="uploaded", owner=None, is_active=True):
    version = DocumentVersion(id=uuid4(), status=version_status)
    document = Document(
        id=uuid4(),
        status=doc_status,
        deleted_at=NOW if doc_status == "deleted" else None,
        owner_user_id=owner or uuid4(),
        active_version_id=version.id if is_active else uuid4(),
    )
    return version, document


def test_active_version_is_previewable():
    version, document = make()
    citations.decide(version, document, uuid4(), allow_superseded=False)


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"version_status": "withdrawn", "is_active": False}, "citation_not_found"),
        ({"doc_status": "deleted"}, "citation_not_found"),
        ({"doc_status": "quarantined"}, "citation_not_found"),
        ({"version_status": "failed", "is_active": False}, "citation_not_found"),
        ({"version_status": "superseded", "is_active": False}, "citation_superseded"),
    ],
)
def test_unavailable_sources_are_404(kwargs, code):
    version, document = make(**kwargs)
    with pytest.raises(ApiError) as raised:
        citations.decide(version, document, uuid4(), allow_superseded=True)
    assert raised.value.status == 404 and raised.value.code == code


def test_superseded_needs_explicit_pin_and_ownership():
    owner = uuid4()
    version, document = make("superseded", owner=owner, is_active=False)
    citations.decide(version, document, owner, allow_superseded=True)
    for user, allow in ((owner, False), (uuid4(), True)):
        with pytest.raises(ApiError) as raised:
            citations.decide(version, document, user, allow_superseded=allow)
        assert raised.value.status == 404


class FakeDb:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(str(statement))
        return SimpleNamespace(first=lambda: self.row)


def scope(workspace_id, user_id=None):
    return SimpleNamespace(
        workspace=SimpleNamespace(id=workspace_id), user=SimpleNamespace(id=user_id or uuid4())
    )


async def test_resolve_missing_chunk_is_404_never_a_guess():
    db = FakeDb(None)
    with pytest.raises(ApiError) as raised:
        await citations.resolve_citation(db, scope(uuid4()), uuid4())
    assert raised.value.status == 404
    (sql,) = db.statements
    assert "edu.document_chunks.workspace_id = :workspace_id_" in sql


async def test_resolve_returns_exact_version_page_and_snippet():
    workspace = uuid4()
    version, document = make()
    version.workspace_id = document.workspace_id = workspace
    version.version_no, version.activated_at = 2, NOW
    document.file_name = "Giáo án.txt"
    chunk = DocumentChunk(
        id=uuid4(),
        workspace_id=workspace,
        document_version_id=version.id,
        page_no=4,
        section_path="Bài 2",
        char_start=10,
        char_end=10 + len(LONG),
        text=LONG,
        text_sha256=hashlib.sha256(LONG.encode()).digest(),
    )
    preview = await citations.resolve_citation(
        FakeDb((chunk, version, document)), scope(workspace), chunk.id
    )
    assert (preview.version_id, preview.version_no, preview.page_no) == (version.id, 2, 4)
    assert preview.text == LONG and LONG.startswith(preview.snippet[:-1])
    assert preview.text_sha256 == hashlib.sha256(LONG.encode()).hexdigest()
    assert preview.file_name == "Giáo án.txt"
