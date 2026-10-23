"""AI draft generation (AUTHR-03): lesson plans, study guides and single-choice questions.

API side (``enqueue_generation``, async, inside ``workspace_transaction``): validate the request,
check the curriculum unit / target content item, enqueue a ``content.generate`` or
``questions.generate`` background job and record a ``generation_jobs`` row (``pending``).

Worker side (``run_generation``, sync session with the job actor's RLS context):

1. retrieve sources with the authorized ``services.retrieval.retrieve`` (k <= 8) inside the job's
   workspace context (re-authorized at execution time, never widened);
2. build the prompt: a CONSTANT per-purpose system prompt (``app/prompts``) that declares source
   text untrusted, and a user message where teacher parameters live in ``<request>`` and only
   chunk text lives in ``<source id="[n]">`` (angle brackets escaped so a chunk can never close
   its tag; no file names, no student data);
3. enforce the token budget (drop lowest-ranked sources first, refuse if still too large) and
   reserve usage units before calling the provider;
4. validate the JSON output with a strict pure-Python schema check, map ``[n]`` citations back
   to the retrieved chunks (citations outside the source set are stripped and the draft is
   marked ``invalid`` with a reason);
5. persist: a NEW ``draft`` content revision (never approved/published) with
   ``generation_job_id`` set, or ``draft`` questions with keys through ``question_bank``; plus
   ``generation_sources`` rows and token usage.

Provider outages fail the job with ``provider_unavailable`` (after the adapter's bounded
retries); manual authoring never depends on this module. Prompts, source text and outputs are
never logged.
"""

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.authoring import COGNITIVE_LEVELS, ContentItem, ContentRevision
from app.models.generation import GenerationJob, GenerationSource
from app.models.jobs import UsageEvent, WorkspaceQuota
from app.services import content as content_service
from app.services import embeddings, llm, retrieval, usage
from app.services import jobs as job_service
from app.services import question_bank as bank
from app.services.authoring_common import (
    AuthoringError,
    Invalid,
    NotFound,
    Scope,
    parse_uuid,
    utcnow,
)
from app.services.chunking import estimate_tokens

logger = logging.getLogger("eduvia.generation")

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
PURPOSES = ("lesson_plan", "study_guide", "questions")
PROMPT_VERSIONS = {
    "lesson_plan": "lesson_plan_v1",
    "study_guide": "study_guide_v1",
    "questions": "questions_v1",
}
JOB_KINDS = {"lesson_plan": "content.generate", "study_guide": "content.generate"}
QUESTIONS_KIND = "questions.generate"
KINDS = frozenset({"content.generate", QUESTIONS_KIND})
UNIT_TYPE = "llm_request"
MAX_SOURCES = 8
MAX_OBJECTIVES = 20
MAX_OBJECTIVE_CHARS = 500
MAX_SUBJECT_CHARS = 100
MAX_TITLE_CHARS = 300
MAX_DOCUMENTS = 50
MAX_QUESTIONS = 20
DEFAULT_QUESTIONS = 5
MAX_REASONS = 20
DEFAULT_TITLES = {
    "lesson_plan": "Giáo án (bản nháp AI)",
    "study_guide": "Đề cương ôn tập (bản nháp AI)",
}
PURPOSE_LABELS = {
    "lesson_plan": "Soạn giáo án",
    "study_guide": "Soạn đề cương ôn tập",
    "questions": "Soạn câu hỏi trắc nghiệm một lựa chọn",
}


class GenerationFailed(Exception):
    """Permanent, client-safe failure code. ``metered`` = the provider was actually called."""

    def __init__(self, code: str, *, metered: bool = False, request_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.metered = metered
        self.request_id = request_id


# ---- Request validation (pure) --------------------------------------------------------------


def _invalid(code: str, message: str) -> Invalid:
    return Invalid(code, message)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def normalize_input(raw: Any) -> dict[str, Any]:
    """Validate the client request and return the canonical (camelCase) job input."""
    if not isinstance(raw, Mapping):
        raise _invalid("invalid_generation_input", "Yêu cầu tạo bản nháp không hợp lệ.")
    allowed = {
        "purpose",
        "contentItemId",
        "curriculumUnitId",
        "grade",
        "subject",
        "objectives",
        "durationMinutes",
        "documentIds",
        "count",
        "title",
        "cognitiveLevel",
    }
    extra = set(raw) - allowed
    if extra:
        raise _invalid("invalid_generation_input", "Yêu cầu có trường không được hỗ trợ.")
    purpose = raw.get("purpose")
    if purpose not in PURPOSES:
        raise _invalid("invalid_purpose", "Loại bản nháp không được hỗ trợ.")
    unit = parse_uuid(raw.get("curriculumUnitId"))
    if unit is None:
        raise _invalid("invalid_curriculum_unit", "Cần chọn đơn vị chương trình.")
    grade = _int(raw.get("grade"))
    if grade is None or not 1 <= grade <= 12:
        raise _invalid("invalid_grade", "Khối lớp phải từ 1 đến 12.")
    subject = raw.get("subject")
    if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= MAX_SUBJECT_CHARS:
        raise _invalid("invalid_subject", "Môn học không hợp lệ.")
    objectives = raw.get("objectives")
    if (
        not isinstance(objectives, list)
        or not 1 <= len(objectives) <= MAX_OBJECTIVES
        or not all(
            isinstance(o, str) and 1 <= len(o.strip()) <= MAX_OBJECTIVE_CHARS for o in objectives
        )
    ):
        raise _invalid("invalid_objectives", "Cần từ 1 đến 20 mục tiêu, mỗi mục tối đa 500 ký tự.")
    result: dict[str, Any] = {
        "purpose": purpose,
        "curriculumUnitId": str(unit),
        "grade": grade,
        "subject": subject.strip(),
        "objectives": [o.strip() for o in objectives],
    }
    duration = raw.get("durationMinutes")
    if duration is not None:
        if _int(duration) is None or not 1 <= duration <= 600:
            raise _invalid("invalid_duration", "Thời lượng phải từ 1 đến 600 phút.")
        result["durationMinutes"] = duration
    documents = raw.get("documentIds")
    if documents is not None:
        ids = [parse_uuid(d) for d in documents] if isinstance(documents, list) else [None]
        if any(d is None for d in ids) or len(ids) > MAX_DOCUMENTS:
            raise _invalid("invalid_documents", "Danh sách tài liệu không hợp lệ (tối đa 50).")
        result["documentIds"] = [str(d) for d in dict.fromkeys(ids)]
    if purpose == "questions":
        if raw.get("contentItemId") is not None or raw.get("title") is not None:
            raise _invalid("invalid_generation_input", "Câu hỏi không gắn với giáo án/đề cương.")
        count = raw.get("count", DEFAULT_QUESTIONS)
        if _int(count) is None or not 1 <= count <= MAX_QUESTIONS:
            raise _invalid("invalid_count", f"Số câu hỏi phải từ 1 đến {MAX_QUESTIONS}.")
        result["count"] = count
        level = raw.get("cognitiveLevel")
        if level is not None:
            if level not in COGNITIVE_LEVELS:
                raise _invalid("invalid_cognitive_level", "Mức độ nhận thức không hợp lệ.")
            result["cognitiveLevel"] = level
    else:
        if raw.get("count") is not None or raw.get("cognitiveLevel") is not None:
            raise _invalid("invalid_generation_input", "Số câu hỏi chỉ dùng khi soạn câu hỏi.")
        item = raw.get("contentItemId")
        if item is not None:
            item_id = parse_uuid(item)
            if item_id is None:
                raise _invalid("invalid_content_item", "Mã nội dung không hợp lệ.")
            result["contentItemId"] = str(item_id)
        title = raw.get("title")
        if title is not None:
            if not isinstance(title, str) or not 1 <= len(title.strip()) <= MAX_TITLE_CHARS:
                raise _invalid("invalid_title", "Tiêu đề không hợp lệ.")
            result["title"] = title.strip()
    return result


def job_kind(purpose: str) -> str:
    return JOB_KINDS.get(purpose, QUESTIONS_KIND)


# ---- Prompt building (pure) -----------------------------------------------------------------


@dataclass(frozen=True)
class PromptSource:
    label: str
    chunk_id: UUID
    text: str
    text_sha256: bytes
    rank: int


@lru_cache
def system_prompt(purpose: str) -> str:
    """Constant per purpose: nothing request- or source-specific ever reaches it."""
    return (PROMPTS_DIR / f"{PROMPT_VERSIONS[purpose]}.txt").read_text(encoding="utf-8").strip()


def escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def prompt_sources(chunks: Sequence[Any], limit: int = MAX_SOURCES) -> list[PromptSource]:
    out: list[PromptSource] = []
    seen: set[UUID] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen or len(out) >= limit:
            continue
        seen.add(chunk.chunk_id)
        digest = getattr(chunk, "text_sha256", None)
        out.append(
            PromptSource(
                label=f"[{len(out) + 1}]",
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                text_sha256=bytes(digest)
                if digest
                else hashlib.sha256(chunk.text.encode("utf-8")).digest(),
                rank=len(out) + 1,
            )
        )
    return out


def build_user_message(request: Mapping[str, Any], sources: Sequence[PromptSource]) -> str:
    purpose = request["purpose"]
    lines = [
        "<request>",
        f"Nhiệm vụ: {PURPOSE_LABELS[purpose]}",
        f"Môn học: {escape(request['subject'])}",
        f"Khối lớp: {request['grade']}",
    ]
    if request.get("durationMinutes"):
        lines.append(f"Thời lượng: {request['durationMinutes']} phút")
    if purpose == "questions":
        lines.append(f"Số câu hỏi: {request['count']}")
        if request.get("cognitiveLevel"):
            lines.append(f"Mức độ nhận thức: {request['cognitiveLevel']}")
    lines.append("Mục tiêu:")
    lines.extend(f"- {escape(objective)}" for objective in request["objectives"])
    lines.append("</request>")
    lines.append("<sources>")
    if not sources:
        lines.append("(Không có nguồn phù hợp; không được tạo trích dẫn.)")
    for source in sources:
        lines.append(f'<source id="{source.label}">{escape(source.text)}</source>')
    lines.append("</sources>")
    return "\n".join(lines)


def tokens(text_value: str) -> int:
    """Conservative estimate: word-based, floored by ~4 characters per token."""
    return max(estimate_tokens(text_value), len(text_value) // 4)


def estimate_prompt_tokens(system: str, user: str) -> int:
    return tokens(system) + tokens(user)


def fit_budget(
    request: Mapping[str, Any], sources: Sequence[PromptSource], max_input_tokens: int
) -> tuple[list[PromptSource], str, int]:
    """Drop lowest-ranked sources until the prompt fits; refuse if it never does."""
    system = system_prompt(request["purpose"])
    kept = list(sources)
    while True:
        user = build_user_message(request, kept)
        estimate = estimate_prompt_tokens(system, user)
        if estimate <= max_input_tokens:
            return kept, user, estimate
        if not kept:
            raise GenerationFailed("budget_exceeded")
        kept.pop()


def retrieval_query(request: Mapping[str, Any]) -> str:
    parts = [*request["objectives"], request["subject"], f"lớp {request['grade']}"]
    return " ".join(parts)[: retrieval.MAX_QUERY_CHARS]


# ---- Output schemas and validation (pure) ---------------------------------------------------

_CITATION = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label"],
    "properties": {"label": {"type": "string"}},
}


def content_schema(purpose: str) -> dict[str, Any]:
    block = {
        "type": "object",
        "additionalProperties": False,
        "required": ["type", "text", "citations"],
        "properties": {
            "type": {"type": "string", "enum": sorted(content_service.BLOCK_TYPES)},
            "text": {"type": "string"},
            "citations": {"type": "array", "items": _CITATION},
        },
    }
    section = {
        "type": "object",
        "additionalProperties": False,
        "required": ["heading", "blocks"],
        "properties": {
            "heading": {"type": "string"},
            "blocks": {"type": "array", "items": block},
        },
    }
    return {
        "title": purpose,
        "type": "object",
        "additionalProperties": False,
        "required": ["sections"],
        "properties": {"sections": {"type": "array", "items": section}},
    }


QUESTIONS_SCHEMA: dict[str, Any] = {
    "title": "questions",
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "stem",
                    "choices",
                    "correctKey",
                    "explanation",
                    "cognitiveLevel",
                    "citations",
                ],
                "properties": {
                    "stem": {"type": "string"},
                    "choices": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["key", "text"],
                            "properties": {
                                "key": {"type": "string", "enum": ["A", "B", "C", "D"]},
                                "text": {"type": "string"},
                            },
                        },
                    },
                    "correctKey": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "explanation": {"type": "string"},
                    "cognitiveLevel": {"type": "string", "enum": list(COGNITIVE_LEVELS)},
                    "citations": {"type": "array", "items": _CITATION},
                },
            },
        }
    },
}


def output_schema(purpose: str) -> dict[str, Any]:
    return QUESTIONS_SCHEMA if purpose == "questions" else content_schema(purpose)


_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
}


def check_schema(value: Any, schema: Mapping[str, Any], path: str = "$") -> list[str]:
    """Strict subset of JSON Schema: type, enum, properties, required, additionalProperties,
    items. Returns human-readable error paths (empty list when valid)."""
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        python_type = _TYPES[expected]
        if not isinstance(value, python_type) or (
            expected in ("integer", "number") and isinstance(value, bool)
        ):
            return [f"{path}: cần kiểu {expected}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: giá trị không hợp lệ")
    if expected == "object":
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: thiếu trường bắt buộc")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}.{key}: trường không được phép")
        for key, sub in properties.items():
            if key in value:
                errors.extend(check_schema(value[key], sub, f"{path}.{key}"))
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(check_schema(item, schema["items"], f"{path}[{index}]"))
            if len(errors) > MAX_REASONS:
                break
    return errors[:MAX_REASONS]


@dataclass
class ValidatedOutput:
    status: str  # valid | invalid
    reasons: list[str] = field(default_factory=list)
    body: dict[str, Any] | None = None
    questions: list[bank.QuestionInput] = field(default_factory=list)


def _map_citations(citations: list, label_map: Mapping[str, UUID], reasons: list[str], path: str):
    mapped = []
    for citation in citations:
        label = citation.get("label") if isinstance(citation, Mapping) else None
        chunk = label_map.get(label) if isinstance(label, str) else None
        if chunk is None:
            reasons.append(f"citation_not_in_sources: {path} ({str(label)[:20]})")
            continue
        entry = {"chunkId": str(chunk), "label": label}
        if entry not in mapped:
            mapped.append(entry)
    return mapped


def validate_content_output(
    parsed: Any, purpose: str, sources: Sequence[PromptSource]
) -> ValidatedOutput:
    errors = check_schema(parsed, content_schema(purpose))
    if errors:
        return ValidatedOutput("invalid", errors)
    label_map = {source.label: source.chunk_id for source in sources}
    reasons: list[str] = []
    body = {
        "sections": [
            {
                "heading": section["heading"],
                "blocks": [
                    {
                        "type": block["type"],
                        "text": block["text"],
                        "citations": _map_citations(
                            block["citations"],
                            label_map,
                            reasons,
                            f"sections[{s}].blocks[{b}]",
                        ),
                    }
                    for b, block in enumerate(section["blocks"])
                ],
            }
            for s, section in enumerate(parsed["sections"])
        ]
    }
    try:
        body = content_service.validate_body(body)
    except Invalid as exc:
        return ValidatedOutput("invalid", [exc.message])
    if not body["sections"]:
        return ValidatedOutput("invalid", ["empty_draft"])
    return ValidatedOutput("invalid" if reasons else "valid", reasons[:MAX_REASONS], body=body)


def validate_questions_output(
    parsed: Any, request: Mapping[str, Any], sources: Sequence[PromptSource]
) -> ValidatedOutput:
    errors = check_schema(parsed, QUESTIONS_SCHEMA)
    if errors:
        return ValidatedOutput("invalid", errors)
    label_map = {source.label: source.chunk_id for source in sources}
    reasons: list[str] = []
    accepted: list[bank.QuestionInput] = []
    unit = UUID(request["curriculumUnitId"])
    for index, item in enumerate(parsed["questions"][: request["count"]]):
        path = f"questions[{index}]"
        keys = [choice["key"] for choice in item["choices"]]
        if keys != ["A", "B", "C", "D"]:
            reasons.append(f"{path}: cần đúng 4 phương án A, B, C, D")
            continue
        if item["correctKey"] not in keys:
            reasons.append(f"{path}: đáp án đúng phải là một phương án")
            continue
        citations = _map_citations(item["citations"], label_map, reasons, path)
        try:
            question = bank.validate_question(
                bank.QuestionInput(
                    stem=item["stem"],
                    choices=[{"key": c["key"], "text": c["text"]} for c in item["choices"]],
                    cognitive_level=request.get("cognitiveLevel") or item["cognitiveLevel"],
                    correct_key=item["correctKey"],
                    explanation=item["explanation"] or None,
                    curriculum_unit_id=unit,
                    source_citations=tuple(citations),
                )
            )
        except Invalid as exc:
            reasons.append(f"{path}: {exc.message}")
            continue
        accepted.append(question)
    if len(parsed["questions"]) > request["count"]:
        reasons.append("too_many_questions")
    if not accepted:
        reasons.append("no_valid_questions")
    return ValidatedOutput(
        "invalid" if reasons else "valid", reasons[:MAX_REASONS], questions=accepted
    )


# ---- Async bridge: reuse async services with the worker's sync session -----------------------


class AsyncBridge:
    """Minimal AsyncSession facade over a sync ``Session``. Every awaited call completes
    immediately, so ``run_sync`` can drive the coroutine without an event loop."""

    def __init__(self, db: Session):
        self._db = db

    def add(self, obj) -> None:
        self._db.add(obj)

    async def flush(self) -> None:
        self._db.flush()

    async def execute(self, *args, **kwargs):
        return self._db.execute(*args, **kwargs)

    async def scalar(self, *args, **kwargs):
        return self._db.scalar(*args, **kwargs)

    async def scalars(self, *args, **kwargs):
        return self._db.scalars(*args, **kwargs)


def run_sync(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as stop:
        return stop.value
    coroutine.close()
    raise RuntimeError("bridged coroutine suspended unexpectedly")


# ---- API side -------------------------------------------------------------------------------


async def enqueue_generation(
    db, scope: Scope, raw: Any, *, settings, idempotency_key: str
) -> tuple[GenerationJob, Any, bool]:
    request = normalize_input(raw)
    await content_service.ensure_unit(db, UUID(request["curriculumUnitId"]))
    if request.get("contentItemId"):
        item = await content_service.load_item(
            db, scope.workspace.id, UUID(request["contentItemId"])
        )
        if item.kind != request["purpose"]:
            raise Invalid("content_kind_mismatch", "Loại nội dung không khớp với yêu cầu.")
        if item.status == "archived":
            raise Invalid("content_archived", "Nội dung đã được lưu trữ.")
    kind = job_kind(request["purpose"])
    job, created = await job_service.enqueue_job(db, scope, kind, request, idempotency_key)
    if not created:
        existing = await db.scalar(
            select(GenerationJob).where(
                GenerationJob.workspace_id == scope.workspace.id,
                GenerationJob.background_job_id == job.id,
            )
        )
        if existing is None:
            raise NotFound("generation_job_not_found", "Không tìm thấy yêu cầu tạo bản nháp.")
        return existing, job, False
    generation = GenerationJob(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        background_job_id=job.id,
        requested_by_user_id=scope.user.id,
        purpose=request["purpose"],
        input=request,
        prompt_version=PROMPT_VERSIONS[request["purpose"]],
        provider=settings.llm_provider,
        model=settings.llm_model if settings.llm_provider != "fake" else "fake-drafter-v1",
        validation_status="pending",
        created_at=utcnow(),
    )
    db.add(generation)
    await db.flush()
    return generation, job, True


async def load_generation(db, workspace_id: UUID, generation_id: UUID) -> GenerationJob:
    generation = await db.scalar(
        select(GenerationJob).where(
            GenerationJob.id == generation_id, GenerationJob.workspace_id == workspace_id
        )
    )
    if generation is None:
        raise NotFound("generation_job_not_found", "Không tìm thấy yêu cầu tạo bản nháp.")
    return generation


# ---- Worker side ----------------------------------------------------------------------------


def reserve_units(
    db: Session, workspace_id: UUID, units: int, *, job_id: UUID, now: datetime
) -> bool:
    """Lock the quota row, check the monthly cap and append a reservation (sync twin)."""
    quota = db.scalar(
        select(WorkspaceQuota).where(WorkspaceQuota.workspace_id == workspace_id).with_for_update()
    )
    cap = quota.month_cap_units if quota is not None else 0
    used = db.scalar(
        select(func.coalesce(func.sum(UsageEvent.units), 0)).where(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.created_at >= usage.month_start(now),
        )
    )
    if not usage.within_cap(int(used or 0), cap, units):
        return False
    record_units(db, workspace_id, units, job_id=job_id, now=now)
    return True


def record_units(db: Session, workspace_id: UUID, units: int, *, job_id: UUID, now) -> None:
    db.add(
        UsageEvent(
            id=uuid4(),
            workspace_id=workspace_id,
            job_id=job_id,
            kind="reservation",
            units=units,
            unit_type=UNIT_TYPE,
            created_at=now,
        )
    )
    db.flush()


def default_retriever(embedder: embeddings.EmbeddingProvider | None, max_distance: float):
    """Authorized retrieval through ``services.retrieval.retrieve`` on the sync session."""

    def retrieve(db: Session, scope, query: str, document_ids, k: int):
        vector = None
        if embedder is not None:
            try:
                result = embedder.embed([query])
                if result.vectors and len(result.vectors[0]) == embedder.dimension:
                    vector = result.vectors[0]
            except embeddings.EmbeddingError:
                vector = None  # degrade to lexical-only, never to a wider scope
        return run_sync(
            retrieval.retrieve(
                AsyncBridge(db),
                scope,
                query,
                document_ids=document_ids,
                k=k,
                query_vector=vector,
                model=embedder.model if vector is not None else None,
                model_version=embedder.version if vector is not None else None,
                max_distance=max_distance,
            )
        )

    return retrieve


def _scope(job) -> SimpleNamespace:
    return SimpleNamespace(
        user=SimpleNamespace(id=job.requested_by_user_id),
        workspace=SimpleNamespace(id=job.workspace_id),
        role="teacher",
    )


def _load_generation(db: Session, job, *, lock: bool) -> GenerationJob | None:
    query = select(GenerationJob).where(
        GenerationJob.workspace_id == job.workspace_id,
        GenerationJob.background_job_id == job.id,
    )
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def summary(generation: GenerationJob, **extra) -> dict[str, Any]:
    output = generation.output or {}
    return {
        "generationJobId": str(generation.id),
        "validationStatus": generation.validation_status,
        "reasons": list(output.get("reasons", []))[:MAX_REASONS],
        **extra,
    }


def insert_draft_revision(
    db: Session,
    *,
    workspace_id: UUID,
    user_id: UUID,
    request: Mapping[str, Any],
    body: dict[str, Any],
    background_job_id: UUID,
    now: datetime,
) -> tuple[ContentItem, ContentRevision]:
    """A new DRAFT revision carrying ``generation_job_id``; never approved or published."""
    item_id = parse_uuid(request.get("contentItemId"))
    previous = None
    if item_id is not None:
        item = db.scalar(
            select(ContentItem)
            .where(
                ContentItem.id == item_id,
                ContentItem.workspace_id == workspace_id,
                ContentItem.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if item is None:
            raise GenerationFailed("content_not_found")
        if item.kind != request["purpose"]:
            raise GenerationFailed("content_kind_mismatch")
        if item.status == "archived":
            raise GenerationFailed("content_archived")
        previous = db.scalar(
            select(ContentRevision).where(
                ContentRevision.workspace_id == workspace_id,
                ContentRevision.content_item_id == item.id,
                ContentRevision.revision_no == item.latest_revision_no,
            )
        )
        number = item.latest_revision_no + 1
    else:
        item = ContentItem(
            id=uuid4(),
            workspace_id=workspace_id,
            kind=request["purpose"],
            title=request.get("title") or DEFAULT_TITLES[request["purpose"]],
            created_by_user_id=user_id,
            status="draft",
            latest_revision_no=0,
            curriculum_unit_id=UUID(request["curriculumUnitId"]),
            created_at=now,
            updated_at=now,
        )
        db.add(item)
        db.flush()
        number = 1
    revision = ContentRevision(
        id=uuid4(),
        workspace_id=workspace_id,
        content_item_id=item.id,
        revision_no=number,
        body=body,
        audience=previous.audience if previous is not None else "teacher",
        status="draft",
        based_on_revision_id=previous.id if previous is not None else None,
        generation_job_id=background_job_id,
        created_by_user_id=user_id,
        body_sha256=content_service.body_sha256(body),
        created_at=now,
        updated_at=now,
    )
    db.add(revision)
    item.latest_revision_no = number
    item.updated_at = now
    db.flush()
    return item, revision


def insert_draft_questions(
    db: Session, scope, questions: Sequence[bank.QuestionInput]
) -> list[UUID]:
    bridge = AsyncBridge(db)
    created: list[UUID] = []
    for data in questions:
        try:
            question, _ = run_sync(bank.create_question(bridge, scope, data))
        except AuthoringError as exc:
            raise GenerationFailed(exc.code) from None
        question.status = "draft"  # AI questions always need teacher review before use
        db.flush()
        created.append(question.id)
    return created


def _parse(text_value: str) -> Any:
    text_value = text_value.strip()
    if text_value.startswith("```"):
        text_value = text_value.strip("`")
        text_value = text_value.removeprefix("json").strip()
    return json.loads(text_value)


def run_generation(
    ctx,
    *,
    provider: llm.LLMProvider,
    retriever=None,
    settings=None,
) -> dict[str, Any]:
    """Worker handler for ``content.generate`` / ``questions.generate``."""
    from app.core.config import get_settings

    settings = settings or get_settings()
    db: Session = ctx.db
    job = ctx.job
    now = ctx.clock()
    generation = _load_generation(db, job, lock=True)
    if generation is None:
        raise GenerationFailed("invalid_job_input")
    if generation.finished_at is not None:
        return summary(generation, replay=True)
    request = generation.input
    scope = _scope(job)

    if retriever is None:
        retriever = default_retriever(
            ctx.embedding_provider(), settings.retrieval_max_cosine_distance
        )
    document_ids = [UUID(d) for d in request["documentIds"]] if "documentIds" in request else None
    try:
        chunks = retriever(db, scope, retrieval_query(request), document_ids, MAX_SOURCES)
    except retrieval.RetrievalRejected:
        chunks = []
    sources = prompt_sources(chunks)
    sources, user_message, _estimate = fit_budget(request, sources, settings.llm_max_input_tokens)

    if not reserve_units(
        db, job.workspace_id, settings.llm_units_per_request, job_id=job.id, now=now
    ):
        raise GenerationFailed("quota_exceeded")
    purpose = request["purpose"]
    schema = output_schema(purpose)
    try:
        result = provider.complete(
            system_prompt(purpose),
            [{"role": "user", "content": user_message}],
            max_tokens=settings.llm_max_output_tokens,
            json_schema=schema,
        )
    except llm.LLMError as exc:
        code = "provider_unavailable" if exc.code == "provider_rate_limited" else exc.code
        raise GenerationFailed(code, metered=True, request_id=exc.request_id) from None

    for source in sources:
        db.add(
            GenerationSource(
                id=uuid4(),
                workspace_id=job.workspace_id,
                generation_job_id=generation.id,
                chunk_id=source.chunk_id,
                citation_label=source.label,
                text_sha256=source.text_sha256,
                rank=source.rank,
            )
        )
    db.flush()

    extra: dict[str, Any] = {}
    try:
        parsed = _parse(result.text)
    except (ValueError, TypeError):
        validated = ValidatedOutput("invalid", ["invalid_json"])
        parsed = None
    else:
        validated = (
            validate_questions_output(parsed, request, sources)
            if purpose == "questions"
            else validate_content_output(parsed, purpose, sources)
        )

    output: dict[str, Any] = {"reasons": validated.reasons}
    if validated.body is not None:
        item, revision = insert_draft_revision(
            db,
            workspace_id=job.workspace_id,
            user_id=job.requested_by_user_id,
            request=request,
            body=validated.body,
            background_job_id=job.id,
            now=now,
        )
        output["draft"] = validated.body
        extra = {"contentItemId": str(item.id), "revisionNo": revision.revision_no}
    elif validated.questions:
        ids = insert_draft_questions(db, scope, validated.questions)
        output["questionIds"] = [str(i) for i in ids]
        extra = {"questionIds": [str(i) for i in ids]}
    elif parsed is not None and len(json.dumps(parsed, ensure_ascii=False)) <= 200_000:
        output["rejected"] = parsed  # kept for review on restricted retention, never published

    generation.provider = getattr(provider, "name", generation.provider)
    generation.model = result.model[:128]
    generation.provider_request_id = result.request_id
    generation.input_tokens = result.input_tokens
    generation.output_tokens = result.output_tokens
    generation.output = output
    generation.validation_status = validated.status
    generation.finished_at = now
    db.flush()
    return summary(generation, sources=len(sources), **extra)


def mark_failed(ctx, error: Exception, *, settings=None) -> None:
    """``on_permanent_failure``: record the outcome; meter a provider call that happened."""
    from app.core.config import get_settings

    settings = settings or get_settings()
    generation = _load_generation(ctx.db, ctx.job, lock=True)
    if generation is None or generation.finished_at is not None:
        return
    code = getattr(error, "code", "transient_error")
    if getattr(error, "metered", False):
        record_units(
            ctx.db,
            ctx.job.workspace_id,
            settings.llm_units_per_request,
            job_id=ctx.job.id,
            now=ctx.clock(),
        )
    generation.validation_status = "failed"
    generation.output = {"errorCode": code, "reasons": []}
    generation.provider_request_id = getattr(error, "request_id", None)
    generation.finished_at = ctx.clock()
    ctx.db.flush()
