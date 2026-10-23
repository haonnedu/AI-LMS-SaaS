"""Versioned exam blueprints and the deterministic validator (BP-01, BP-02).

A version body is ``{"parts": [{"code", "title", "slots": [{"index", "itemType", "points",
"curriculumUnitId", "cognitiveLevel", "difficulty"?}]}], "matrix": [{"curriculumUnitId",
"cognitiveLevel", "count"}]}``. Rules follow EXAM_BLUEPRINTS.md: one primary matrix cell per
slot, exact counts, Decimal points (2 dp), explicit ``unsupported_item_type`` (no silent type
change), and difficulty is never treated as a cognitive level. Bodies are immutable once
stored; every edit is a new version, and only a ``validated`` version can be published.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models.authoring import COGNITIVE_LEVELS, EXAM_KINDS, Blueprint, BlueprintVersion
from app.models.knowledge import CurriculumSubject, CurriculumUnit
from app.services.authoring_common import (
    Conflict,
    Invalid,
    NotFound,
    Scope,
    canonical_json,
    check_expected,
    parse_uuid,
    sha256_json,
    utcnow,
)

SUPPORTED_ITEM_TYPES = frozenset({"single_choice"})
MAX_BODY_BYTES = 200 * 1024
MAX_PARTS = 20
MAX_SLOTS = 200
MAX_CELLS = 500
CENT = Decimal("0.01")
BLUEPRINT_NOT_FOUND = ("blueprint_not_found", "Không tìm thấy cấu trúc đề.")
VERSION_NOT_FOUND = ("blueprint_version_not_found", "Không tìm thấy phiên bản cấu trúc đề.")


@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def error(self, code: str, message: str, path: str = "") -> None:
        self.ok = False
        self.errors.append({"code": code, "message": message, "path": path})

    def warn(self, code: str, message: str, path: str = "") -> None:
        self.warnings.append({"code": code, "message": message, "path": path})

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


@dataclass(frozen=True)
class UnitScope:
    subject_id: UUID
    grade: int


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str | Decimal):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def referenced_units(body: Any) -> set[UUID]:
    """Unit IDs mentioned anywhere in a (possibly invalid) body, for the DB existence check."""
    found: set[UUID] = set()
    if not isinstance(body, Mapping):
        return found
    parts = body.get("parts") if isinstance(body.get("parts"), list) else []
    cells = body.get("matrix") if isinstance(body.get("matrix"), list) else []
    slots = [
        slot
        for part in parts
        if isinstance(part, Mapping) and isinstance(part.get("slots"), list)
        for slot in part["slots"]
    ]
    for entry in [*slots, *cells]:
        if isinstance(entry, Mapping):
            unit = parse_uuid(entry.get("curriculumUnitId"))
            if unit is not None:
                found.add(unit)
    return found


def validate(
    body: Any,
    *,
    total_points: Decimal,
    known_units: Mapping[UUID, UnitScope] | None = None,
    subject_id: UUID | None = None,
    grade: int | None = None,
    supported_item_types: Iterable[str] = SUPPORTED_ITEM_TYPES,
) -> ValidationReport:
    """Deterministic blueprint validation. ``known_units=None`` skips the DB-backed unit check
    (pure unit tests); the API always passes the units it found in the catalog."""
    report = ValidationReport()
    supported = frozenset(supported_item_types)
    if not isinstance(body, Mapping) or set(body) != {"parts", "matrix"}:
        report.error("invalid_schema", "Cấu trúc đề phải gồm đúng hai trường parts và matrix.")
        return report
    parts, matrix = body["parts"], body["matrix"]
    if not isinstance(parts, list) or not 1 <= len(parts) <= MAX_PARTS:
        report.error("invalid_schema", f"Đề cần từ 1 đến {MAX_PARTS} phần.", "parts")
        return report
    if not isinstance(matrix, list) or len(matrix) > MAX_CELLS:
        report.error("invalid_schema", "Ma trận phải là danh sách ô hợp lệ.", "matrix")
        return report
    if len(canonical_json(body)) > MAX_BODY_BYTES:
        report.error("body_too_large", "Cấu trúc đề vượt quá giới hạn 200 KB.")
        return report

    slot_cells: Counter[tuple[UUID, str]] = Counter()
    indexes: Counter[int] = Counter()
    part_codes: Counter[str] = Counter()
    points_total = Decimal("0")
    slot_count = 0
    units_used: set[UUID] = set()

    for p_index, part in enumerate(parts):
        p_path = f"parts[{p_index}]"
        if not isinstance(part, Mapping) or not {"code", "title", "slots"} <= set(part):
            report.error("invalid_schema", "Phần đề cần code, title và slots.", p_path)
            continue
        if set(part) - {"code", "title", "slots"}:
            report.error("invalid_schema", "Phần đề có trường không được hỗ trợ.", p_path)
        code, title, slots = part["code"], part["title"], part["slots"]
        if not isinstance(code, str) or not 1 <= len(code.strip()) <= 32:
            report.error("invalid_schema", "Mã phần không hợp lệ.", f"{p_path}.code")
        else:
            part_codes[code.strip()] += 1
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 300:
            report.error("invalid_schema", "Tiêu đề phần không hợp lệ.", f"{p_path}.title")
        if not isinstance(slots, list):
            report.error("invalid_schema", "Danh sách câu của phần không hợp lệ.", p_path)
            continue
        for s_index, slot in enumerate(slots):
            s_path = f"{p_path}.slots[{s_index}]"
            slot_count += 1
            if slot_count > MAX_SLOTS:
                report.error("too_many_slots", f"Tối đa {MAX_SLOTS} câu trong một đề.", s_path)
                break
            if not isinstance(slot, Mapping):
                report.error("invalid_schema", "Câu (slot) phải là đối tượng JSON.", s_path)
                continue
            allowed = {
                "index",
                "itemType",
                "points",
                "curriculumUnitId",
                "cognitiveLevel",
                "difficulty",
            }
            if set(slot) - allowed:
                report.error("invalid_schema", "Câu có trường không được hỗ trợ.", s_path)
            index = _int(slot.get("index"))
            if index is None or index < 1:
                report.error("invalid_slot_index", "Số thứ tự câu phải là số nguyên ≥ 1.", s_path)
            else:
                indexes[index] += 1
            item_type = slot.get("itemType")
            if item_type not in supported:
                report.error(
                    "unsupported_item_type",
                    f"Dạng câu '{item_type}' chưa được hỗ trợ; không tự đổi sang dạng khác.",
                    f"{s_path}.itemType",
                )
            points = _decimal(slot.get("points"))
            if points is None or points <= 0 or points != points.quantize(CENT):
                report.error(
                    "invalid_points",
                    "Điểm của câu phải dương và tối đa 2 chữ số thập phân.",
                    f"{s_path}.points",
                )
            else:
                points_total += points
            unit = parse_uuid(slot.get("curriculumUnitId"))
            if unit is None:
                report.error(
                    "missing_curriculum_unit",
                    "Câu cần đơn vị chương trình (curriculumUnitId).",
                    f"{s_path}.curriculumUnitId",
                )
            else:
                units_used.add(unit)
            cognitive = slot.get("cognitiveLevel")
            difficulty = slot.get("difficulty")
            if difficulty is not None and (_int(difficulty) is None or not 1 <= difficulty <= 5):
                report.error(
                    "invalid_difficulty", "Độ khó phải từ 1 đến 5.", f"{s_path}.difficulty"
                )
            if cognitive is None:
                report.error(
                    "missing_cognitive_level",
                    "Câu cần mức độ nhận thức; độ khó không thay thế mức độ nhận thức.",
                    f"{s_path}.cognitiveLevel",
                )
                if difficulty is not None:
                    report.warn(
                        "difficulty_not_cognitive",
                        "Độ khó dự kiến không suy ra được mức độ nhận thức.",
                        s_path,
                    )
            elif cognitive not in COGNITIVE_LEVELS:
                report.error(
                    "invalid_cognitive_level",
                    "Mức độ nhận thức không hợp lệ.",
                    f"{s_path}.cognitiveLevel",
                )
            elif unit is not None:
                slot_cells[(unit, cognitive)] += 1

    if slot_count == 0:
        report.error("empty_blueprint", "Cấu trúc đề chưa có câu nào.", "parts")
    for code, count in part_codes.items():
        if count > 1:
            report.error("duplicate_part_code", f"Mã phần '{code}' bị trùng.", "parts")
    for index, count in sorted(indexes.items()):
        if count > 1:
            report.error("duplicate_slot_index", f"Số thứ tự câu {index} bị trùng.", "parts")

    matrix_cells: dict[tuple[UUID, str], int] = {}
    for c_index, cell in enumerate(matrix):
        c_path = f"matrix[{c_index}]"
        if not isinstance(cell, Mapping) or set(cell) != {
            "curriculumUnitId",
            "cognitiveLevel",
            "count",
        }:
            report.error(
                "invalid_schema", "Ô ma trận cần curriculumUnitId, cognitiveLevel, count.", c_path
            )
            continue
        unit = parse_uuid(cell["curriculumUnitId"])
        count = _int(cell["count"])
        if unit is None or cell["cognitiveLevel"] not in COGNITIVE_LEVELS:
            report.error("invalid_schema", "Ô ma trận không hợp lệ.", c_path)
            continue
        if count is None or count < 0:
            report.error("invalid_matrix_count", "Số câu của ô ma trận phải ≥ 0.", c_path)
            continue
        key = (unit, cell["cognitiveLevel"])
        if key in matrix_cells:
            report.error("duplicate_matrix_cell", "Ô ma trận bị khai báo trùng.", c_path)
            continue
        matrix_cells[key] = count
        units_used.add(unit)

    for key in sorted(set(matrix_cells) | set(slot_cells), key=lambda k: (str(k[0]), k[1])):
        expected, actual = matrix_cells.get(key, 0), slot_cells.get(key, 0)
        if expected != actual:
            report.error(
                "matrix_mismatch",
                f"Ô ({key[0]}, {key[1]}): ma trận {expected} câu nhưng cấu trúc có {actual} câu.",
                "matrix",
            )

    expected_total = _decimal(total_points)
    if expected_total is not None and points_total.quantize(CENT) != expected_total.quantize(CENT):
        report.error(
            "points_mismatch",
            f"Tổng điểm các câu ({points_total.quantize(CENT)}) khác tổng điểm đề "
            f"({expected_total.quantize(CENT)}).",
            "parts",
        )

    if known_units is not None:
        for unit in sorted(units_used, key=str):
            scope = known_units.get(unit)
            if scope is None:
                report.error(
                    "unknown_curriculum_unit", f"Đơn vị chương trình {unit} không tồn tại."
                )
            elif (subject_id is not None and scope.subject_id != subject_id) or (
                grade is not None and scope.grade != grade
            ):
                report.warn(
                    "unit_outside_scope",
                    f"Đơn vị chương trình {unit} không thuộc môn/khối của đề.",
                )
    return report


def body_sha256(body: Any) -> bytes:
    return sha256_json(body)


# ---- Database -------------------------------------------------------------------------------


async def load_blueprint(
    db, workspace_id: UUID, blueprint_id: UUID, *, lock: bool = False
) -> Blueprint:
    query = select(Blueprint).where(
        Blueprint.id == blueprint_id, Blueprint.workspace_id == workspace_id
    )
    if lock:
        query = query.with_for_update()
    blueprint = await db.scalar(query)
    if blueprint is None:
        raise NotFound(*BLUEPRINT_NOT_FOUND)
    return blueprint


async def load_version(
    db, blueprint: Blueprint, version_no: int, *, lock: bool = False
) -> BlueprintVersion:
    query = select(BlueprintVersion).where(
        BlueprintVersion.workspace_id == blueprint.workspace_id,
        BlueprintVersion.blueprint_id == blueprint.id,
        BlueprintVersion.version_no == version_no,
    )
    if lock:
        query = query.with_for_update()
    version = await db.scalar(query)
    if version is None:
        raise NotFound(*VERSION_NOT_FOUND)
    return version


async def list_versions(db, blueprint: Blueprint, limit: int = 100) -> list[BlueprintVersion]:
    rows = await db.scalars(
        select(BlueprintVersion)
        .where(
            BlueprintVersion.workspace_id == blueprint.workspace_id,
            BlueprintVersion.blueprint_id == blueprint.id,
        )
        .order_by(BlueprintVersion.version_no.desc())
        .limit(limit)
    )
    return list(rows.all())


async def known_units(db, unit_ids: set[UUID]) -> dict[UUID, UnitScope]:
    if not unit_ids:
        return {}
    rows = (
        await db.execute(
            select(CurriculumUnit.id, CurriculumUnit.subject_id, CurriculumUnit.grade).where(
                CurriculumUnit.id.in_(unit_ids)
            )
        )
    ).all()
    return {unit_id: UnitScope(subject, grade) for unit_id, subject, grade in rows}


async def run_validation(db, blueprint: Blueprint, body: Any) -> ValidationReport:
    return validate(
        body,
        total_points=Decimal(blueprint.total_points),
        known_units=await known_units(db, referenced_units(body)),
        subject_id=blueprint.subject_id,
        grade=blueprint.grade,
    )


async def create_blueprint(
    db,
    scope: Scope,
    *,
    title: str,
    subject_id: UUID,
    grade: int,
    program_year: str,
    exam_kind: str,
    duration_minutes: int,
    total_points: Decimal,
    effective_year: int,
    provenance: str,
) -> Blueprint:
    if exam_kind not in EXAM_KINDS:
        raise Invalid("invalid_exam_kind", "Loại kỳ kiểm tra không hợp lệ.")
    if total_points <= 0 or total_points != total_points.quantize(CENT):
        raise Invalid("invalid_total_points", "Tổng điểm phải dương, tối đa 2 chữ số thập phân.")
    found = await db.scalar(select(CurriculumSubject.id).where(CurriculumSubject.id == subject_id))
    if found is None:
        raise Invalid("curriculum_subject_not_found", "Môn học không tồn tại.")
    now = utcnow()
    blueprint = Blueprint(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        title=title,
        subject_id=subject_id,
        grade=grade,
        program_year=program_year,
        exam_kind=exam_kind,
        duration_minutes=duration_minutes,
        total_points=total_points,
        status="draft",
        latest_version_no=0,
        effective_year=effective_year,
        origin_kind="teacher_defined",
        provenance=provenance,
        created_by_user_id=scope.user.id,
        created_at=now,
        updated_at=now,
    )
    db.add(blueprint)
    await db.flush()
    return blueprint


async def create_version(
    db,
    scope: Scope,
    blueprint_id: UUID,
    body: Any,
    *,
    expected_version_no: int | None = None,
    blueprint: Blueprint | None = None,
) -> BlueprintVersion:
    if blueprint is None:
        blueprint = await load_blueprint(db, scope.workspace.id, blueprint_id, lock=True)
    if expected_version_no is not None:
        check_expected(blueprint.latest_version_no, expected_version_no)
    if blueprint.status == "archived":
        raise Conflict("blueprint_archived", "Cấu trúc đề đã được lưu trữ.")
    if not isinstance(body, Mapping):
        raise Invalid("invalid_schema", "Cấu trúc đề phải là đối tượng JSON.")
    if len(canonical_json(body)) > MAX_BODY_BYTES:
        raise Invalid("body_too_large", "Cấu trúc đề vượt quá giới hạn 200 KB.")
    report = await run_validation(db, blueprint, body)
    now = utcnow()
    version = BlueprintVersion(
        id=uuid4(),
        workspace_id=blueprint.workspace_id,
        blueprint_id=blueprint.id,
        version_no=blueprint.latest_version_no + 1,
        body=dict(body),
        status="validated" if report.ok else "draft",
        validation_report=report.as_dict(),
        body_sha256=body_sha256(body),
        created_by_user_id=scope.user.id,
        created_at=now,
        validated_at=now if report.ok else None,
    )
    db.add(version)
    blueprint.latest_version_no = version.version_no
    blueprint.updated_at = now
    await db.flush()
    return version


async def revalidate(db, scope: Scope, blueprint_id: UUID, version_no: int) -> BlueprintVersion:
    blueprint = await load_blueprint(db, scope.workspace.id, blueprint_id, lock=True)
    version = await load_version(db, blueprint, version_no, lock=True)
    if version.status not in ("draft", "validated"):
        raise Conflict(
            "blueprint_version_frozen",
            "Phiên bản đã xuất bản hoặc lưu trữ, không thể kiểm tra lại.",
        )
    report = await run_validation(db, blueprint, version.body)
    now = utcnow()
    version.validation_report = report.as_dict()
    version.status = "validated" if report.ok else "draft"
    version.validated_at = now if report.ok else None
    await db.flush()
    return version


async def publish(db, scope: Scope, blueprint_id: UUID, version_no: int) -> BlueprintVersion:
    blueprint = await load_blueprint(db, scope.workspace.id, blueprint_id, lock=True)
    version = await load_version(db, blueprint, version_no, lock=True)
    if version.status != "validated":
        raise Conflict(
            "blueprint_not_validated", "Chỉ phiên bản đã kiểm tra hợp lệ mới có thể xuất bản."
        )
    report = await run_validation(db, blueprint, version.body)
    if not report.ok:  # never publish on a stale report (the transaction rolls back)
        raise Conflict(
            "blueprint_not_validated", "Phiên bản không còn hợp lệ; hãy xem báo cáo kiểm tra."
        )
    now = utcnow()
    if blueprint.current_version_id is not None and blueprint.current_version_id != version.id:
        previous = await db.scalar(
            select(BlueprintVersion)
            .where(
                BlueprintVersion.workspace_id == blueprint.workspace_id,
                BlueprintVersion.blueprint_id == blueprint.id,
                BlueprintVersion.id == blueprint.current_version_id,
            )
            .with_for_update()
        )
        if previous is not None and previous.status == "published":
            previous.status = "archived"
    version.status = "published"
    version.published_at = now
    version.published_by_user_id = scope.user.id
    blueprint.current_version_id = version.id
    blueprint.status = "published"
    blueprint.updated_at = now
    await db.flush()
    return version


def blueprint_listing(workspace_id: UUID, *, status: str | None = None):
    query = select(Blueprint).where(Blueprint.workspace_id == workspace_id)
    if status is not None:
        query = query.where(Blueprint.status == status)
    return query
