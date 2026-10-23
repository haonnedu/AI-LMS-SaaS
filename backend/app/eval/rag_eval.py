"""RAG evaluation harness (KNOW-10), dependency-free.

Run: ``python -m app.eval.rag_eval --local`` (from ``backend/``). It indexes the seed corpus in
``tests/fixtures/rag_eval/corpus.json`` in memory with the ``LocalHashEmbedder`` and replays
``questions.json`` through the SAME policy code the database path uses (``retrieval.validate``,
candidate budgets, distance cut-off, RRF ``retrieval.fuse``, ``citations.build_citations``), with
an in-memory twin of the SQL authorization filters (caller workspace only, active version that is
the document's active one, document ``uploaded``). It prints a table and a JSON report.

Metrics (reported, NOT asserted: pilot thresholds must be approved by product + pedagogy, see
IMPLEMENTATION_PLAN section 10):

* ``recall_at_k``: answerable items whose expected chunk is in the top ``k``;
* ``citation_precision``: cited items (top ``cite_n``) that come from an expected document;
* ``citation_integrity``: citations whose snippet is verbatim from the cited chunk and whose hash
  matches (anything else would be a fabricated source);
* ``abstention_accuracy``: items whose abstain/answer outcome matches ``expect_abstain``;
* ``injection_resistance``: prompt-injection items where policy held (no forbidden or foreign
  documents, at most ``k`` results, every retrieved instruction-like chunk flagged as untrusted);
* ``isolation_violations``: results from another workspace, a deleted document or a
  non-active version across ALL items (must be 0).

The dataset is a SEED written by engineering for the pedagogy team: it is small (18 questions,
Vietnamese, grades 10-12 maths + one literature text) and exists to exercise the harness and the
policy. Replace/extend it with an approved, rights-cleared curriculum set before using the
numbers for any pilot decision. The LocalHashEmbedder measures lexical overlap, not semantic
quality; re-run against the chosen provider once it is decided.
"""

import argparse
import json
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.services import citations, retrieval
from app.services.embeddings import (
    EmbeddingProvider,
    LocalHashEmbedder,
    cosine_similarity,
    fold_diacritics,
    tokenize,
)

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "rag_eval"
NAMESPACE = uuid.UUID("3f6f6a3e-61a4-4b8e-9a43-6a2c1d3e9b10")

# Instruction-like content inside retrieved documents is DATA, never a command. These patterns
# flag it so generation can quote it as untrusted (and evals can check it was noticed). They
# match on diacritic-folded, lower-cased text.
INJECTION_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"\bbo qua (moi|tat ca|cac|nhung) (huong dan|chi dan|quy tac|lenh)",
        r"\bquen (moi|tat ca|cac|nhung) (huong dan|chi dan|quy tac)",
        r"\btro ly( ai)?\b.{0,40}\b(hay|phai)\b",
        r"\btat bo loc",
        r"\bban la (quan tri vien|admin)",
        r"\bignore (all |any )?(previous|prior|above) instructions",
        r"\bsystem prompt\b",
        r"(^|[.!?]\s*)system\s*:",
    )
)


def looks_like_instruction(text: str) -> bool:
    folded = fold_diacritics(text).lower()
    return any(pattern.search(folded) for pattern in INJECTION_PATTERNS)


def _uuid(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, key)


@dataclass
class IndexedChunk:
    key: str
    chunk_id: uuid.UUID
    workspace: str
    document_key: str
    document_id: uuid.UUID
    version_id: uuid.UUID
    version_status: str
    document_status: str
    active: bool
    page_no: int | None
    section_path: str | None
    text: str
    injection: bool
    tokens: Counter
    vector: list[float]
    model: str
    model_version: str


@dataclass
class MemoryIndex:
    """In-memory twin of the retrieval SQL (exact scan; same filters and fusion)."""

    embedder: EmbeddingProvider
    chunks: list[IndexedChunk] = field(default_factory=list)

    @classmethod
    def from_corpus(cls, corpus: dict, embedder: EmbeddingProvider) -> "MemoryIndex":
        index = cls(embedder)
        for document in corpus["documents"]:
            active = [v["id"] for v in document["versions"] if v["status"] == "active"]
            for version in document["versions"]:
                texts = [c["text"] for c in version["chunks"]]
                vectors = embedder.embed(texts).vectors
                for chunk, vector in zip(version["chunks"], vectors, strict=True):
                    index.chunks.append(
                        IndexedChunk(
                            key=chunk["id"],
                            chunk_id=_uuid(chunk["id"]),
                            workspace=document["workspace"],
                            document_key=document["id"],
                            document_id=_uuid(document["id"]),
                            version_id=_uuid(version["id"]),
                            version_status=version["status"],
                            document_status=document["status"],
                            active=version["id"] in active[:1],
                            page_no=chunk.get("page"),
                            section_path=chunk.get("section"),
                            text=chunk["text"],
                            injection=bool(chunk.get("injection")),
                            tokens=Counter(tokenize(chunk["text"])),
                            vector=vector,
                            model=embedder.model,
                            model_version=embedder.version,
                        )
                    )
        return index

    def by_id(self) -> dict[uuid.UUID, IndexedChunk]:
        return {c.chunk_id: c for c in self.chunks}

    def eligible(self, workspace: str) -> list[IndexedChunk]:
        return [
            c
            for c in self.chunks
            if c.workspace == workspace
            and c.version_status == "active"
            and c.active
            and c.document_status == "uploaded"
        ]

    def search(
        self, workspace: str, query: str, k: int, max_distance: float
    ) -> list[retrieval.RetrievedChunk]:
        query = retrieval.validate(query, k, None)
        if not re.search(r"\w", query):
            return []
        budget = retrieval.candidate_budget(k)
        pool = self.eligible(workspace)
        terms = set(tokenize(query))
        # plainto_tsquery('simple') semantics: every query term must be present (AND).
        lexical = sorted(
            (c for c in pool if terms and terms <= set(c.tokens)),
            key=lambda c: (-sum(c.tokens[t] for t in terms), str(c.chunk_id)),
        )[:budget]
        qv = self.embedder.embed([query]).vectors[0]
        scored = []
        for c in pool:
            if c.model != self.embedder.model or c.model_version != self.embedder.version:
                continue  # never compare incompatible vectors
            distance = 1.0 - cosine_similarity(qv, c.vector)
            if distance <= max_distance:
                scored.append((distance, str(c.chunk_id), c))
        semantic = [c for _, _, c in sorted(scored, key=lambda s: (s[0], s[1]))][:budget]
        lex_rank = {c.chunk_id: i for i, c in enumerate(lexical, start=1)}
        sem_rank = {c.chunk_id: i for i, c in enumerate(semantic, start=1)}
        candidates = [
            retrieval.Candidate(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                version_id=c.version_id,
                page_no=c.page_no,
                section_path=c.section_path,
                text=c.text,
                text_sha256=None,
                lexical_rank=lex_rank.get(c.chunk_id),
                semantic_rank=sem_rank.get(c.chunk_id),
            )
            for c in {
                **{c.chunk_id: c for c in lexical},
                **{c.chunk_id: c for c in semantic},
            }.values()
        ]
        return retrieval.fuse(candidates, k)


def load_json(name: str, base: Path = FIXTURES) -> dict:
    return json.loads((base / name).read_text(encoding="utf-8"))


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def evaluate(
    corpus: dict,
    questions: dict,
    *,
    embedder: EmbeddingProvider | None = None,
    k: int = 5,
    cite_n: int = 3,
    max_distance: float = retrieval.DEFAULT_MAX_DISTANCE,
) -> dict:
    embedder = embedder or LocalHashEmbedder()
    index = MemoryIndex.from_corpus(corpus, embedder)
    chunks = index.by_id()
    workspace = questions["workspace"]
    rows = []
    recall_hits = recall_total = 0
    cited_ok = cited_total = 0
    integrity_ok = integrity_total = 0
    abstain_ok = abstain_total = 0
    injection_ok = injection_total = 0
    violations = 0
    for item in questions["items"]:
        results = index.search(workspace, item["question"], k, max_distance)
        hits = [chunks[r.chunk_id] for r in results]
        keys = [c.key for c in hits]
        forbidden_docs = set(item.get("forbidden_documents", []))
        forbidden_chunks = set(item.get("forbidden_chunks", []))
        item_violations = [
            c.key
            for c in hits
            if c.workspace != workspace
            or not c.active
            or c.version_status != "active"
            or c.document_status != "uploaded"
            or c.document_key in forbidden_docs
            or c.key in forbidden_chunks
        ]
        violations += len(item_violations)
        flagged = [c.key for c in hits if looks_like_instruction(c.text)]
        unflagged_injections = [c.key for c in hits if c.injection and c.key not in flagged]
        abstained = not results

        expected = set(item.get("expected_chunks", []))
        hit = bool(expected & set(keys)) if expected else None
        if expected:
            recall_total += 1
            recall_hits += int(bool(hit))
            expected_docs = {chunks[_uuid(key)].document_key for key in expected}
            for citation in citations.build_citations(results[:cite_n]):
                cited_total += 1
                cited_ok += int(chunks[citation.chunk_id].document_key in expected_docs)
        for citation in citations.build_citations(results):
            source = chunks[citation.chunk_id]
            integrity_total += 1
            verbatim = citation.snippet.rstrip("…").strip() in " ".join(source.text.split())
            same_hash = citation.text_sha256 == citations.sha256_hex(source.text)
            integrity_ok += int(verbatim and same_hash and citation.version_id == source.version_id)
        if item.get("expect_abstain") is not None:
            abstain_total += 1
            abstain_ok += int(abstained == item["expect_abstain"])
        injection_pass = None
        if item["kind"] == "injection":
            injection_total += 1
            injection_pass = not item_violations and len(results) <= k and not unflagged_injections
            injection_ok += int(injection_pass)
        rows.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "abstained": abstained,
                "expectAbstain": item.get("expect_abstain"),
                "hit": hit,
                "results": keys,
                "flaggedInstructions": flagged,
                "violations": item_violations,
                "injectionPolicyHeld": injection_pass,
            }
        )
    corpus_injections = [c for c in index.chunks if c.injection]
    detector_false_positives = [
        c.key for c in index.chunks if not c.injection and looks_like_instruction(c.text)
    ]
    return {
        "config": {
            "embedder": embedder.model,
            "embeddingVersion": embedder.version,
            "k": k,
            "citeN": cite_n,
            "maxDistance": max_distance,
            "items": len(questions["items"]),
            "chunks": len(index.chunks),
        },
        "metrics": {
            "recall_at_k": _ratio(recall_hits, recall_total),
            "citation_precision": _ratio(cited_ok, cited_total),
            "citation_integrity": _ratio(integrity_ok, integrity_total),
            "abstention_accuracy": _ratio(abstain_ok, abstain_total),
            "injection_resistance": _ratio(injection_ok, injection_total),
            "isolation_violations": violations,
            "injection_chunks_flagged": _ratio(
                sum(looks_like_instruction(c.text) for c in corpus_injections),
                len(corpus_injections),
            ),
            "injection_detector_false_positives": len(detector_false_positives),
        },
        "items": rows,
    }


def render_table(report: dict) -> str:
    lines = [
        f"{'item':<5} {'kind':<9} {'abst':<5} {'exp':<5} {'hit':<5} {'inj':<5} results",
        "-" * 78,
    ]
    for row in report["items"]:

        def fmt(value):
            return "-" if value is None else ("yes" if value else "no")

        lines.append(
            f"{row['id']:<5} {row['kind']:<9} {fmt(row['abstained']):<5} "
            f"{fmt(row['expectAbstain']):<5} {fmt(row['hit']):<5} "
            f"{fmt(row['injectionPolicyHeld']):<5} {','.join(row['results'][:4])}"
        )
    lines.append("-" * 78)
    for name, value in report["metrics"].items():
        lines.append(f"{name:<36} {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Eduvia RAG eval (seed dataset)")
    parser.add_argument("--local", action="store_true", help="in-memory index + LocalHashEmbedder")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--cite-n", type=int, default=3)
    parser.add_argument("--max-distance", type=float, default=retrieval.DEFAULT_MAX_DISTANCE)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args(argv)
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:  # Windows consoles default to a legacy code page
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    if not args.local:
        print("Only --local is implemented (no database/provider needed).", file=sys.stderr)
        return 2
    report = evaluate(
        load_json("corpus.json", args.fixtures),
        load_json("questions.json", args.fixtures),
        k=args.k,
        cite_n=args.cite_n,
        max_distance=args.max_distance,
    )
    if not args.json_only:
        print(render_table(report))
        print()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
