"""Blueprint validator cases from EXAM_BLUEPRINTS.md and version/publish flow without a DB."""

import copy
from decimal import Decimal
from uuid import uuid4

import pytest
from authoring_fakes import FakeSession, scope

from app.models.authoring import BlueprintVersion
from app.models.knowledge import CurriculumSubject, CurriculumUnit
from app.services import blueprints as service
from app.services.authoring_common import Conflict, Invalid, NotFound, RevisionConflict

SUBJECT = uuid4()
FRACTIONS, EXPRESSIONS, EQUATIONS = uuid4(), uuid4(), uuid4()
# Illustrative (non-official) example of EXAM_BLUEPRINTS.md section 6: rows 6/6/8, columns 8/8/4.
MATRIX = {
    FRACTIONS: {"remember": 3, "understand": 2, "apply": 1},
    EXPRESSIONS: {"remember": 2, "understand": 3, "apply": 1},
    EQUATIONS: {"remember": 3, "understand": 3, "apply": 2},
}


def example_body(points="0.50"):
    slots, index = [], 1
    for unit, cells in MATRIX.items():
        for level, count in cells.items():
            for _ in range(count):
                slots.append(
                    {
                        "index": index,
                        "itemType": "single_choice",
                        "points": points,
                        "curriculumUnitId": str(unit),
                        "cognitiveLevel": level,
                    }
                )
                index += 1
    matrix = [
        {"curriculumUnitId": str(unit), "cognitiveLevel": level, "count": count}
        for unit, cells in MATRIX.items()
        for level, count in cells.items()
    ]
    return {"parts": [{"code": "P1", "title": "Trắc nghiệm", "slots": slots}], "matrix": matrix}


def codes(report):
    return [error["code"] for error in report.errors]


def known(*units, subject=SUBJECT, grade=10):
    return {unit: service.UnitScope(subject, grade) for unit in units}


def test_illustrative_example_is_valid_20_slots_10_points():
    body = example_body()
    report = service.validate(body, total_points=Decimal("10"))
    assert report.ok and report.errors == [] and report.warnings == []
    slots = body["parts"][0]["slots"]
    assert len(slots) == 20
    by_unit = {u: sum(s["curriculumUnitId"] == str(u) for s in slots) for u in MATRIX}
    assert list(by_unit.values()) == [6, 6, 8]
    by_level = {
        lv: sum(s["cognitiveLevel"] == lv for s in slots)
        for lv in ("remember", "understand", "apply")
    }
    assert by_level == {"remember": 8, "understand": 8, "apply": 4}


def test_matrix_mismatch_is_reported_per_cell():
    body = example_body()
    body["matrix"][0]["count"] = 4  # matrix says 4 fraction/remember, slots give 3
    report = service.validate(body, total_points=Decimal("10"))
    assert not report.ok and codes(report) == ["matrix_mismatch"]
    assert "4" in report.errors[0]["message"] and "3" in report.errors[0]["message"]


def test_slot_outside_matrix_is_a_mismatch():
    body = example_body()
    body["parts"][0]["slots"][0]["cognitiveLevel"] = "analyze"
    report = service.validate(body, total_points=Decimal("10"))
    assert codes(report) == ["matrix_mismatch", "matrix_mismatch"]


def test_points_mismatch_uses_decimal():
    report = service.validate(example_body(points="0.50"), total_points=Decimal("9.99"))
    assert codes(report) == ["points_mismatch"]
    # 0.1 * 3 style float drift must not matter: thirty-ish 0.10 slots sum exactly.
    body = example_body(points=0.5)
    assert service.validate(body, total_points=Decimal("10.00")).ok


@pytest.mark.parametrize("points", ["0", "-1", "0.333", "abc", None, True])
def test_invalid_points(points):
    body = example_body()
    body["parts"][0]["slots"][0]["points"] = points
    assert "invalid_points" in codes(service.validate(body, total_points=Decimal("10")))


@pytest.mark.parametrize("item_type", ["short_answer", "essay", "true_false_multi", None])
def test_unsupported_item_type_fails_explicitly(item_type):
    body = example_body()
    body["parts"][0]["slots"][5]["itemType"] = item_type
    report = service.validate(body, total_points=Decimal("10"))
    assert codes(report) == ["unsupported_item_type"]
    assert report.errors[0]["path"] == "parts[0].slots[5].itemType"


def test_missing_cognitive_level_is_error_and_difficulty_never_substitutes():
    body = example_body()
    slot = body["parts"][0]["slots"][0]
    del slot["cognitiveLevel"]
    slot["difficulty"] = 5
    report = service.validate(body, total_points=Decimal("10"))
    assert "missing_cognitive_level" in codes(report)
    assert [w["code"] for w in report.warnings] == ["difficulty_not_cognitive"]
    assert not report.ok


def test_difficulty_with_cognitive_level_is_fine_and_bounded():
    body = example_body()
    body["parts"][0]["slots"][0]["difficulty"] = 2
    assert service.validate(body, total_points=Decimal("10")).ok
    body["parts"][0]["slots"][0]["difficulty"] = 7
    assert codes(service.validate(body, total_points=Decimal("10"))) == ["invalid_difficulty"]


def test_duplicate_slot_indexes_and_part_codes():
    body = example_body()
    body["parts"][0]["slots"][1]["index"] = 1
    second = copy.deepcopy(body["parts"][0])
    second["slots"] = []
    body["parts"].append(second)
    report = service.validate(body, total_points=Decimal("10"))
    assert codes(report) == ["duplicate_part_code", "duplicate_slot_index"]


@pytest.mark.parametrize(
    "body,code",
    [
        (None, "invalid_schema"),
        ({"parts": []}, "invalid_schema"),
        ({"parts": [], "matrix": []}, "invalid_schema"),
        ({"parts": [{"code": "P", "title": "T", "slots": []}], "matrix": []}, "empty_blueprint"),
        ({"parts": [{"code": "P", "title": "T", "slots": [{}]}], "matrix": []}, None),
        ({"parts": [{"code": "P", "title": "T", "slots": []}], "matrix": [{"x": 1}]}, None),
    ],
)
def test_structural_errors(body, code):
    report = service.validate(body, total_points=Decimal("1"))
    assert not report.ok
    if code:
        assert code in codes(report)


def test_duplicate_and_negative_matrix_cells():
    body = example_body()
    body["matrix"].append(dict(body["matrix"][0]))
    body["matrix"].append(
        {"curriculumUnitId": str(uuid4()), "cognitiveLevel": "apply", "count": -1}
    )
    assert codes(service.validate(body, total_points=Decimal("10"))) == [
        "duplicate_matrix_cell",
        "invalid_matrix_count",
    ]


def test_unknown_units_and_scope_warning():
    body = example_body()
    report = service.validate(
        body,
        total_points=Decimal("10"),
        known_units=known(FRACTIONS, EXPRESSIONS),
        subject_id=SUBJECT,
        grade=10,
    )
    assert codes(report) == ["unknown_curriculum_unit"]
    units = known(FRACTIONS, EXPRESSIONS) | known(EQUATIONS, grade=11)
    report = service.validate(
        body, total_points=Decimal("10"), known_units=units, subject_id=SUBJECT, grade=10
    )
    assert report.ok and [w["code"] for w in report.warnings] == ["unit_outside_scope"]
    assert service.referenced_units(body) == {FRACTIONS, EXPRESSIONS, EQUATIONS}


def test_supported_types_are_injectable_for_future_item_types():
    body = example_body()
    body["parts"][0]["slots"][0]["itemType"] = "short_answer"
    report = service.validate(
        body, total_points=Decimal("10"), supported_item_types={"single_choice", "short_answer"}
    )
    assert report.ok


# ---- Version / publish flow -----------------------------------------------------------------


@pytest.fixture
def db():
    session = FakeSession()
    session.add(CurriculumSubject(id=SUBJECT, code="toan"))
    for unit in MATRIX:
        session.add(CurriculumUnit(id=unit, subject_id=SUBJECT, grade=10))
    return session


@pytest.fixture
def teacher():
    return scope()


async def make_blueprint(db, teacher, total="10.00"):
    return await service.create_blueprint(
        db,
        teacher,
        title="Kiểm tra giữa kỳ",
        subject_id=SUBJECT,
        grade=10,
        program_year="2018",
        exam_kind="periodic",
        duration_minutes=45,
        total_points=Decimal(total),
        effective_year=2026,
        provenance="Giáo viên tự biên soạn",
    )


async def test_create_requires_known_subject_and_valid_points(db, teacher):
    blueprint = await make_blueprint(db, teacher)
    assert blueprint.origin_kind == "teacher_defined" and blueprint.status == "draft"
    with pytest.raises(Invalid):
        await make_blueprint(db, teacher, total="1.234")
    with pytest.raises(Invalid) as error:
        await service.create_blueprint(
            db,
            teacher,
            title="x",
            subject_id=uuid4(),
            grade=10,
            program_year="2018",
            exam_kind="mock",
            duration_minutes=30,
            total_points=Decimal("10"),
            effective_year=2026,
            provenance="x",
        )
    assert error.value.code == "curriculum_subject_not_found"


async def test_valid_version_is_validated_and_publishable(db, teacher):
    blueprint = await make_blueprint(db, teacher)
    version = await service.create_version(db, teacher, blueprint.id, example_body())
    assert version.status == "validated" and version.validation_report["ok"] is True
    assert version.validated_at is not None and len(version.body_sha256) == 32
    published = await service.publish(db, teacher, blueprint.id, 1)
    assert published.status == "published" and published.published_by_user_id == teacher.user.id
    assert blueprint.current_version_id == version.id and blueprint.status == "published"
    with pytest.raises(Conflict):
        await service.revalidate(db, teacher, blueprint.id, 1)


async def test_invalid_version_stays_draft_and_cannot_publish(db, teacher):
    blueprint = await make_blueprint(db, teacher)
    body = example_body()
    body["parts"][0]["slots"][0]["itemType"] = "essay"
    version = await service.create_version(db, teacher, blueprint.id, body)
    assert version.status == "draft"
    assert version.validation_report["errors"][0]["code"] == "unsupported_item_type"
    with pytest.raises(Conflict) as error:
        await service.publish(db, teacher, blueprint.id, 1)
    assert error.value.code == "blueprint_not_validated"
    again = await service.revalidate(db, teacher, blueprint.id, 1)
    assert again.status == "draft"


async def test_unknown_unit_detected_against_catalog(db, teacher):
    blueprint = await make_blueprint(db, teacher)
    body = example_body()
    stranger = str(uuid4())
    body["parts"][0]["slots"][0]["curriculumUnitId"] = stranger
    body["matrix"][0]["count"] -= 1
    body["matrix"].append({"curriculumUnitId": stranger, "cognitiveLevel": "remember", "count": 1})
    version = await service.create_version(db, teacher, blueprint.id, body)
    assert [e["code"] for e in version.validation_report["errors"]] == ["unknown_curriculum_unit"]


async def test_versions_use_optimistic_concurrency_and_new_publish_archives_old(db, teacher):
    blueprint = await make_blueprint(db, teacher)
    first = await service.create_version(db, teacher, blueprint.id, example_body())
    await service.publish(db, teacher, blueprint.id, 1)
    with pytest.raises(RevisionConflict) as error:
        await service.create_version(
            db, teacher, blueprint.id, example_body(), expected_version_no=0
        )
    assert error.value.latest == 1
    second = await service.create_version(
        db, teacher, blueprint.id, example_body(), expected_version_no=1
    )
    await service.publish(db, teacher, blueprint.id, 2)
    assert first.status == "archived" and first.published_at is not None
    assert second.status == "published" and blueprint.current_version_id == second.id
    assert len(db.all(BlueprintVersion)) == 2


async def test_cross_workspace_blueprint_is_not_found(db, teacher):
    blueprint = await make_blueprint(db, teacher)
    with pytest.raises(NotFound):
        await service.create_version(db, scope(), blueprint.id, example_body())
