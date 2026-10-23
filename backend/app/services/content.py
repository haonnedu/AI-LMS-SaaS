"""Manual lesson-plan / study-guide authoring (AUTHR-01, AUTHR-02 backend).

Everything here is deterministic and provider-free, so an AI outage never blocks writing,
autosaving, submitting, approving or publishing. Concurrency model: the item row is locked
(``FOR UPDATE``) and ``content_items.latest_revision_no`` is the optimistic-concurrency token;
a stale ``expected_revision_no`` raises ``RevisionConflict`` (409 ``revision_conflict``).
The database trigger independently freezes every non-draft revision body.
"""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from app.models.authoring import CONTENT_KINDS, ContentItem, ContentRevision, ReviewRequest
from app.models.knowledge import CurriculumUnit
from app.services.authoring_common import (
    Conflict,
    Forbidden,
    Invalid,
    NotFound,
    Scope,
    canonical_json,
    check_expected,
    parse_uuid,
    sha256_json,
    utcnow,
)

MAX_BODY_BYTES = 200 * 1024
MAX_SECTIONS = 200
MAX_BLOCKS = 500
MAX_CITATIONS = 20
MAX_HEADING = 300
MAX_TEXT = 20000
MAX_LABEL = 200
BLOCK_TYPES = frozenset({"paragraph", "list", "objective", "activity", "note"})
AUDIENCES = frozenset({"teacher", "student"})
EMPTY_BODY: dict[str, Any] = {"sections": []}

ITEM_NOT_FOUND = ("content_not_found", "Không tìm thấy nội dung.")
REVISION_NOT_FOUND = ("revision_not_found", "Không tìm thấy phiên bản nội dung.")


# ---- Pure helpers ---------------------------------------------------------------------------


def _invalid(path: str, message: str) -> Invalid:
    return Invalid("invalid_content_body", f"Nội dung không hợp lệ tại {path}: {message}")


def _text(value: Any, path: str, *, max_length: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _invalid(path, "phải là chuỗi ký tự.")
    if not allow_empty and not value.strip():
        raise _invalid(path, "không được để trống.")
    if len(value) > max_length:
        raise _invalid(path, f"vượt quá {max_length} ký tự.")
    return value


def _keys(value: Any, path: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(value, dict):
        raise _invalid(path, "phải là đối tượng JSON.")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing:
        raise _invalid(path, f"thiếu trường {', '.join(sorted(missing))}.")
    if extra:
        raise _invalid(path, f"có trường không được hỗ trợ {', '.join(sorted(extra))}.")
    return value


def validate_body(body: Any) -> dict[str, Any]:
    """Validate and normalise a revision body; returns a fresh dict safe to store.

    Shape: ``{"sections": [{"heading", "blocks": [{"type", "text", "citations": [{"chunkId",
    "label"}]}]}]}``. Citations must be chunk UUIDs; existence/authorization of the chunk is
    checked later by AUTHR-04 (review), never trusted from the client here.
    """
    _keys(body, "body", {"sections"})
    sections = body["sections"]
    if not isinstance(sections, list) or len(sections) > MAX_SECTIONS:
        raise _invalid("sections", f"phải là danh sách tối đa {MAX_SECTIONS} mục.")
    normalised = []
    for s_index, section in enumerate(sections):
        path = f"sections[{s_index}]"
        _keys(section, path, {"heading", "blocks"})
        heading = _text(section["heading"], f"{path}.heading", max_length=MAX_HEADING)
        blocks = section["blocks"]
        if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS:
            raise _invalid(f"{path}.blocks", f"phải là danh sách tối đa {MAX_BLOCKS} khối.")
        out_blocks = []
        for b_index, block in enumerate(blocks):
            b_path = f"{path}.blocks[{b_index}]"
            _keys(block, b_path, {"type", "text"}, {"citations"})
            if block["type"] not in BLOCK_TYPES:
                raise _invalid(f"{b_path}.type", "loại khối không được hỗ trợ.")
            text_value = _text(
                block["text"], f"{b_path}.text", max_length=MAX_TEXT, allow_empty=True
            )
            citations = block.get("citations", [])
            if not isinstance(citations, list) or len(citations) > MAX_CITATIONS:
                raise _invalid(
                    f"{b_path}.citations", f"phải là danh sách tối đa {MAX_CITATIONS} trích dẫn."
                )
            out_citations = []
            for c_index, citation in enumerate(citations):
                c_path = f"{b_path}.citations[{c_index}]"
                _keys(citation, c_path, {"chunkId", "label"})
                chunk = parse_uuid(citation["chunkId"])
                if chunk is None:
                    raise _invalid(f"{c_path}.chunkId", "phải là mã đoạn tài liệu (UUID).")
                label = _text(citation["label"], f"{c_path}.label", max_length=MAX_LABEL)
                out_citations.append({"chunkId": str(chunk), "label": label})
            out_blocks.append(
                {"type": block["type"], "text": text_value, "citations": out_citations}
            )
        normalised.append({"heading": heading, "blocks": out_blocks})
    result = {"sections": normalised}
    if len(canonical_json(result)) > MAX_BODY_BYTES:
        raise Invalid("content_too_large", "Nội dung vượt quá giới hạn 200 KB.")
    return result


def body_sha256(body: Mapping[str, Any]) -> bytes:
    return sha256_json(body)


def cited_chunk_ids(body: Mapping[str, Any]) -> set[UUID]:
    return {
        UUID(citation["chunkId"])
        for section in body.get("sections", [])
        for block in section.get("blocks", [])
        for citation in block.get("citations", [])
    }


def may_approve(*, author_id: UUID, reviewer_id: UUID, staff_count: int | None) -> bool:
    """Four-eyes rule: the author may approve only when they are the sole staff member."""
    return author_id != reviewer_id or staff_count == 1


def validate_kind(kind: str) -> str:
    if kind not in CONTENT_KINDS:
        raise Invalid("invalid_content_kind", "Loại nội dung không được hỗ trợ.")
    return kind


def validate_audience(audience: str) -> str:
    if audience not in AUDIENCES:
        raise Invalid("invalid_audience", "Đối tượng sử dụng không hợp lệ.")
    return audience


# ---- Loading --------------------------------------------------------------------------------


async def load_item(db, workspace_id: UUID, item_id: UUID, *, lock: bool = False) -> ContentItem:
    query = select(ContentItem).where(
        ContentItem.id == item_id,
        ContentItem.workspace_id == workspace_id,
        ContentItem.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update()
    item = await db.scalar(query)
    if item is None:
        raise NotFound(*ITEM_NOT_FOUND)
    return item


async def load_revision(
    db, item: ContentItem, revision_no: int, *, lock: bool = False
) -> ContentRevision:
    query = select(ContentRevision).where(
        ContentRevision.workspace_id == item.workspace_id,
        ContentRevision.content_item_id == item.id,
        ContentRevision.revision_no == revision_no,
    )
    if lock:
        query = query.with_for_update()
    revision = await db.scalar(query)
    if revision is None:
        raise NotFound(*REVISION_NOT_FOUND)
    return revision


async def load_revision_by_id(db, item: ContentItem, revision_id: UUID | None):
    if revision_id is None:
        return None
    return await db.scalar(
        select(ContentRevision).where(
            ContentRevision.workspace_id == item.workspace_id,
            ContentRevision.content_item_id == item.id,
            ContentRevision.id == revision_id,
        )
    )


async def ensure_unit(db, unit_id: UUID | None) -> None:
    if unit_id is None:
        return
    found = await db.scalar(select(CurriculumUnit.id).where(CurriculumUnit.id == unit_id))
    if found is None:
        raise Invalid("curriculum_unit_not_found", "Đơn vị chương trình không tồn tại.")


async def staff_count(db, workspace_id: UUID) -> int | None:
    return await db.scalar(select(func.edu.workspace_staff_count(workspace_id)))


async def ensure_staff(db, workspace_id: UUID, user_id: UUID | None) -> None:
    """A review assignee must be active owner/admin/teacher staff of this workspace."""
    if user_id is None:
        return
    role = await db.scalar(select(func.edu.workspace_staff_role(workspace_id, user_id)))
    if role is None:
        raise Invalid("invalid_assignee", "Người duyệt phải là giáo viên của không gian này.")


# ---- Mutations ------------------------------------------------------------------------------


def _new_revision(
    scope: Scope, item: ContentItem, revision_no: int, body: dict, audience: str, based_on=None
) -> ContentRevision:
    now = utcnow()
    return ContentRevision(
        id=uuid4(),
        workspace_id=item.workspace_id,
        content_item_id=item.id,
        revision_no=revision_no,
        body=body,
        audience=audience,
        status="draft",
        based_on_revision_id=based_on,
        created_by_user_id=scope.user.id,
        body_sha256=body_sha256(body),
        created_at=now,
        updated_at=now,
    )


async def create_item(
    db,
    scope: Scope,
    *,
    kind: str,
    title: str,
    curriculum_unit_id: UUID | None = None,
    body: Any = None,
    audience: str = "teacher",
) -> tuple[ContentItem, ContentRevision]:
    validate_kind(kind)
    validate_audience(audience)
    clean = validate_body(EMPTY_BODY if body is None else body)
    await ensure_unit(db, curriculum_unit_id)
    now = utcnow()
    item = ContentItem(
        id=uuid4(),
        workspace_id=scope.workspace.id,
        kind=kind,
        title=title,
        created_by_user_id=scope.user.id,
        status="draft",
        latest_revision_no=1,
        curriculum_unit_id=curriculum_unit_id,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    await db.flush()  # parent row before the composite FK of its first revision
    revision = _new_revision(scope, item, 1, clean, audience)
    db.add(revision)
    await db.flush()
    return item, revision


async def create_revision(
    db,
    scope: Scope,
    item_id: UUID,
    *,
    expected_revision_no: int,
    body: Any,
    audience: str | None = None,
) -> ContentRevision:
    clean = validate_body(body)
    item = await load_item(db, scope.workspace.id, item_id, lock=True)
    check_expected(item.latest_revision_no, expected_revision_no)
    if item.status == "archived":
        raise Conflict("content_archived", "Nội dung đã được lưu trữ, không thể chỉnh sửa.")
    previous = await load_revision(db, item, item.latest_revision_no)
    revision = _new_revision(
        scope,
        item,
        item.latest_revision_no + 1,
        clean,
        validate_audience(audience or previous.audience),
        based_on=previous.id,
    )
    db.add(revision)
    item.latest_revision_no = revision.revision_no
    item.updated_at = revision.created_at
    await db.flush()
    return revision


async def save_draft(
    db, scope: Scope, item_id: UUID, *, expected_revision_no: int, body: Any
) -> ContentRevision:
    """Autosave: overwrite the latest revision in place only while it is still ``draft``."""
    clean = validate_body(body)
    item = await load_item(db, scope.workspace.id, item_id, lock=True)
    check_expected(item.latest_revision_no, expected_revision_no)
    revision = await load_revision(db, item, item.latest_revision_no, lock=True)
    if revision.status != "draft":
        raise Conflict(
            "revision_not_draft",
            "Phiên bản này đã được gửi duyệt hoặc xuất bản; hãy tạo phiên bản mới để chỉnh sửa.",
        )
    now = utcnow()
    revision.body = clean
    revision.body_sha256 = body_sha256(clean)
    revision.updated_at = now
    item.updated_at = now
    await db.flush()
    return revision


async def submit_for_review(
    db, scope: Scope, item_id: UUID, revision_no: int, *, assigned_to: UUID | None = None
) -> ContentRevision:
    item = await load_item(db, scope.workspace.id, item_id, lock=True)
    revision = await load_revision(db, item, revision_no, lock=True)
    if revision.status != "draft":
        raise Conflict("invalid_transition", "Chỉ bản nháp mới có thể gửi duyệt.")
    validate_body(revision.body)  # stored drafts are re-checked before review
    await ensure_staff(db, item.workspace_id, assigned_to)
    now = utcnow()
    revision.status = "in_review"
    revision.updated_at = now
    db.add(
        ReviewRequest(
            id=uuid4(),
            workspace_id=item.workspace_id,
            content_revision_id=revision.id,
            requested_by_user_id=scope.user.id,
            assigned_to_user_id=assigned_to,
            status="open",
            created_at=now,
        )
    )
    if item.status == "draft":
        item.status = "in_review"
    item.updated_at = now
    await db.flush()
    return revision


async def approve(
    db, scope: Scope, item_id: UUID, revision_no: int, *, comment: str | None = None
) -> ContentRevision:
    item = await load_item(db, scope.workspace.id, item_id, lock=True)
    revision = await load_revision(db, item, revision_no, lock=True)
    if revision.status != "in_review":
        raise Conflict("invalid_transition", "Chỉ phiên bản đang chờ duyệt mới có thể duyệt.")
    if revision.created_by_user_id == scope.user.id:
        count = await staff_count(db, item.workspace_id)
        if not may_approve(
            author_id=revision.created_by_user_id, reviewer_id=scope.user.id, staff_count=count
        ):
            raise Forbidden(
                "self_approval_forbidden",
                "Người soạn không thể tự duyệt khi không gian làm việc có giáo viên khác.",
            )
    now = utcnow()
    revision.status = "approved"
    revision.reviewed_by_user_id = scope.user.id
    revision.reviewed_at = now
    revision.updated_at = now
    request = await db.scalar(
        select(ReviewRequest)
        .where(
            ReviewRequest.workspace_id == item.workspace_id,
            ReviewRequest.content_revision_id == revision.id,
            ReviewRequest.status == "open",
        )
        .with_for_update()
    )
    if request is not None:
        request.status = "approved"
        request.decided_by_user_id = scope.user.id
        request.decided_at = now
        request.comment = comment
    item.updated_at = now
    await db.flush()
    return revision


async def publish(db, scope: Scope, item_id: UUID, revision_no: int) -> ContentRevision:
    item = await load_item(db, scope.workspace.id, item_id, lock=True)
    revision = await load_revision(db, item, revision_no, lock=True)
    if revision.status != "approved":
        raise Conflict("revision_not_approved", "Chỉ phiên bản đã duyệt mới có thể xuất bản.")
    now = utcnow()
    previous = await load_revision_by_id(db, item, item.current_revision_id)
    if previous is not None and previous.id != revision.id and previous.status == "published":
        previous.status = "archived"  # payload and publication stamp stay frozen
        previous.updated_at = now
    revision.status = "published"
    revision.published_at = now
    revision.updated_at = now
    item.current_revision_id = revision.id
    item.status = "published"
    item.updated_at = now
    await db.flush()
    return revision


# ---- Queries --------------------------------------------------------------------------------


async def list_revisions(db, item: ContentItem, limit: int = 200) -> Sequence[ContentRevision]:
    rows = await db.scalars(
        select(ContentRevision)
        .where(
            ContentRevision.workspace_id == item.workspace_id,
            ContentRevision.content_item_id == item.id,
        )
        .order_by(ContentRevision.revision_no.desc())
        .limit(limit)
    )
    return list(rows.all())


def item_listing(workspace_id: UUID, *, kind: str | None, status: str | None):
    query = select(ContentItem).where(
        ContentItem.workspace_id == workspace_id, ContentItem.deleted_at.is_(None)
    )
    if kind is not None:
        query = query.where(ContentItem.kind == kind)
    if status is not None:
        query = query.where(ContentItem.status == status)
    return query
