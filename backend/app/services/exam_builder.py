"""Constrained exam assembly and immutable exam snapshots (BP-03, BP-04).

* ``select_items``: fills every slot of a PUBLISHED blueprint version from ``active`` bank
  questions whose (curriculumUnitId, cognitiveLevel[, difficulty]) match the slot, never using
  a question twice. Order is deterministic for a given seed (candidates ranked by
  ``sha256(seed:questionId)``; the most constrained slots are filled first). An insufficient
  pool yields ``SelectionReport(ok=False, missing_slots=[...])`` plus the counts that
  ``questions.generate`` could draft; the matrix is never silently altered and no exam is
  created.
* ``create_exam_from_blueprint`` / ``create_exam_manual`` build a ``draft`` exam version whose
  items COPY stem/choices/points and whose keys are copied through ``edu.question_key`` (staff
  only); later bank or blueprint edits never touch the snapshot.
* ``publish_exam_version`` validates (>= 1 item, 3..5 choices, exactly one key per item that
  names a choice, points > 0, sum = total), sets ``content_hash`` = sha256 of the canonical
  items JSON (keys excluded) and freezes the version (the database re-validates in a trigger).
"""

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, insert, select

from app.models.authoring import Blueprint, BlueprintVersion, Question, QuestionRevision
from app.models.generation import Exam, ExamAnswerKey, ExamItem, ExamVersion
from app.services import question_bank as bank
from app.services.authoring_common import (
    Conflict,
    Invalid,
    NotFound,
    Scope,
    canonical_json,
    utcnow,
)

CENT = Decimal("0.01")
MAX_ITEMS = 200
EXAM_NOT_FOUND = ("exam_not_found", "Không tìm thấy đề kiểm tra.")
VERSION_NOT_FOUND = ("exam_version_not_found", "Không tìm thấy phiên bản đề kiểm tra.")


@dataclass(frozen=True)
class Slot:
    part_code: str
    index: int
    points: Decimal
    unit_id: UUID
    cognitive_level: str
    difficulty: int | None
    order: int


@dataclass(frozen=True)
class Candidate:
    question_id: UUID
    revision_id: UUID
    unit_id: UUID | None
    cognitive_level: str
    difficulty: int | None


@dataclass(frozen=True)
class Pick:
    slot: Slot
    candidate: Candidate


@dataclass
class SelectionReport:
    ok: bool = True
    picks: list[Pick] = field(default_factory=list)
    missing_slots: list[dict[str, Any]] = field(default_factory=list)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    seed: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "seed": self.seed,
            "selected": len(self.picks),
            "missingSlots": self.missing_slots,
            "suggestedGeneration": self.suggestions,
        }


# ---- Pure selection -------------------------------------------------------------------------


def expand_slots(body: Mapping[str, Any]) -> list[Slot]:
    slots = []
    order = 0
    for part in body.get("parts", []):
        for slot in part.get("slots", []):
            slots.append(
                Slot(
                    part_code=str(part["code"]),
                    index=int(slot["index"]),
                    points=Decimal(str(slot["points"])).quantize(CENT),
                    unit_id=UUID(str(slot["curriculumUnitId"])),
                    cognitive_level=slot["cognitiveLevel"],
                    difficulty=slot.get("difficulty"),
                    order=order,
                )
            )
            order += 1
    return slots


def _rank(seed: str, question_id: UUID) -> str:
    return hashlib.sha256(f"{seed}:{question_id}".encode()).hexdigest()


def matches(slot: Slot, candidate: Candidate) -> bool:
    return (
        candidate.unit_id == slot.unit_id
        and candidate.cognitive_level == slot.cognitive_level
        and (slot.difficulty is None or candidate.difficulty == slot.difficulty)
    )


def select_from_pool(
    slots: Sequence[Slot], pool: Sequence[Candidate], seed: str
) -> SelectionReport:
    """Deterministic constrained selection; never reuses a question, never relaxes a slot."""
    report = SelectionReport(seed=seed)
    ranked = sorted(pool, key=lambda c: (_rank(seed, c.question_id), str(c.question_id)))
    used: set[UUID] = set()
    chosen: dict[int, Pick] = {}
    # Most constrained first (explicit difficulty), then document order.
    for slot in sorted(slots, key=lambda s: (s.difficulty is None, s.order)):
        candidate = next(
            (c for c in ranked if c.question_id not in used and matches(slot, c)), None
        )
        if candidate is None:
            report.ok = False
            report.missing_slots.append(
                {
                    "partCode": slot.part_code,
                    "index": slot.index,
                    "reason": "insufficient_pool",
                    "curriculumUnitId": str(slot.unit_id),
                    "cognitiveLevel": slot.cognitive_level,
                    "difficulty": slot.difficulty,
                }
            )
            continue
        used.add(candidate.question_id)
        chosen[slot.order] = Pick(slot, candidate)
    report.picks = [chosen[o] for o in sorted(chosen)]
    report.missing_slots.sort(key=lambda m: (m["partCode"], m["index"]))
    shortage = Counter(
        (m["curriculumUnitId"], m["cognitiveLevel"], m["difficulty"]) for m in report.missing_slots
    )
    report.suggestions = [
        {
            "purpose": "questions",
            "curriculumUnitId": unit,
            "cognitiveLevel": level,
            "difficulty": difficulty,
            "count": count,
        }
        for (unit, level, difficulty), count in sorted(shortage.items(), key=str)
    ]
    return report


# ---- Publication rules (pure) ---------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotItem:
    position: int
    item_type: str
    stem: str
    choices: list[dict[str, str]]
    points: Decimal
    correct_key: str | None


def publication_errors(items: Sequence[SnapshotItem], total_points: Decimal) -> list[str]:
    errors = []
    if not items:
        return ["exam_empty"]
    total = Decimal("0")
    for item in items:
        keys = [choice.get("key") for choice in item.choices]
        if not 3 <= len(keys) <= 5 or len(set(keys)) != len(keys):
            errors.append(f"invalid_choices:{item.position}")
        if item.points is None or Decimal(item.points) <= 0:
            errors.append(f"invalid_points:{item.position}")
        else:
            total += Decimal(item.points)
        if item.correct_key is None:
            errors.append(f"missing_key:{item.position}")
        elif item.correct_key not in keys:
            errors.append(f"invalid_key:{item.position}")
    if total.quantize(CENT) != Decimal(total_points).quantize(CENT):
        errors.append("points_mismatch")
    return errors


def content_hash(items: Sequence[SnapshotItem]) -> bytes:
    """sha256 of the canonical student-visible items (keys deliberately excluded)."""
    canonical = [
        {
            "position": item.position,
            "itemType": item.item_type,
            "stem": item.stem,
            "choices": [{"key": c["key"], "text": c["text"]} for c in item.choices],
            "points": str(Decimal(item.points).quantize(CENT)),
        }
        for item in sorted(items, key=lambda i: i.position)
    ]
    return hashlib.sha256(canonical_json(canonical)).digest()


# ---- Database -------------------------------------------------------------------------------


async def read_item_key(db, item_id: UUID) -> str | None:
    value = await db.scalar(select(func.edu.exam_item_key(item_id)))
    return value.strip() if isinstance(value, str) else None


async def read_item_explanation(db, item_id: UUID) -> str | None:
    return await db.scalar(select(func.edu.exam_item_explanation(item_id)))


async def load_blueprint_version(db, workspace_id: UUID, version_id: UUID):
    version = await db.scalar(
        select(BlueprintVersion).where(
            BlueprintVersion.id == version_id, BlueprintVersion.workspace_id == workspace_id
        )
    )
    if version is None:
        raise NotFound("blueprint_version_not_found", "Không tìm thấy phiên bản cấu trúc đề.")
    return version


async def candidate_pool(db, workspace_id: UUID, unit_ids: set[UUID]) -> list[Candidate]:
    rows = (
        await db.execute(
            bank.question_listing(workspace_id, status="active").where(
                Question.curriculum_unit_id.in_(unit_ids)
            )
        )
    ).all()
    return [
        Candidate(
            question_id=question.id,
            revision_id=revision.id,
            unit_id=question.curriculum_unit_id,
            cognitive_level=question.cognitive_level,
            difficulty=question.difficulty,
        )
        for question, revision in rows
    ]


async def select_items(
    db, scope: Scope, blueprint_version: BlueprintVersion, seed: str | None = None
) -> SelectionReport:
    if blueprint_version.status != "published":
        raise Conflict(
            "blueprint_not_published", "Chỉ cấu trúc đề đã xuất bản mới có thể dùng để tạo đề."
        )
    slots = expand_slots(blueprint_version.body)
    if not slots or len(slots) > MAX_ITEMS:
        raise Invalid("invalid_blueprint", "Cấu trúc đề không có câu hợp lệ.")
    pool = await candidate_pool(db, scope.workspace.id, {slot.unit_id for slot in slots})
    return select_from_pool(slots, pool, seed if seed is not None else str(blueprint_version.id))


async def _new_exam(db, scope: Scope, title: str, blueprint_version_id: UUID | None, total):
    now = utcnow()
    exam = Exam(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        title=title,
        blueprint_version_id=blueprint_version_id,
        status="draft",
        created_by_user_id=scope.user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(exam)
    await db.flush()
    version = ExamVersion(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        exam_id=exam.id,
        version_no=1,
        status="draft",
        total_points=Decimal(total).quantize(CENT),
        blueprint_version_id=blueprint_version_id,
        created_at=now,
    )
    db.add(version)
    await db.flush()
    exam.current_version_id = version.id
    return exam, version


async def _snapshot(db, scope: Scope, version: ExamVersion, entries) -> list[ExamItem]:
    """``entries``: (question, revision, points). Copies payload and key (teacher read)."""
    items = []
    for position, (question, revision, points) in enumerate(entries, start=1):
        key = await bank.read_key(db, revision.id)
        if key is None:
            raise Conflict(
                "question_key_missing", f"Câu hỏi ở vị trí {position} chưa có đáp án đúng."
            )
        item = ExamItem(
            id=uuid4(),
            workspace_id=version.workspace_id,
            exam_version_id=version.id,
            position=position,
            item_type=question.item_type,
            stem=revision.stem,
            choices=[dict(choice) for choice in revision.choices],
            points=Decimal(points).quantize(CENT),
            source_question_revision_id=revision.id,
            curriculum_unit_id=question.curriculum_unit_id,
            cognitive_level=question.cognitive_level,
        )
        db.add(item)
        await db.flush()
        # Core INSERT without RETURNING: the runtime role has no SELECT on exam_answer_keys.
        await db.execute(
            insert(ExamAnswerKey).values(
                exam_item_id=item.id,
                workspace_id=item.workspace_id,
                exam_version_id=version.id,
                correct_key=key,
                explanation=revision.explanation,
            )
        )
        items.append(item)
    return items


async def create_exam_from_blueprint(
    db, scope: Scope, *, blueprint_version_id: UUID, title: str | None, seed: str | None = None
):
    """Returns ``(exam, version, items, report)``; exam is None when the pool is insufficient."""
    blueprint_version = await load_blueprint_version(db, scope.workspace.id, blueprint_version_id)
    report = await select_items(db, scope, blueprint_version, seed)
    if not report.ok:
        return None, None, [], report
    blueprint = await db.scalar(
        select(Blueprint).where(
            Blueprint.id == blueprint_version.blueprint_id,
            Blueprint.workspace_id == scope.workspace.id,
        )
    )
    total = sum((pick.slot.points for pick in report.picks), Decimal("0"))
    exam, version = await _new_exam(
        db,
        scope,
        title or (blueprint.title if blueprint is not None else "Đề kiểm tra"),
        blueprint_version.id,
        total,
    )
    entries = []
    for pick in report.picks:
        question = await bank.load_question(db, scope.workspace.id, pick.candidate.question_id)
        revision = await db.scalar(
            select(QuestionRevision).where(
                QuestionRevision.workspace_id == scope.workspace.id,
                QuestionRevision.id == pick.candidate.revision_id,
            )
        )
        entries.append((question, revision, pick.slot.points))
    items = await _snapshot(db, scope, version, entries)
    await db.flush()
    return exam, version, items, report


async def create_exam_manual(
    db, scope: Scope, *, title: str, selections: Sequence[tuple[UUID, Decimal]]
):
    if not selections or len(selections) > MAX_ITEMS:
        raise Invalid("invalid_exam_items", f"Đề cần từ 1 đến {MAX_ITEMS} câu hỏi.")
    ids = [question_id for question_id, _ in selections]
    if len(set(ids)) != len(ids):
        raise Invalid("duplicate_question", "Mỗi câu hỏi chỉ được dùng một lần trong đề.")
    entries = []
    for question_id, points in selections:
        points = Decimal(points)
        if points <= 0 or points != points.quantize(CENT):
            raise Invalid("invalid_points", "Điểm mỗi câu phải dương, tối đa 2 chữ số thập phân.")
        question = await bank.load_question(db, scope.workspace.id, question_id)
        if question.status == "retired":
            raise Conflict("question_retired", "Không thể dùng câu hỏi đã ngừng sử dụng.")
        revision = await bank.load_current_revision(db, question)
        entries.append((question, revision, points))
    total = sum((points for _, _, points in entries), Decimal("0"))
    exam, version = await _new_exam(db, scope, title, None, total)
    items = await _snapshot(db, scope, version, entries)
    await db.flush()
    return exam, version, items


async def load_exam(db, workspace_id: UUID, exam_id: UUID, *, lock: bool = False) -> Exam:
    query = select(Exam).where(Exam.id == exam_id, Exam.workspace_id == workspace_id)
    if lock:
        query = query.with_for_update()
    exam = await db.scalar(query)
    if exam is None:
        raise NotFound(*EXAM_NOT_FOUND)
    return exam


async def load_version(db, exam: Exam, version_no: int, *, lock: bool = False) -> ExamVersion:
    query = select(ExamVersion).where(
        ExamVersion.workspace_id == exam.workspace_id,
        ExamVersion.exam_id == exam.id,
        ExamVersion.version_no == version_no,
    )
    if lock:
        query = query.with_for_update()
    version = await db.scalar(query)
    if version is None:
        raise NotFound(*VERSION_NOT_FOUND)
    return version


async def load_version_by_id(db, workspace_id: UUID, version_id: UUID) -> ExamVersion:
    version = await db.scalar(
        select(ExamVersion).where(
            ExamVersion.id == version_id, ExamVersion.workspace_id == workspace_id
        )
    )
    if version is None:
        raise NotFound(*VERSION_NOT_FOUND)
    return version


async def list_versions(db, exam: Exam) -> list[ExamVersion]:
    rows = await db.scalars(
        select(ExamVersion)
        .where(ExamVersion.workspace_id == exam.workspace_id, ExamVersion.exam_id == exam.id)
        .order_by(ExamVersion.version_no.desc())
    )
    return list(rows.all())


async def load_items(db, version: ExamVersion) -> list[ExamItem]:
    rows = await db.scalars(
        select(ExamItem)
        .where(
            ExamItem.workspace_id == version.workspace_id,
            ExamItem.exam_version_id == version.id,
        )
        .order_by(ExamItem.position)
    )
    return list(rows.all())


async def publish_exam_version(db, scope: Scope, exam_id: UUID, version_no: int) -> ExamVersion:
    exam = await load_exam(db, scope.workspace.id, exam_id, lock=True)
    if exam.status == "archived":
        raise Conflict("exam_archived", "Đề đã được lưu trữ.")
    version = await load_version(db, exam, version_no, lock=True)
    if version.status != "draft":
        raise Conflict("exam_version_not_draft", "Chỉ phiên bản nháp mới có thể xuất bản.")
    items = await load_items(db, version)
    snapshot = [
        SnapshotItem(
            position=item.position,
            item_type=item.item_type,
            stem=item.stem,
            choices=item.choices,
            points=Decimal(item.points),
            correct_key=await read_item_key(db, item.id),
        )
        for item in items
    ]
    errors = publication_errors(snapshot, Decimal(version.total_points))
    if errors:
        raise Conflict(
            "exam_not_publishable",
            "Đề chưa thể xuất bản: " + ", ".join(errors[:10]) + ".",
        )
    now = utcnow()
    if exam.current_version_id is not None and exam.current_version_id != version.id:
        previous = await db.scalar(
            select(ExamVersion)
            .where(
                ExamVersion.workspace_id == exam.workspace_id,
                ExamVersion.id == exam.current_version_id,
            )
            .with_for_update()
        )
        if previous is not None and previous.status == "published":
            previous.status = "archived"
    version.content_hash = content_hash(snapshot)
    version.status = "published"
    version.published_at = now
    version.published_by_user_id = scope.user.id
    exam.current_version_id = version.id
    exam.status = "published"
    exam.updated_at = now
    await db.flush()
    return version


async def archive_exam(db, scope: Scope, exam_id: UUID) -> Exam:
    exam = await load_exam(db, scope.workspace.id, exam_id, lock=True)
    if exam.status != "archived":
        exam.status = "archived"
        exam.updated_at = utcnow()
        await db.flush()
    return exam


def exam_listing(workspace_id: UUID, *, status: str | None = None):
    query = select(Exam).where(Exam.workspace_id == workspace_id)
    if status is not None:
        query = query.where(Exam.status == status)
    return query
