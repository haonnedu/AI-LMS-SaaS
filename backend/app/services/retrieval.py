"""Authorized hybrid retrieval (KNOW-07) over the caller's private workspace knowledge.

Must run INSIDE ``workspace_transaction``: RLS already limits every row to the verified
workspace, and the SQL additionally pins ``workspace_id`` and applies the authorization/lifecycle
predicates BEFORE any ranking or text leaves the database:

* ``document_versions.status = 'active'`` and it is the document's ``active_version_id``;
* ``documents.status = 'uploaded'``, ``deleted_at IS NULL``, ``rights_attested`` and
  ``rights_scope = 'private'``;
* vectors only when ``embedding_model``/``embedding_version`` equal the configured embedder
  (incompatible vectors are never compared).

Candidates: full-text (``ts_rank_cd`` over ``search_vector`` with ``plainto_tsquery('simple',
...)``) and exact cosine distance (``<=>``, no ANN index, so filtered recall is exact), each
with a bounded per-source budget, fused with reciprocal rank fusion (RRF, k=60). Semantic
candidates farther than ``max_distance`` are not evidence. No candidates => ``[]`` (abstain);
there is never a fallback to other workspaces, shared corpora or looser filters.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from app.services import embeddings

MAX_K = 20
DEFAULT_K = 8
MAX_QUERY_CHARS = 2000
MAX_DOCUMENT_FILTER = 50
RRF_K = 60
DEFAULT_MAX_DISTANCE = 0.8
SOURCES = ("lexical", "semantic")

_HAS_WORD = re.compile(r"\w", re.UNICODE)


class RetrievalRejected(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    page_no: int | None
    section_path: str | None
    text: str
    text_sha256: bytes | None
    lexical_rank: int | None
    semantic_rank: int | None


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    page_no: int | None
    section_path: str | None
    text: str
    score: float
    sources: tuple[str, ...]
    text_sha256: bytes | None = None


def validate(query: str, k: int, document_ids: Sequence[UUID] | None) -> str:
    if not isinstance(k, int) or not 1 <= k <= MAX_K:
        raise RetrievalRejected("invalid_k")
    query = (query or "").strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise RetrievalRejected("invalid_query")
    if document_ids is not None and len(document_ids) > MAX_DOCUMENT_FILTER:
        raise RetrievalRejected("too_many_documents")
    return query


def candidate_budget(k: int) -> int:
    return min(80, max(20, 4 * k))


def rrf_scores(
    rankings: dict[str, Sequence], *, rrf_k: int = RRF_K
) -> dict[object, tuple[float, tuple[str, ...]]]:
    """``rankings`` maps a source name to IDs best-first; returns id -> (score, sources)."""
    scores: dict[object, float] = {}
    found: dict[object, list[str]] = {}
    for source, ids in rankings.items():
        for rank, item in enumerate(ids, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (rrf_k + rank)
            found.setdefault(item, []).append(source)
    return {item: (scores[item], tuple(found[item])) for item in scores}


def fuse(candidates: Sequence[Candidate], k: int, *, rrf_k: int = RRF_K) -> list[RetrievedChunk]:
    """RRF over the ranks the database assigned; stable tie-break on chunk ID."""
    results = []
    for c in candidates:
        score, sources = 0.0, []
        if c.lexical_rank is not None:
            score += 1.0 / (rrf_k + c.lexical_rank)
            sources.append("lexical")
        if c.semantic_rank is not None:
            score += 1.0 / (rrf_k + c.semantic_rank)
            sources.append("semantic")
        if not sources:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                version_id=c.version_id,
                page_no=c.page_no,
                section_path=c.section_path,
                text=c.text,
                score=round(score, 8),
                sources=tuple(sources),
                text_sha256=c.text_sha256,
            )
        )
    results.sort(key=lambda r: (-r.score, str(r.chunk_id)))
    return results[:k]


ELIGIBLE_SQL = """
eligible AS (
  SELECT c.id, c.document_version_id, v.document_id, c.page_no, c.section_path, c.text,
         c.text_sha256, c.search_vector, c.embedding, c.embedding_model, c.embedding_version
  FROM edu.document_chunks c
  JOIN edu.document_versions v
    ON v.workspace_id = c.workspace_id AND v.id = c.document_version_id
  JOIN edu.documents d
    ON d.workspace_id = v.workspace_id AND d.id = v.document_id AND d.active_version_id = v.id
  WHERE c.workspace_id = :workspace_id
    AND v.workspace_id = :workspace_id
    AND d.workspace_id = :workspace_id
    AND v.status = 'active'
    AND d.status = 'uploaded'
    AND d.deleted_at IS NULL
    AND d.rights_attested
    AND d.rights_scope = 'private'{document_filter}
)"""

LEXICAL_SQL = """
lexical AS (
  SELECT e.id, row_number() OVER (
           ORDER BY ts_rank_cd(e.search_vector, q.query) DESC, e.id) AS rank
  FROM eligible e, plainto_tsquery('simple', :query) AS q(query)
  WHERE e.search_vector @@ q.query
  ORDER BY rank
  LIMIT :budget
)"""

SEMANTIC_SQL = """
semantic AS (
  SELECT ranked.id, ranked.rank FROM (
    SELECT e.id, e.embedding <=> CAST(:embedding AS vector) AS distance,
           row_number() OVER (ORDER BY e.embedding <=> CAST(:embedding AS vector), e.id) AS rank
    FROM eligible e
    WHERE e.embedding IS NOT NULL
      AND e.embedding_model = :model
      AND e.embedding_version = :model_version
  ) ranked
  WHERE ranked.distance <= :max_distance
  ORDER BY ranked.rank
  LIMIT :budget
)"""

EMPTY_SEMANTIC_SQL = """
semantic AS (SELECT NULL::uuid AS id, NULL::bigint AS rank WHERE false)"""


def build_sql(*, with_vector: bool, with_documents: bool) -> str:
    """The single retrieval statement. Every filter is a bound parameter (no interpolation of
    user input); only fixed fragments are chosen here."""
    document_filter = "\n    AND d.id = ANY(:document_ids)" if with_documents else ""
    ctes = [
        ELIGIBLE_SQL.format(document_filter=document_filter),
        LEXICAL_SQL,
        SEMANTIC_SQL if with_vector else EMPTY_SEMANTIC_SQL,
    ]
    return (
        "WITH "
        + ",".join(ctes)
        + """
SELECT e.id AS chunk_id, e.document_id, e.document_version_id AS version_id, e.page_no,
       e.section_path, e.text, e.text_sha256, l.rank AS lexical_rank, s.rank AS semantic_rank
FROM eligible e
LEFT JOIN lexical l ON l.id = e.id
LEFT JOIN semantic s ON s.id = e.id
WHERE l.id IS NOT NULL OR s.id IS NOT NULL
"""
    )


def build_params(
    workspace_id: UUID,
    query: str,
    k: int,
    *,
    query_vector: Sequence[float] | None,
    model: str | None,
    model_version: str | None,
    document_ids: Sequence[UUID] | None,
    max_distance: float,
) -> dict:
    params: dict = {"workspace_id": workspace_id, "query": query, "budget": candidate_budget(k)}
    if query_vector is not None:
        params.update(
            embedding=embeddings.vector_literal(query_vector),
            model=model,
            model_version=model_version,
            max_distance=max_distance,
        )
    if document_ids is not None:
        params["document_ids"] = list(document_ids)
    return params


async def retrieve(
    db,
    scope,
    query: str,
    *,
    document_ids: Sequence[UUID] | None = None,
    k: int = DEFAULT_K,
    query_vector: Sequence[float] | None = None,
    model: str | None = None,
    model_version: str | None = None,
    max_distance: float = DEFAULT_MAX_DISTANCE,
) -> list[RetrievedChunk]:
    """Hybrid retrieval inside the caller's ``workspace_transaction``. Without a query vector
    (provider unavailable) only the lexical half runs; it never widens authorization."""
    query = validate(query, k, document_ids)
    if not _HAS_WORD.search(query):
        return []
    if document_ids is not None and not document_ids:
        return []
    with_vector = query_vector is not None and model is not None and model_version is not None
    sql = build_sql(with_vector=with_vector, with_documents=document_ids is not None)
    params = build_params(
        scope.workspace.id,
        query,
        k,
        query_vector=query_vector if with_vector else None,
        model=model,
        model_version=model_version,
        document_ids=document_ids,
        max_distance=max_distance,
    )
    rows = (await db.execute(text(sql), params)).all()
    candidates = [
        Candidate(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            version_id=row.version_id,
            page_no=row.page_no,
            section_path=row.section_path,
            text=row.text,
            text_sha256=bytes(row.text_sha256) if row.text_sha256 is not None else None,
            lexical_rank=row.lexical_rank,
            semantic_rank=row.semantic_rank,
        )
        for row in rows
    ]
    return fuse(candidates, k)
