"""Hybrid retrieval policy (KNOW-07/09): RRF math, guardrails, and the SQL filter builder."""

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import retrieval
from app.services.retrieval import Candidate


def candidate(lexical=None, semantic=None, chunk_id=None):
    return Candidate(
        chunk_id=chunk_id or uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        page_no=1,
        section_path="Chương 1",
        text="Mệnh đề là một câu khẳng định.",
        text_sha256=hashlib.sha256(b"x").digest(),
        lexical_rank=lexical,
        semantic_rank=semantic,
    )


# ---------------------------------------------------------------- RRF


def test_rrf_scores_sum_reciprocal_ranks():
    scores = retrieval.rrf_scores({"lexical": ["a", "b"], "semantic": ["b", "c"]})
    assert scores["b"][0] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["a"] == (pytest.approx(1 / 61), ("lexical",))
    assert scores["b"][1] == ("lexical", "semantic")
    assert scores["c"] == (pytest.approx(1 / 62), ("semantic",))


def test_fuse_prefers_agreement_and_cuts_to_k():
    both = candidate(lexical=2, semantic=2)
    lexical_top = candidate(lexical=1)
    semantic_top = candidate(semantic=1)
    tail = [candidate(lexical=10 + i) for i in range(10)]
    fused = retrieval.fuse([lexical_top, tail[0], both, semantic_top, *tail[1:]], k=3)
    assert [c.chunk_id for c in fused][0] == both.chunk_id
    assert len(fused) == 3
    assert fused[0].score == pytest.approx(2 / 62, abs=1e-8)
    assert fused[0].sources == ("lexical", "semantic")


def test_fuse_tie_break_is_stable_and_drops_unranked():
    a, b = sorted([uuid4(), uuid4()], key=str)
    fused = retrieval.fuse([candidate(lexical=1, chunk_id=b), candidate(semantic=1, chunk_id=a)], 5)
    assert [c.chunk_id for c in fused] == [a, b]
    assert retrieval.fuse([candidate()], 5) == []


# ---------------------------------------------------------------- guardrails


@pytest.mark.parametrize(
    "query,k,ids,code",
    [
        ("Mệnh đề", 0, None, "invalid_k"),
        ("Mệnh đề", 21, None, "invalid_k"),
        ("   ", 5, None, "invalid_query"),
        ("x" * 2001, 5, None, "invalid_query"),
        ("Mệnh đề", 5, [uuid4() for _ in range(51)], "too_many_documents"),
    ],
)
def test_validate_rejects_out_of_bounds(query, k, ids, code):
    with pytest.raises(retrieval.RetrievalRejected, match=code):
        retrieval.validate(query, k, ids)


def test_candidate_budget_is_bounded():
    assert retrieval.candidate_budget(1) == 20
    assert retrieval.candidate_budget(20) == 80
    assert retrieval.MAX_K == 20


# ---------------------------------------------------------------- SQL builder


def normalized(sql: str) -> str:
    return " ".join(sql.split())


def test_sql_applies_authorization_and_lifecycle_filters_before_ranking():
    sql = normalized(retrieval.build_sql(with_vector=True, with_documents=False))
    eligible = sql.split("lexical AS")[0]
    for predicate in (
        "c.workspace_id = :workspace_id",
        "v.workspace_id = :workspace_id",
        "d.workspace_id = :workspace_id",
        "v.status = 'active'",
        "d.active_version_id = v.id",
        "d.status = 'uploaded'",
        "d.deleted_at IS NULL",
        "d.rights_attested",
        "d.rights_scope = 'private'",
    ):
        assert predicate in eligible, predicate
    # Ranking only ever reads the authorized ``eligible`` set.
    assert sql.count("FROM edu.document_chunks") == 1
    assert "FROM eligible e, plainto_tsquery('simple', :query)" in sql
    assert "ts_rank_cd(e.search_vector, q.query)" in sql
    # Vectors are compared only within the configured model/version.
    assert "e.embedding_model = :model" in sql and "e.embedding_version = :model_version" in sql
    assert "e.embedding <=> CAST(:embedding AS vector)" in sql
    assert "ranked.distance <= :max_distance" in sql
    assert "LIMIT :budget" in sql
    assert "ANY(:document_ids)" not in sql


def test_sql_without_vector_is_lexical_only_and_document_filter_is_bound():
    sql = normalized(retrieval.build_sql(with_vector=False, with_documents=True))
    assert ":embedding" not in sql and "WHERE false" in sql
    assert "AND d.id = ANY(:document_ids)" in sql
    assert "d.status = 'uploaded'" in sql and "v.status = 'active'" in sql


def test_params_never_interpolate_user_input():
    workspace, doc = uuid4(), uuid4()
    hostile = "'; DROP TABLE edu.document_chunks; --"
    params = retrieval.build_params(
        workspace,
        hostile,
        8,
        query_vector=[0.0, 1.0],
        model="m",
        model_version="v",
        document_ids=[doc],
        max_distance=0.7,
    )
    assert params == {
        "workspace_id": workspace,
        "query": hostile,
        "budget": 32,
        "embedding": "[0.0,1.0]",
        "model": "m",
        "model_version": "v",
        "max_distance": 0.7,
        "document_ids": [doc],
    }
    for with_vector in (True, False):
        for with_documents in (True, False):
            assert hostile not in retrieval.build_sql(
                with_vector=with_vector, with_documents=with_documents
            )


# ---------------------------------------------------------------- retrieve() with a fake session


class FakeAsyncDb:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((normalized(str(statement)), params))
        return SimpleNamespace(all=lambda: self.rows)


def scope(workspace_id=None):
    return SimpleNamespace(workspace=SimpleNamespace(id=workspace_id or uuid4()))


def row(**overrides):
    values = dict(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        page_no=2,
        section_path="Bài 1",
        text="Đạo hàm của hằng số bằng 0.",
        text_sha256=hashlib.sha256(b"t").digest(),
        lexical_rank=None,
        semantic_rank=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


async def test_retrieve_runs_one_scoped_statement_and_fuses():
    current = scope()
    best, other = row(lexical_rank=1, semantic_rank=1), row(semantic_rank=2)
    db = FakeAsyncDb([other, best])
    results = await retrieval.retrieve(
        db, current, "  Đạo hàm  ", k=2, query_vector=[0.1, 0.2], model="m", model_version="v"
    )
    assert [r.chunk_id for r in results] == [best.chunk_id, other.chunk_id]
    assert results[0].sources == ("lexical", "semantic")
    ((sql, params),) = db.calls
    assert params["workspace_id"] == current.workspace.id and params["query"] == "Đạo hàm"
    assert "e.embedding <=> CAST(:embedding AS vector)" in sql


async def test_retrieve_without_model_is_lexical_only():
    db = FakeAsyncDb()
    assert await retrieval.retrieve(db, scope(), "Đạo hàm", query_vector=[0.1]) == []
    ((sql, params),) = db.calls
    assert "embedding" not in params and "WHERE false" in sql


async def test_retrieve_abstains_without_touching_the_database():
    db = FakeAsyncDb([row(lexical_rank=1)])
    assert await retrieval.retrieve(db, scope(), "?!…") == []
    assert await retrieval.retrieve(db, scope(), "Đạo hàm", document_ids=[]) == []
    assert db.calls == []


async def test_retrieve_empty_result_is_an_abstention_not_a_fallback():
    db = FakeAsyncDb([])
    assert await retrieval.retrieve(db, scope(), "Tích phân", k=5) == []
    assert len(db.calls) == 1  # no second, wider query


async def test_document_filter_is_passed_as_parameter():
    doc = uuid4()
    db = FakeAsyncDb([])
    await retrieval.retrieve(db, scope(), "Mệnh đề", document_ids=[doc])
    ((sql, params),) = db.calls
    assert params["document_ids"] == [doc] and "d.id = ANY(:document_ids)" in sql


async def test_k_is_bounded_in_service():
    with pytest.raises(retrieval.RetrievalRejected):
        await retrieval.retrieve(FakeAsyncDb(), scope(), "Mệnh đề", k=50)
