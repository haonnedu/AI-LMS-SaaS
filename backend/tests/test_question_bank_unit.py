"""Question bank without PostgreSQL: validation, CSV import (per-row errors, duplicates, atomic),
key separation (INSERT-only keys, student export without keys) and teacher/student DTOs."""

import csv
import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
from authoring_fakes import FakeSession, scope

from app.api import authoring as api
from app.models.authoring import Question, QuestionObjective, QuestionRevision
from app.models.knowledge import CurriculumUnit
from app.services import question_bank as bank
from app.services.authoring_common import Conflict, Invalid, RevisionConflict

HEADER = ",".join(bank.CSV_COLUMNS)


def choices(*texts):
    return [{"key": "ABCDE"[i], "text": t} for i, t in enumerate(texts or ("1", "2", "3", "4"))]


def question(**overrides):
    values = dict(stem="1 + 1 bằng mấy?", choices=choices(), cognitive_level="remember")
    values.update(overrides)
    return bank.QuestionInput(**values)


def rows_of(text):
    return list(csv.reader(io.StringIO(text.removeprefix(bank.BOM))))


# ---- Pure validation ------------------------------------------------------------------------


def test_valid_question_is_trimmed():
    clean = bank.validate_question(
        question(stem="  Đề  ", correct_key="B", explanation="  ", difficulty=3)
    )
    assert clean.stem == "Đề" and clean.explanation is None and clean.correct_key == "B"


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"item_type": "short_answer"}, "unsupported_item_type"),
        ({"stem": "   "}, "invalid_stem"),
        ({"choices": choices("1", "2")}, "invalid_choices"),
        (
            {"choices": choices("1", "2", "3", "4", "5") + [{"key": "F", "text": "6"}]},
            "invalid_choices",
        ),
        (
            {
                "choices": [
                    {"key": "A", "text": "1"},
                    {"key": "C", "text": "2"},
                    {"key": "B", "text": "3"},
                ]
            },
            "invalid_choices",
        ),
        ({"choices": choices("1", " ", "3")}, "invalid_choices"),
        ({"choices": choices("Hà Nội", "hà  nội", "Huế")}, "duplicate_choice"),
        ({"correct_key": "E"}, "invalid_correct_key"),
        ({"difficulty": 6}, "invalid_difficulty"),
        ({"difficulty": True}, "invalid_difficulty"),
        ({"cognitive_level": "create"}, "invalid_cognitive_level"),
        ({"source_citations": ({"chunkId": "x", "label": "a"},)}, "invalid_citations"),
    ],
)
def test_invalid_questions(overrides, code):
    with pytest.raises(Invalid) as error:
        bank.validate_question(question(**overrides))
    assert error.value.code == code


def test_stem_hash_normalises_case_space_and_unicode_form():
    assert bank.stem_sha256("Thủ đô  của Việt Nam?") == bank.stem_sha256(" thủ đô của việt nam? ")
    assert bank.stem_sha256("a") != bank.stem_sha256("b")


# ---- CSV import parsing ---------------------------------------------------------------------


def test_parse_reports_every_row_error_and_in_file_duplicates():
    text = "\n".join(
        [
            HEADER,
            "Câu 1?,1,2,3,,,A,2,remember,T10-01,Giải thích",
            "Câu 2?,1,2,,,,A,,remember,,",  # only two choices
            "Câu 3?,1,2,3,4,,F,,understand,,",  # key not among choices
            "Câu 4?,1,2,3,4,5,B,9,apply,,",  # difficulty out of range
            "Câu 5?,1,2,3,4,5,B,x,apply,,",  # difficulty not a number
            "Câu 6?,1,2,3,4,5,,,apply,,",  # missing key
            "câu  1?,4,5,6,,,C,,remember,,",  # duplicate stem of row 2
            "Câu 8?,1,2,3,,,a,,analyze,,",  # lower-case key accepted
            "too,few,columns",
            "",
        ]
    )
    report = bank.parse_import_csv(text)
    assert [(e["row"], e["code"]) for e in report.errors] == [
        (3, "invalid_choices"),
        (4, "invalid_correct_key"),
        (5, "invalid_difficulty"),
        (6, "invalid_difficulty"),
        (7, "missing_correct_key"),
        (10, "invalid_column_count"),
    ]
    assert all(set(e) == {"row", "code", "message"} for e in report.errors)
    assert [r.row for r in report.rows] == [2, 9]
    assert report.rows[0].unit_code == "T10-01" and report.rows[0].data.difficulty == 2
    assert report.rows[1].data.correct_key == "A"
    assert report.duplicates == [
        {
            "row": 8,
            "stemSha256": bank.stem_sha256("Câu 1?").hex(),
            "duplicateOfRow": 2,
            "existingQuestionId": None,
        }
    ]


@pytest.mark.parametrize(
    "text,code",
    [("", "empty_file"), ("stem,choiceA\nx,y", "invalid_header"), ('"unterminated', None)],
)
def test_parse_rejects_bad_files(text, code):
    report = bank.parse_import_csv(text)
    assert not report.rows
    if code:
        assert report.errors[0]["code"] == code


def test_parse_accepts_bom_and_crlf():
    report = bank.parse_import_csv(bank.BOM + HEADER + "\r\nCâu?,a,b,c,,,A,,remember,,\r\n")
    assert not report.errors and len(report.rows) == 1


def test_parse_row_cap():
    lines = [HEADER] + [f"Câu {i}?,1,2,3,,,A,,remember,," for i in range(bank.MAX_IMPORT_ROWS + 1)]
    report = bank.parse_import_csv("\n".join(lines))
    assert report.errors[-1]["code"] == "too_many_rows"
    assert len(report.rows) == bank.MAX_IMPORT_ROWS


# ---- Import with the in-memory session ------------------------------------------------------


@pytest.fixture
def db():
    session = FakeSession()
    session.unit = CurriculumUnit(id=uuid4(), unit_code="T10-01")
    session.add(session.unit)
    return session


@pytest.fixture
def teacher():
    return scope()


async def test_import_creates_questions_keys_and_flags_existing_duplicates(db, teacher):
    existing, _ = await bank.create_question(db, teacher, question(stem="Đã có?", correct_key="A"))
    text = "\n".join(
        [
            HEADER,
            "Câu mới?,1,2,3,,,B,3,understand,T10-01,Vì 2",
            "đã  CÓ?,1,2,3,,,A,,remember,,",
        ]
    )
    report = await bank.import_csv(db, teacher, text)
    assert not report.errors
    assert len(report.created) == 1
    assert report.duplicates[0]["existingQuestionId"] == existing.id
    created = next(q for q in db.all(Question) if q.id == report.created[0])
    assert created.status == "active" and created.curriculum_unit_id == db.unit.id
    revision = next(r for r in db.all(QuestionRevision) if r.question_id == created.id)
    assert db.keys[revision.id] == "B" and revision.explanation == "Vì 2"
    objectives = [o for o in db.all(QuestionObjective) if o.question_id == created.id]
    assert [o.curriculum_unit_id for o in objectives] == [db.unit.id]


async def test_import_is_atomic_on_any_error(db, teacher):
    text = "\n".join([HEADER, "Hợp lệ?,1,2,3,,,A,,remember,,", "Sai mã?,1,2,3,,,A,,remember,X-99,"])
    report = await bank.import_csv(db, teacher, text)
    assert report.created == []
    assert report.errors == [
        {"row": 3, "code": "unknown_unit_code", "message": "Mã đơn vị chương trình không tồn tại."}
    ]
    assert db.all(Question) == [] and db.keys == {}


async def test_import_ambiguous_unit_code(db, teacher):
    db.add(CurriculumUnit(id=uuid4(), unit_code="T10-01"))
    report = await bank.import_csv(db, teacher, HEADER + "\nCâu?,1,2,3,,,A,,remember,T10-01,")
    assert report.errors[0]["code"] == "ambiguous_unit_code" and not report.created


# ---- Key separation -------------------------------------------------------------------------


async def test_keys_are_insert_only_and_change_creates_new_revision(db, teacher):
    created, first = await bank.create_question(db, teacher, question())
    assert created.status == "draft" and db.keys == {}
    _, same = await bank.set_key(db, teacher, created.id, "C")
    assert same is first and db.keys == {first.id: "C"} and created.status == "active"
    _, unchanged = await bank.set_key(db, teacher, created.id, "C")
    assert unchanged is first and len(db.keys) == 1
    _, second = await bank.set_key(db, teacher, created.id, "D")
    assert second.revision_no == 2 and second.choices == first.choices
    assert db.keys == {first.id: "C", second.id: "D"}  # the old key row is never updated
    assert created.current_revision_id == second.id
    with pytest.raises(Invalid):
        await bank.set_key(db, teacher, created.id, "E")


async def test_update_creates_revision_and_carries_key_only_for_same_choices(db, teacher):
    created, first = await bank.create_question(db, teacher, question(correct_key="A"))
    _, second = await bank.update_question(
        db, teacher, created.id, question(stem="1 + 1 = ?"), expected_revision_no=1
    )
    assert second.revision_no == 2 and db.keys[second.id] == "A" and created.status == "active"
    assert created.stem == "1 + 1 = ?"
    _, third = await bank.update_question(
        db, teacher, created.id, question(choices=choices("2", "3", "4"))
    )
    assert third.id not in db.keys and created.status == "draft"
    with pytest.raises(RevisionConflict) as error:
        await bank.update_question(db, teacher, created.id, question(), expected_revision_no=1)
    assert error.value.latest == 3
    assert first.stem == "1 + 1 bằng mấy?"  # revisions are append-only


async def test_retired_question_is_frozen(db, teacher):
    created, _ = await bank.create_question(db, teacher, question(correct_key="A"))
    await bank.retire(db, teacher, created.id)
    assert created.status == "retired"
    with pytest.raises(Conflict):
        await bank.set_key(db, teacher, created.id, "B")
    with pytest.raises(Conflict):
        await bank.update_question(db, teacher, created.id, question())


async def test_student_export_has_no_key_column_and_never_reads_keys(db, teacher):
    await bank.create_question(
        db, teacher, question(stem="=HYPERLINK()", correct_key="B", explanation="BÍ_MẬT")
    )
    await bank.create_question(db, teacher, question(stem="Nháp?"))  # draft, excluded
    db.statements.clear()
    text = bank.student_csv(await bank.student_export_rows(db, teacher.workspace.id))
    rows = rows_of(text)
    assert rows[0] == list(bank.STUDENT_EXPORT_COLUMNS)
    assert "correct" not in rows[0] and "explanation" not in rows[0]
    assert len(rows) == 2 and rows[1][1] == "'=HYPERLINK()"  # formula neutralised
    assert "BÍ_MẬT" not in text
    assert not any("question_key" in str(s) for s in db.statements)
    assert db.key_reads == 0


async def test_student_csv_ignores_key_fields_even_if_given_teacher_rows():
    row = bank.TeacherExportRow(
        id=uuid4(),
        stem="Câu?",
        choices=choices(),
        difficulty=1,
        cognitive_level="remember",
        unit_code=None,
        correct_key="C",
        explanation="Lời giải",
    )
    rows = rows_of(bank.student_csv([row]))
    assert len(rows[1]) == len(bank.STUDENT_EXPORT_COLUMNS)
    assert "Lời giải" not in rows[1]


async def test_teacher_export_includes_keys(db, teacher):
    await bank.create_question(db, teacher, question(correct_key="B", explanation="Vì vậy"))
    await bank.create_question(db, teacher, question(stem="-x + 1?"))
    rows = rows_of(bank.teacher_csv(await bank.teacher_export_rows(db, teacher.workspace.id)))
    assert rows[0] == list(bank.TEACHER_EXPORT_COLUMNS)
    by_stem = {row[1]: row for row in rows[1:]}
    assert by_stem["1 + 1 bằng mấy?"][-3:] == ["B", "Vì vậy", "active"]
    assert by_stem["'-x + 1?"][-3:] == ["", "", "draft"]
    assert any("edu.question_key" in str(s) for s in db.statements)


def test_export_functions_are_separate_without_audience_flag():
    import inspect

    for function in (bank.student_csv, bank.teacher_csv, bank.student_export_rows):
        assert "audience" not in inspect.signature(function).parameters
    assert "correct_key" not in bank.ExportRow.__dataclass_fields__
    assert "explanation" not in bank.ExportRow.__dataclass_fields__


def test_numbers_are_not_quoted_in_csv():
    assert bank._cell("-5") == "-5" and bank._cell("-2,5") == "-2,5"
    assert bank._cell("+1") == "'+1" and bank._cell("@x") == "'@x"


# ---- DTO builders ---------------------------------------------------------------------------


def _orm(created):
    q = SimpleNamespace(
        id=uuid4(),
        item_type="single_choice",
        status="active",
        difficulty=2,
        cognitive_level="apply",
        curriculum_unit_id=None,
        source_citations=[{"chunkId": str(uuid4()), "label": "Tr. 1"}],
        created_at=created,
        updated_at=created,
    )
    r = SimpleNamespace(
        id=uuid4(), revision_no=3, stem="Câu?", choices=choices(), explanation="Giải"
    )
    return q, r


def test_teacher_dto_has_key_student_dto_never_does():
    from datetime import UTC, datetime

    q, r = _orm(datetime(2026, 10, 23, tzinfo=UTC))
    teacher = api.teacher_question_dto(q, r, "C", [])
    assert teacher.correctKey == "C" and teacher.explanation == "Giải"
    student = api.student_question_dto(q, r).model_dump()
    assert set(student) == {"id", "itemType", "stem", "choices"}
    for field in ("correctKey", "explanation", "rationale"):
        assert field not in api.StudentQuestionDTO.model_fields
        assert field not in api.QuestionSummaryDTO.model_fields
