"""BP-03/BP-04: deterministic constrained selection, shortage report, snapshot creation,
publication validation and content-hash stability."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from authoring_fakes import scope as make_scope
from generation_fakes import GenFakeSession

from app.models.authoring import Blueprint, BlueprintVersion
from app.models.generation import Exam, ExamItem, ExamVersion
from app.models.knowledge import CurriculumUnit
from app.services import exam_builder as builder
from app.services import question_bank as bank
from app.services.authoring_common import Conflict

UNIT_A, UNIT_B = uuid4(), uuid4()


def slot(index, unit=UNIT_A, level="remember", difficulty=None, points="1.00", part="P1"):
    return builder.Slot(part, index, Decimal(points), unit, level, difficulty, index)


def candidate(unit=UNIT_A, level="remember", difficulty=None):
    return builder.Candidate(uuid4(), uuid4(), unit, level, difficulty)


def test_selection_is_deterministic_and_never_reuses():
    pool = [candidate() for _ in range(6)]
    slots = [slot(i) for i in range(1, 4)]
    first = builder.select_from_pool(slots, pool, "seed-1")
    again = builder.select_from_pool(slots, list(reversed(pool)), "seed-1")
    assert first.ok and [p.candidate for p in first.picks] == [p.candidate for p in again.picks]
    assert len({p.candidate.question_id for p in first.picks}) == 3
    seeds = {
        tuple(p.candidate.question_id for p in builder.select_from_pool(slots, pool, s).picks)
        for s in ("a", "b", "c", "d", "e")
    }
    assert len(seeds) > 1  # the seed actually drives the choice


def test_constrained_slots_are_filled_first():
    hard = candidate(difficulty=5)
    pool = [hard, candidate(difficulty=2)]
    slots = [slot(1), slot(2, difficulty=5)]
    for seed in ("x", "y", "z"):
        report = builder.select_from_pool(slots, pool, seed)
        assert report.ok
        assert next(p for p in report.picks if p.slot.index == 2).candidate == hard


def test_insufficient_pool_reports_missing_slots_without_relaxing():
    pool = [candidate(), candidate(level="apply", unit=UNIT_B)]
    slots = [slot(1), slot(2), slot(3, unit=UNIT_B, level="apply"), slot(4, unit=UNIT_B)]
    report = builder.select_from_pool(slots, pool, "s")
    assert not report.ok
    assert [(m["partCode"], m["index"]) for m in report.missing_slots] == [("P1", 2), ("P1", 4)]
    assert all(m["reason"] == "insufficient_pool" for m in report.missing_slots)
    counts = {(s["curriculumUnitId"], s["cognitiveLevel"]): s["count"] for s in report.suggestions}
    assert counts == {(str(UNIT_A), "remember"): 1, (str(UNIT_B), "remember"): 1}
    assert report.as_dict()["suggestedGeneration"][0]["purpose"] == "questions"


CHOICES = [{"key": "A", "text": "1"}, {"key": "B", "text": "2"}, {"key": "C", "text": "3"}]


def snap(position=1, key="A", points="5.00", choices=CHOICES, stem="Câu hỏi"):
    return builder.SnapshotItem(position, "single_choice", stem, choices, Decimal(points), key)


@pytest.mark.parametrize(
    "items,total,expected",
    [
        ([], "10", ["exam_empty"]),
        ([snap(key=None), snap(2)], "10", ["missing_key:1"]),
        ([snap(key="E"), snap(2)], "10", ["invalid_key:1"]),
        ([snap(choices=CHOICES[:2]), snap(2)], "10", ["invalid_choices:1"]),
        ([snap(points="0"), snap(2, points="10")], "10", ["invalid_points:1"]),
        ([snap(), snap(2)], "9.99", ["points_mismatch"]),
        ([snap(), snap(2)], "10.00", []),
    ],
)
def test_publication_rules(items, total, expected):
    assert builder.publication_errors(items, Decimal(total)) == expected


def test_content_hash_is_stable_and_excludes_keys():
    base = [snap(2), snap(1)]
    assert builder.content_hash(base) == builder.content_hash(list(reversed(base)))
    assert builder.content_hash(base) == builder.content_hash([snap(1, key="B"), snap(2)])
    assert builder.content_hash(base) != builder.content_hash([snap(1, stem="Khác"), snap(2)])
    assert builder.content_hash(base) != builder.content_hash([snap(1, points="5.5"), snap(2)])
    assert len(builder.content_hash(base)) == 32


# ---- Database-level flows over the in-memory session ----------------------------------------


NOW = datetime(2026, 10, 23, tzinfo=UTC)


async def seeded(count=3, level="remember"):
    db = GenFakeSession()
    scope = make_scope()
    unit = CurriculumUnit(id=UNIT_A, subject_id=uuid4(), grade=6, unit_code="T6-01")
    db.add(unit)
    questions = []
    for i in range(count):
        question, _ = await bank.create_question(
            db,
            scope,
            bank.QuestionInput(
                stem=f"Câu hỏi số {i}",
                choices=[{"key": k, "text": f"{k}{i}"} for k in "ABCD"],
                cognitive_level=level,
                correct_key="ABCD"[i % 4],
                explanation=f"Giải thích {i}",
                curriculum_unit_id=UNIT_A,
            ),
        )
        questions.append(question)
    blueprint = Blueprint(
        id=uuid4(), workspace_id=scope.workspace.id, title="Kiểm tra 15 phút", total_points=10
    )
    db.add(blueprint)
    body = {
        "parts": [
            {
                "code": "P1",
                "title": "Trắc nghiệm",
                "slots": [
                    {
                        "index": i,
                        "itemType": "single_choice",
                        "points": "5.00",
                        "curriculumUnitId": str(UNIT_A),
                        "cognitiveLevel": "remember",
                    }
                    for i in (1, 2)
                ],
            }
        ],
        "matrix": [{"curriculumUnitId": str(UNIT_A), "cognitiveLevel": "remember", "count": 2}],
    }
    version = BlueprintVersion(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        blueprint_id=blueprint.id,
        version_no=1,
        body=body,
        status="published",
    )
    db.add(version)
    return db, scope, questions, version


async def test_create_from_blueprint_snapshots_items_and_keys():
    db, scope, questions, version = await seeded()
    exam, exam_version, items, report = await builder.create_exam_from_blueprint(
        db, scope, blueprint_version_id=version.id, title=None, seed="s1"
    )
    assert report.ok and exam.title == "Kiểm tra 15 phút" and exam.status == "draft"
    assert exam_version.status == "draft" and exam_version.total_points == Decimal("10.00")
    assert [i.position for i in items] == [1, 2] and exam.current_version_id == exam_version.id
    by_revision = {q.current_revision_id: q for q in questions}
    for item in items:
        source = by_revision[item.source_question_revision_id]
        assert (
            item.stem == source.stem
            and db.exam_keys[item.id][0] == db.keys[item.source_question_revision_id]
        )
    # Later bank edits never touch the snapshot.
    first = items[0]
    question = by_revision[first.source_question_revision_id]
    await bank.update_question(
        db,
        scope,
        question.id,
        bank.QuestionInput(
            stem="Đề đã sửa",
            choices=[{"key": k, "text": f"mới {k}"} for k in "ABC"],
            cognitive_level="remember",
            correct_key="C",
        ),
    )
    assert first.stem != "Đề đã sửa" and len(first.choices) == 4
    published = await builder.publish_exam_version(db, scope, exam.id, 1)
    assert published.status == "published" and len(published.content_hash) == 32
    assert published.published_by_user_id == scope.user.id and exam.status == "published"
    with pytest.raises(Conflict) as error:
        await builder.publish_exam_version(db, scope, exam.id, 1)
    assert error.value.code == "exam_version_not_draft"


async def test_insufficient_pool_creates_nothing():
    db, scope, _, version = await seeded(count=1)
    exam, _, _, report = await builder.create_exam_from_blueprint(
        db, scope, blueprint_version_id=version.id, title="Đề", seed=None
    )
    assert exam is None and not report.ok and len(report.missing_slots) == 1
    assert db.all(Exam) == [] and db.all(ExamVersion) == [] and db.all(ExamItem) == []


async def test_unpublished_blueprint_is_refused():
    db, scope, _, version = await seeded()
    version.status = "validated"
    with pytest.raises(Conflict) as error:
        await builder.create_exam_from_blueprint(
            db, scope, blueprint_version_id=version.id, title=None
        )
    assert error.value.code == "blueprint_not_published"


async def test_manual_exam_and_publication_validation():
    db, scope, questions, _ = await seeded()
    exam, version, items = await builder.create_exam_manual(
        db,
        scope,
        title="Đề tự chọn",
        selections=[(questions[0].id, Decimal("4")), (questions[1].id, Decimal("6"))],
    )
    assert version.total_points == Decimal("10.00") and len(items) == 2
    del db.exam_keys[items[1].id]  # a missing key blocks publication
    with pytest.raises(Conflict) as error:
        await builder.publish_exam_version(db, scope, exam.id, 1)
    assert error.value.code == "exam_not_publishable" and "missing_key:2" in error.value.message
    with pytest.raises(Exception) as duplicate:
        await builder.create_exam_manual(
            db,
            scope,
            title="Trùng",
            selections=[(questions[0].id, Decimal("1")), (questions[0].id, Decimal("1"))],
        )
    assert duplicate.value.code == "duplicate_question"
