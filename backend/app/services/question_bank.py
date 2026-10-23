"""Single-choice question bank with separated answer keys (QB-01, QB-02).

* Every edit creates a new append-only ``question_revisions`` row.
* Keys live in ``question_keys``: the runtime role may INSERT but never SELECT them. Staff read
  a key only through ``edu.question_key(revision_id)`` (teacher roles checked in SQL). Keys are
  immutable per revision; changing a key creates a new revision with the same content.
* Student-facing exports use ``student_export_rows`` + ``student_csv`` which never reference
  the key function or explanations. Teacher exports are separate functions; there is no flag.
* CSV import validates every row, and is atomic: if any row has an error nothing is created.
  Duplicate stems (normalised sha256, in-file or already in the bank) are reported for review,
  never merged automatically.
"""

import csv
import hashlib
import io
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, select

from app.models.authoring import (
    COGNITIVE_LEVELS,
    ITEM_TYPES,
    Question,
    QuestionKey,
    QuestionObjective,
    QuestionRevision,
)
from app.models.knowledge import CurriculumUnit
from app.services.authoring_common import (
    Conflict,
    Invalid,
    NotFound,
    Scope,
    check_expected,
    parse_uuid,
    sha256_json,
    utcnow,
)

CHOICE_KEYS = "ABCDE"
MIN_CHOICES, MAX_CHOICES = 3, 5
MAX_STEM = 10000
MAX_CHOICE_TEXT = 2000
MAX_EXPLANATION = 10000
MAX_OBJECTIVES = 20
MAX_CITATIONS = 50
MAX_IMPORT_ROWS = 2000
MAX_EXPORT_ROWS = 5000
CSV_COLUMNS = (
    "stem",
    "choiceA",
    "choiceB",
    "choiceC",
    "choiceD",
    "choiceE",
    "correct",
    "difficulty",
    "cognitive",
    "unitCode",
    "explanation",
)
STUDENT_EXPORT_COLUMNS = (
    "id",
    "stem",
    "choiceA",
    "choiceB",
    "choiceC",
    "choiceD",
    "choiceE",
    "difficulty",
    "cognitive",
    "unitCode",
)
TEACHER_EXPORT_COLUMNS = STUDENT_EXPORT_COLUMNS + ("correct", "explanation", "status")
QUESTION_NOT_FOUND = ("question_not_found", "Không tìm thấy câu hỏi.")
BOM = "\ufeff"
NUMBER = re.compile(r"[-+]?\d+([.,]\d+)?")


@dataclass(frozen=True)
class QuestionInput:
    stem: str
    choices: list[dict[str, str]]
    cognitive_level: str
    difficulty: int | None = None
    correct_key: str | None = None
    rationale: str | None = None
    explanation: str | None = None
    curriculum_unit_id: UUID | None = None
    objective_unit_ids: tuple[UUID, ...] = ()
    source_citations: tuple[dict[str, str], ...] = ()
    item_type: str = "single_choice"


@dataclass
class ImportRow:
    row: int
    data: QuestionInput
    unit_code: str | None
    stem_sha256: bytes


@dataclass
class ImportReport:
    rows: list[ImportRow] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    created: list[UUID] = field(default_factory=list)


# ---- Pure helpers ---------------------------------------------------------------------------


def normalise_stem(stem: str) -> str:
    return " ".join(unicodedata.normalize("NFC", stem).casefold().split())


def stem_sha256(stem: str) -> bytes:
    return hashlib.sha256(normalise_stem(stem).encode("utf-8")).digest()


def revision_sha256(stem: str, choices: list[dict[str, str]], explanation: str | None) -> bytes:
    return sha256_json({"stem": stem, "choices": choices, "explanation": explanation})


def validate_question(data: QuestionInput) -> QuestionInput:
    """Pure validation of one single-choice question; raises ``Invalid`` with a stable code."""
    if data.item_type not in ITEM_TYPES:
        raise Invalid("unsupported_item_type", "Dạng câu hỏi này chưa được hỗ trợ.")
    stem = data.stem.strip() if isinstance(data.stem, str) else ""
    if not stem:
        raise Invalid("invalid_stem", "Đề bài không được để trống.")
    if len(stem) > MAX_STEM:
        raise Invalid("invalid_stem", f"Đề bài vượt quá {MAX_STEM} ký tự.")
    if not isinstance(data.choices, list) or not MIN_CHOICES <= len(data.choices) <= MAX_CHOICES:
        raise Invalid("invalid_choices", "Câu hỏi cần từ 3 đến 5 phương án.")
    expected_keys = CHOICE_KEYS[: len(data.choices)]
    choices, seen = [], set()
    for position, choice in enumerate(data.choices):
        if not isinstance(choice, Mapping) or set(choice) != {"key", "text"}:
            raise Invalid("invalid_choices", "Mỗi phương án gồm đúng hai trường key và text.")
        key, text_value = choice["key"], choice["text"]
        if key != expected_keys[position]:
            raise Invalid("invalid_choices", "Phương án phải được đánh thứ tự A, B, C, D, E.")
        if not isinstance(text_value, str) or not text_value.strip():
            raise Invalid("invalid_choices", f"Phương án {key} không được để trống.")
        if len(text_value) > MAX_CHOICE_TEXT:
            raise Invalid("invalid_choices", f"Phương án {key} quá dài.")
        normalised = normalise_stem(text_value)
        if normalised in seen:
            raise Invalid("duplicate_choice", "Các phương án không được trùng nhau.")
        seen.add(normalised)
        choices.append({"key": key, "text": text_value.strip()})
    if data.correct_key is not None and data.correct_key not in expected_keys:
        raise Invalid("invalid_correct_key", "Đáp án đúng phải là một trong các phương án.")
    if data.difficulty is not None and (
        isinstance(data.difficulty, bool) or not 1 <= data.difficulty <= 5
    ):
        raise Invalid("invalid_difficulty", "Độ khó phải từ 1 đến 5.")
    if data.cognitive_level not in COGNITIVE_LEVELS:
        raise Invalid("invalid_cognitive_level", "Mức độ nhận thức không hợp lệ.")
    explanation = (data.explanation or "").strip() or None
    if explanation is not None and len(explanation) > MAX_EXPLANATION:
        raise Invalid("invalid_explanation", "Lời giải quá dài.")
    rationale = (data.rationale or "").strip() or None
    if rationale is not None and len(rationale) > MAX_EXPLANATION:
        raise Invalid("invalid_rationale", "Giải thích đáp án quá dài.")
    objectives = tuple(dict.fromkeys(data.objective_unit_ids))
    if len(objectives) > MAX_OBJECTIVES:
        raise Invalid("too_many_objectives", "Tối đa 20 mục tiêu cho một câu hỏi.")
    citations = []
    if len(data.source_citations) > MAX_CITATIONS:
        raise Invalid("invalid_citations", "Quá nhiều trích dẫn nguồn.")
    for citation in data.source_citations:
        chunk = parse_uuid(citation.get("chunkId")) if isinstance(citation, Mapping) else None
        label = citation.get("label") if isinstance(citation, Mapping) else None
        if chunk is None or not isinstance(label, str) or not 1 <= len(label.strip()) <= 200:
            raise Invalid("invalid_citations", "Trích dẫn nguồn không hợp lệ.")
        citations.append({"chunkId": str(chunk), "label": label.strip()})
    return QuestionInput(
        stem=stem,
        choices=choices,
        cognitive_level=data.cognitive_level,
        difficulty=data.difficulty,
        correct_key=data.correct_key,
        rationale=rationale,
        explanation=explanation,
        curriculum_unit_id=data.curriculum_unit_id,
        objective_unit_ids=objectives,
        source_citations=tuple(citations),
        item_type=data.item_type,
    )


def _row_error(row: int, code: str, message: str) -> dict[str, Any]:
    return {"row": row, "code": code, "message": message}


def parse_import_csv(text_value: str) -> ImportReport:
    """Parse and validate an import file without touching the database.

    Row numbers are 1-based file lines (the header is row 1). Unit codes are resolved later.
    """
    report = ImportReport()
    reader = csv.reader(io.StringIO(text_value.removeprefix(BOM), newline=""))
    try:
        header = next(reader)
    except StopIteration:
        report.errors.append(_row_error(1, "empty_file", "Tệp CSV không có dữ liệu."))
        return report
    except csv.Error:
        report.errors.append(_row_error(1, "malformed_csv", "Tệp CSV không đúng định dạng."))
        return report
    if tuple(column.strip() for column in header) != CSV_COLUMNS:
        report.errors.append(
            _row_error(1, "invalid_header", "Dòng tiêu đề phải là: " + ",".join(CSV_COLUMNS))
        )
        return report
    seen: dict[bytes, int] = {}
    line = 1
    try:
        for record in reader:
            line += 1
            if not any(cell.strip() for cell in record):
                continue
            if len(report.rows) + len(report.errors) >= MAX_IMPORT_ROWS:
                report.errors.append(
                    _row_error(line, "too_many_rows", f"Tối đa {MAX_IMPORT_ROWS} câu mỗi lần.")
                )
                break
            if len(record) != len(CSV_COLUMNS):
                report.errors.append(
                    _row_error(line, "invalid_column_count", "Số cột của dòng không đúng.")
                )
                continue
            values = dict(zip(CSV_COLUMNS, (cell.strip() for cell in record), strict=True))
            choice_texts = [values[f"choice{key}"] for key in CHOICE_KEYS]
            while choice_texts and not choice_texts[-1]:
                choice_texts.pop()
            difficulty: int | None = None
            if values["difficulty"]:
                if not values["difficulty"].isdigit():
                    report.errors.append(
                        _row_error(line, "invalid_difficulty", "Độ khó phải từ 1 đến 5.")
                    )
                    continue
                difficulty = int(values["difficulty"])
            data = QuestionInput(
                stem=values["stem"],
                choices=[
                    {"key": CHOICE_KEYS[i], "text": choice} for i, choice in enumerate(choice_texts)
                ],
                cognitive_level=values["cognitive"],
                difficulty=difficulty,
                correct_key=values["correct"].upper() or None,
                explanation=values["explanation"] or None,
            )
            try:
                data = validate_question(data)
            except Invalid as exc:
                report.errors.append(_row_error(line, exc.code, exc.message))
                continue
            if data.correct_key is None:
                report.errors.append(_row_error(line, "missing_correct_key", "Thiếu đáp án đúng."))
                continue
            digest = stem_sha256(data.stem)
            if digest in seen:
                report.duplicates.append(
                    {
                        "row": line,
                        "stemSha256": digest.hex(),
                        "duplicateOfRow": seen[digest],
                        "existingQuestionId": None,
                    }
                )
                continue
            seen[digest] = line
            report.rows.append(ImportRow(line, data, values["unitCode"] or None, digest))
    except csv.Error:
        report.errors.append(_row_error(line + 1, "malformed_csv", "Tệp CSV không đúng định dạng."))
    return report


def _cell(value: Any) -> str:
    """Neutralise spreadsheet formulas (CSV injection) while keeping plain numbers intact."""
    text_value = "" if value is None else str(value)
    if text_value[:1] in ("=", "+", "@", "\t", "\r") or (
        text_value[:1] == "-" and not NUMBER.fullmatch(text_value)
    ):
        return "'" + text_value
    return text_value


def _choice_cells(choices: Sequence[Mapping[str, str]]) -> list[str]:
    by_key = {choice["key"]: choice["text"] for choice in choices}
    return [by_key.get(key, "") for key in CHOICE_KEYS]


def _write(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(value) for value in row])
    return BOM + buffer.getvalue()  # Excel opens UTF-8 Vietnamese text correctly with a BOM


@dataclass(frozen=True)
class ExportRow:
    """Student-safe projection; deliberately has no key or explanation fields."""

    id: UUID
    stem: str
    choices: list[dict[str, str]]
    difficulty: int | None
    cognitive_level: str
    unit_code: str | None


@dataclass(frozen=True)
class TeacherExportRow(ExportRow):
    correct_key: str | None = None
    explanation: str | None = None
    status: str = "draft"


def _base_cells(row: ExportRow) -> list[Any]:
    return [
        row.id,
        row.stem,
        *_choice_cells(row.choices),
        row.difficulty,
        row.cognitive_level,
        row.unit_code,
    ]


def student_csv(rows: Iterable[ExportRow]) -> str:
    """Student edition: no key column and no explanation, whatever row type is passed in."""
    return _write(STUDENT_EXPORT_COLUMNS, (_base_cells(row) for row in rows))


def teacher_csv(rows: Iterable[TeacherExportRow]) -> str:
    return _write(
        TEACHER_EXPORT_COLUMNS,
        ([*_base_cells(row), row.correct_key, row.explanation, row.status] for row in rows),
    )


# ---- Database helpers -----------------------------------------------------------------------


async def read_key(db, revision_id: UUID) -> str | None:
    """Teacher-only key read through the SECURITY DEFINER function (no table SELECT grant)."""
    value = await db.scalar(select(func.edu.question_key(revision_id)))
    return value.strip() if isinstance(value, str) else None


async def load_question(
    db, workspace_id: UUID, question_id: UUID, *, lock: bool = False
) -> Question:
    query = select(Question).where(
        Question.id == question_id, Question.workspace_id == workspace_id
    )
    if lock:
        query = query.with_for_update()
    question = await db.scalar(query)
    if question is None:
        raise NotFound(*QUESTION_NOT_FOUND)
    return question


async def load_current_revision(db, question: Question) -> QuestionRevision:
    revision = await db.scalar(
        select(QuestionRevision).where(
            QuestionRevision.workspace_id == question.workspace_id,
            QuestionRevision.question_id == question.id,
            QuestionRevision.id == question.current_revision_id,
        )
    )
    if revision is None:
        raise NotFound(*QUESTION_NOT_FOUND)
    return revision


async def objective_ids(db, question: Question) -> list[UUID]:
    rows = await db.scalars(
        select(QuestionObjective.curriculum_unit_id)
        .where(
            QuestionObjective.workspace_id == question.workspace_id,
            QuestionObjective.question_id == question.id,
        )
        .order_by(QuestionObjective.created_at, QuestionObjective.curriculum_unit_id)
    )
    return list(rows.all())


async def ensure_units(db, unit_ids: Iterable[UUID]) -> None:
    wanted = set(unit_ids)
    if not wanted:
        return
    found = set(
        (await db.scalars(select(CurriculumUnit.id).where(CurriculumUnit.id.in_(wanted)))).all()
    )
    if found != wanted:
        raise Invalid("curriculum_unit_not_found", "Có đơn vị chương trình không tồn tại.")


def _units_of(data: QuestionInput) -> list[UUID]:
    units = list(data.objective_unit_ids)
    if data.curriculum_unit_id is not None and data.curriculum_unit_id not in units:
        units.insert(0, data.curriculum_unit_id)
    return units


async def _insert_key(
    db, scope: Scope, revision: QuestionRevision, key: str, rationale: str | None
) -> None:
    # Core INSERT without RETURNING: the runtime role has no SELECT on question_keys.
    await db.execute(
        insert(QuestionKey).values(
            question_revision_id=revision.id,
            workspace_id=revision.workspace_id,
            correct_key=key,
            rationale=rationale,
            set_by_user_id=scope.user.id,
        )
    )


def _revision(scope: Scope, question: Question, number: int, data: QuestionInput):
    return QuestionRevision(
        id=uuid4(),
        workspace_id=question.workspace_id,
        question_id=question.id,
        revision_no=number,
        stem=data.stem,
        choices=data.choices,
        explanation=data.explanation,
        created_by_user_id=scope.user.id,
        body_sha256=revision_sha256(data.stem, data.choices, data.explanation),
        created_at=utcnow(),
    )


async def _replace_objectives(db, question: Question, units: list[UUID]) -> None:
    await db.execute(
        delete(QuestionObjective).where(
            QuestionObjective.workspace_id == question.workspace_id,
            QuestionObjective.question_id == question.id,
        )
    )
    for unit in units:
        db.add(
            QuestionObjective(
                workspace_id=question.workspace_id,
                question_id=question.id,
                curriculum_unit_id=unit,
                created_at=utcnow(),
            )
        )


async def create_question(
    db, scope: Scope, data: QuestionInput, *, validated: bool = False
) -> tuple[Question, QuestionRevision]:
    if not validated:
        data = validate_question(data)
        await ensure_units(db, _units_of(data))
    now = utcnow()
    question = Question(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        item_type=data.item_type,
        stem=data.stem,
        stem_sha256=stem_sha256(data.stem),
        status="active" if data.correct_key else "draft",
        difficulty=data.difficulty,
        cognitive_level=data.cognitive_level,
        curriculum_unit_id=data.curriculum_unit_id,
        source_citations=list(data.source_citations),
        created_by_user_id=scope.user.id,
        latest_revision_no=1,
        created_at=now,
        updated_at=now,
    )
    db.add(question)
    await db.flush()  # parent row before the composite FK of its revision
    revision = _revision(scope, question, 1, data)
    db.add(revision)
    question.current_revision_id = revision.id
    await db.flush()
    if data.correct_key:
        await _insert_key(db, scope, revision, data.correct_key, data.rationale)
    await _replace_objectives(db, question, _units_of(data))
    await db.flush()
    return question, revision


async def update_question(
    db,
    scope: Scope,
    question_id: UUID,
    data: QuestionInput,
    *,
    expected_revision_no: int | None = None,
) -> tuple[Question, QuestionRevision]:
    data = validate_question(data)
    question = await load_question(db, scope.workspace.id, question_id, lock=True)
    if expected_revision_no is not None:
        check_expected(question.latest_revision_no, expected_revision_no)
    if question.status == "retired":
        raise Conflict("question_retired", "Câu hỏi đã ngừng sử dụng, không thể chỉnh sửa.")
    if data.item_type != question.item_type:
        raise Invalid("item_type_immutable", "Không thể đổi dạng của câu hỏi đã tạo.")
    await ensure_units(db, _units_of(data))
    previous = await load_current_revision(db, question)
    key, rationale = data.correct_key, data.rationale
    if key is None and previous.choices == data.choices:
        # Same options: the existing key still means the same answer, so carry it over.
        key = await read_key(db, previous.id)
    revision = _revision(scope, question, question.latest_revision_no + 1, data)
    db.add(revision)
    now = utcnow()
    question.current_revision_id = revision.id
    question.latest_revision_no = revision.revision_no
    question.stem = data.stem
    question.stem_sha256 = stem_sha256(data.stem)
    question.difficulty = data.difficulty
    question.cognitive_level = data.cognitive_level
    question.curriculum_unit_id = data.curriculum_unit_id
    question.source_citations = list(data.source_citations)
    question.status = "active" if key else "draft"
    question.updated_at = now
    await db.flush()
    if key:
        await _insert_key(db, scope, revision, key, rationale)
    await _replace_objectives(db, question, _units_of(data))
    await db.flush()
    return question, revision


async def set_key(
    db, scope: Scope, question_id: UUID, correct_key: str, rationale: str | None = None
) -> tuple[Question, QuestionRevision]:
    question = await load_question(db, scope.workspace.id, question_id, lock=True)
    if question.status == "retired":
        raise Conflict("question_retired", "Câu hỏi đã ngừng sử dụng, không thể chỉnh sửa.")
    revision = await load_current_revision(db, question)
    keys = [choice["key"] for choice in revision.choices]
    if correct_key not in keys:
        raise Invalid("invalid_correct_key", "Đáp án đúng phải là một trong các phương án.")
    rationale = (rationale or "").strip() or None
    existing = await read_key(db, revision.id)
    now = utcnow()
    if existing == correct_key:
        return question, revision
    if existing is not None:
        # Keys are immutable per revision: a changed key is a new revision of the same content.
        revision = _revision(
            scope,
            question,
            question.latest_revision_no + 1,
            QuestionInput(
                stem=revision.stem,
                choices=revision.choices,
                cognitive_level=question.cognitive_level,
                explanation=revision.explanation,
            ),
        )
        db.add(revision)
        question.current_revision_id = revision.id
        question.latest_revision_no = revision.revision_no
        await db.flush()
    await _insert_key(db, scope, revision, correct_key, rationale)
    question.status = "active"
    question.updated_at = now
    await db.flush()
    return question, revision


async def retire(db, scope: Scope, question_id: UUID) -> Question:
    question = await load_question(db, scope.workspace.id, question_id, lock=True)
    if question.status != "retired":
        question.status = "retired"
        question.updated_at = utcnow()
        await db.flush()
    return question


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def question_listing(
    workspace_id: UUID,
    *,
    unit_id: UUID | None = None,
    difficulty: int | None = None,
    cognitive_level: str | None = None,
    status: str | None = None,
    search: str | None = None,
):
    query = (
        select(Question, QuestionRevision)
        .join(
            QuestionRevision,
            (QuestionRevision.id == Question.current_revision_id)
            & (QuestionRevision.workspace_id == Question.workspace_id),
        )
        .where(Question.workspace_id == workspace_id)
    )
    if unit_id is not None:
        query = query.where(Question.curriculum_unit_id == unit_id)
    if difficulty is not None:
        query = query.where(Question.difficulty == difficulty)
    if cognitive_level is not None:
        query = query.where(Question.cognitive_level == cognitive_level)
    if status is not None:
        query = query.where(Question.status == status)
    if search:
        query = query.where(Question.stem.ilike(f"%{escape_like(search)}%", escape="\\"))
    return query


async def resolve_unit_codes(db, codes: Iterable[str]) -> dict[str, list[UUID]]:
    wanted = sorted(set(codes))
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(CurriculumUnit.unit_code, CurriculumUnit.id).where(
                CurriculumUnit.unit_code.in_(wanted)
            )
        )
    ).all()
    found: dict[str, list[UUID]] = {}
    for code, unit_id in rows:
        found.setdefault(code, []).append(unit_id)
    return found


async def import_csv(db, scope: Scope, text_value: str) -> ImportReport:
    report = parse_import_csv(text_value)
    if report.errors and not report.rows:
        return report
    units = await resolve_unit_codes(db, (r.unit_code for r in report.rows if r.unit_code))
    for item in report.rows:
        if item.unit_code is None:
            continue
        matches = units.get(item.unit_code, [])
        if len(matches) != 1:
            code, message = (
                ("unknown_unit_code", "Mã đơn vị chương trình không tồn tại.")
                if not matches
                else ("ambiguous_unit_code", "Mã đơn vị chương trình trùng ở nhiều môn/lớp.")
            )
            report.errors.append(_row_error(item.row, code, message))
            continue
        item.data = replace(item.data, curriculum_unit_id=matches[0])
    existing = {}
    hashes = [item.stem_sha256 for item in report.rows]
    if hashes:
        rows = (
            await db.execute(
                select(Question.stem_sha256, Question.id).where(
                    Question.workspace_id == scope.workspace.id,
                    Question.stem_sha256.in_(hashes),
                )
            )
        ).all()
        existing = {bytes(digest): question_id for digest, question_id in rows}
    fresh = []
    for item in report.rows:
        if item.stem_sha256 in existing:
            report.duplicates.append(
                {
                    "row": item.row,
                    "stemSha256": item.stem_sha256.hex(),
                    "duplicateOfRow": None,
                    "existingQuestionId": existing[item.stem_sha256],
                }
            )
        else:
            fresh.append(item)
    report.errors.sort(key=lambda error: error["row"])
    report.duplicates.sort(key=lambda duplicate: duplicate["row"])
    if report.errors:
        return report  # atomic: nothing is created while any row is invalid
    for item in fresh:
        question, _ = await create_question(db, scope, item.data, validated=True)
        report.created.append(question.id)
    return report


async def _export_query(db, workspace_id: UUID, statuses: tuple[str, ...], *columns):
    return (
        await db.execute(
            select(Question, QuestionRevision, CurriculumUnit.unit_code, *columns)
            .join(
                QuestionRevision,
                (QuestionRevision.id == Question.current_revision_id)
                & (QuestionRevision.workspace_id == Question.workspace_id),
            )
            .outerjoin(CurriculumUnit, CurriculumUnit.id == Question.curriculum_unit_id)
            .where(Question.workspace_id == workspace_id, Question.status.in_(statuses))
            .order_by(Question.created_at, Question.id)
            .limit(MAX_EXPORT_ROWS)
        )
    ).all()


async def student_export_rows(db, workspace_id: UUID) -> list[ExportRow]:
    """Active questions only; the query never references keys or explanations."""
    rows = await _export_query(db, workspace_id, ("active",))
    return [
        ExportRow(
            id=question.id,
            stem=revision.stem,
            choices=revision.choices,
            difficulty=question.difficulty,
            cognitive_level=question.cognitive_level,
            unit_code=unit_code,
        )
        for question, revision, unit_code in rows
    ]


async def teacher_export_rows(db, workspace_id: UUID) -> list[TeacherExportRow]:
    rows = await _export_query(
        db,
        workspace_id,
        ("draft", "active"),
        func.edu.question_key(QuestionRevision.id).label("correct_key"),
    )
    return [
        TeacherExportRow(
            id=question.id,
            stem=revision.stem,
            choices=revision.choices,
            difficulty=question.difficulty,
            cognitive_level=question.cognitive_level,
            unit_code=unit_code,
            correct_key=key.strip() if isinstance(key, str) else None,
            explanation=revision.explanation,
            status=question.status,
        )
        for question, revision, unit_code, key in rows
    ]
