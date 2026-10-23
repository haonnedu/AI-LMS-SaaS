"""Manual content authoring without PostgreSQL: body schema, optimistic concurrency, autosave
only on drafts, review/publish transitions and the four-eyes approval rule."""

from uuid import UUID, uuid4

import pytest
from authoring_fakes import FakeSession, scope

from app.models.authoring import ContentItem, ContentRevision, ReviewRequest
from app.models.knowledge import CurriculumUnit
from app.services import content
from app.services.authoring_common import Conflict, Forbidden, Invalid, NotFound, RevisionConflict

CHUNK = str(uuid4())


def body(text="Mục tiêu bài học", citations=None):
    return {
        "sections": [
            {
                "heading": "I. Mục tiêu",
                "blocks": [
                    {"type": "objective", "text": text, "citations": citations or []},
                    {"type": "paragraph", "text": ""},
                ],
            }
        ]
    }


# ---- Pure schema validation -----------------------------------------------------------------


def test_valid_body_is_normalised_and_hash_is_stable():
    clean = content.validate_body(body(citations=[{"chunkId": CHUNK.upper(), "label": "Tr. 3"}]))
    block = clean["sections"][0]["blocks"][0]
    assert block["citations"] == [{"chunkId": CHUNK, "label": "Tr. 3"}]
    assert clean["sections"][0]["blocks"][1]["citations"] == []  # default filled in
    assert content.body_sha256(clean) == content.body_sha256(content.validate_body(clean))
    assert len(content.body_sha256(clean)) == 32
    assert content.cited_chunk_ids(clean) == {UUID(CHUNK)}
    assert content.validate_body({"sections": []}) == {"sections": []}


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"sections": {}},
        {"sections": [], "extra": 1},
        {"sections": [{"heading": "", "blocks": []}]},
        {"sections": [{"heading": "x" * 301, "blocks": []}]},
        {"sections": [{"heading": "A"}]},
        {"sections": [{"heading": "A", "blocks": [{"type": "video", "text": "x"}]}]},
        {"sections": [{"heading": "A", "blocks": [{"type": "note", "text": 3}]}]},
        {"sections": [{"heading": "A", "blocks": [{"type": "note", "text": "x", "html": "<b>"}]}]},
        {
            "sections": [
                {
                    "heading": "A",
                    "blocks": [
                        {
                            "type": "note",
                            "text": "x",
                            "citations": [{"chunkId": "nope", "label": "a"}],
                        }
                    ],
                }
            ]
        },
        {
            "sections": [
                {
                    "heading": "A",
                    "blocks": [
                        {
                            "type": "note",
                            "text": "x",
                            "citations": [{"chunkId": CHUNK, "label": ""}],
                        }
                    ],
                }
            ]
        },
        {"sections": [{"heading": "A", "blocks": [{"type": "note", "text": "x" * 20001}]}]},
    ],
)
def test_invalid_bodies_are_rejected(bad):
    with pytest.raises(Invalid) as error:
        content.validate_body(bad)
    assert error.value.code == "invalid_content_body"
    assert error.value.status == 422


def test_body_size_limit_is_200kb():
    blocks = [{"type": "paragraph", "text": "a" * 19000} for _ in range(12)]
    with pytest.raises(Invalid) as error:
        content.validate_body({"sections": [{"heading": "A", "blocks": blocks}]})
    assert error.value.code == "content_too_large"


@pytest.mark.parametrize(
    "author_is_reviewer,staff,allowed",
    [(False, 5, True), (True, 1, True), (True, 2, False), (True, None, False), (False, 1, True)],
)
def test_four_eyes_rule(author_is_reviewer, staff, allowed):
    author = uuid4()
    reviewer = author if author_is_reviewer else uuid4()
    assert content.may_approve(author_id=author, reviewer_id=reviewer, staff_count=staff) is allowed


# ---- Service flows with an in-memory session ------------------------------------------------


@pytest.fixture
def db():
    return FakeSession()


@pytest.fixture
def author():
    return scope()


async def make_item(db, author, **kwargs):
    return await content.create_item(
        db, author, kind="lesson_plan", title="Giáo án", body=body(), **kwargs
    )


async def test_create_item_starts_with_draft_revision_one(db, author):
    item, revision = await make_item(db, author)
    assert item.latest_revision_no == 1 and item.status == "draft"
    assert item.current_revision_id is None
    assert revision.revision_no == 1 and revision.status == "draft"
    assert revision.body_sha256 == content.body_sha256(revision.body)
    assert db.all(ContentRevision) == [revision]


async def test_unknown_unit_or_kind_rejected(db, author):
    with pytest.raises(Invalid) as error:
        await make_item(db, author, curriculum_unit_id=uuid4())
    assert error.value.code == "curriculum_unit_not_found"
    with pytest.raises(Invalid):
        await content.create_item(db, author, kind="exam", title="x")
    unit = CurriculumUnit(id=uuid4())
    db.add(unit)
    item, _ = await make_item(db, author, curriculum_unit_id=unit.id)
    assert item.curriculum_unit_id == unit.id


async def test_new_revision_requires_current_expected_number(db, author):
    item, first = await make_item(db, author)
    second = await content.create_revision(
        db, author, item.id, expected_revision_no=1, body=body("v2")
    )
    assert second.revision_no == 2 and second.based_on_revision_id == first.id
    assert item.latest_revision_no == 2
    with pytest.raises(RevisionConflict) as error:
        await content.create_revision(db, author, item.id, expected_revision_no=1, body=body("x"))
    assert error.value.status == 409 and error.value.code == "revision_conflict"
    assert error.value.latest == 2
    assert len(db.all(ContentRevision)) == 2


async def test_cross_workspace_item_is_not_found(db, author):
    item, _ = await make_item(db, author)
    other = scope()
    with pytest.raises(NotFound):
        await content.create_revision(db, other, item.id, expected_revision_no=1, body=body())
    item.deleted_at = item.created_at
    with pytest.raises(NotFound):
        await content.load_item(db, author.workspace.id, item.id)


async def test_autosave_updates_draft_in_place(db, author):
    item, revision = await make_item(db, author)
    before = revision.body_sha256
    saved = await content.save_draft(db, author, item.id, expected_revision_no=1, body=body("Mới"))
    assert saved is revision and saved.revision_no == 1
    assert saved.body_sha256 != before
    assert saved.body["sections"][0]["blocks"][0]["text"] == "Mới"
    assert len(db.all(ContentRevision)) == 1
    with pytest.raises(RevisionConflict):
        await content.save_draft(db, author, item.id, expected_revision_no=2, body=body())


async def test_autosave_refused_once_submitted(db, author):
    item, revision = await make_item(db, author)
    await content.submit_for_review(db, author, item.id, 1)
    assert revision.status == "in_review" and item.status == "in_review"
    frozen = revision.body_sha256
    with pytest.raises(Conflict) as error:
        await content.save_draft(db, author, item.id, expected_revision_no=1, body=body("x"))
    assert error.value.code == "revision_not_draft"
    assert revision.body_sha256 == frozen
    requests = db.all(ReviewRequest)
    assert len(requests) == 1 and requests[0].status == "open"
    with pytest.raises(Conflict):
        await content.submit_for_review(db, author, item.id, 1)


async def test_submit_assignee_must_be_staff(db, author):
    item, _ = await make_item(db, author)
    with pytest.raises(Invalid) as error:
        await content.submit_for_review(db, author, item.id, 1, assigned_to=uuid4())
    assert error.value.code == "invalid_assignee"
    reviewer = uuid4()
    db.staff_roles[reviewer] = "teacher"
    await content.submit_for_review(db, author, item.id, 1, assigned_to=reviewer)
    assert db.all(ReviewRequest)[0].assigned_to_user_id == reviewer


async def test_author_cannot_self_approve_with_other_staff(db, author):
    item, _ = await make_item(db, author)
    await content.submit_for_review(db, author, item.id, 1)
    db.staff_count = 3
    with pytest.raises(Forbidden) as error:
        await content.approve(db, author, item.id, 1)
    assert error.value.code == "self_approval_forbidden"
    reviewer = scope(author.workspace.id)
    approved = await content.approve(db, reviewer, item.id, 1, comment="Tốt")
    assert approved.status == "approved"
    assert approved.reviewed_by_user_id == reviewer.user.id and approved.reviewed_at
    request = db.all(ReviewRequest)[0]
    assert request.status == "approved" and request.decided_by_user_id == reviewer.user.id


async def test_sole_teacher_may_self_approve_and_publish(db, author):
    db.staff_count = 1
    item, revision = await make_item(db, author)
    with pytest.raises(Conflict) as error:
        await content.publish(db, author, item.id, 1)
    assert error.value.code == "revision_not_approved"
    with pytest.raises(Conflict):
        await content.approve(db, author, item.id, 1)  # still a draft
    await content.submit_for_review(db, author, item.id, 1)
    await content.approve(db, author, item.id, 1)
    published = await content.publish(db, author, item.id, 1)
    assert published.status == "published" and published.published_at
    assert item.current_revision_id == revision.id and item.status == "published"


async def test_publishing_newer_revision_archives_previous(db, author):
    db.staff_count = 1
    item, first = await make_item(db, author)
    for number in (1,):
        await content.submit_for_review(db, author, item.id, number)
        await content.approve(db, author, item.id, number)
        await content.publish(db, author, item.id, number)
    second = await content.create_revision(db, author, item.id, expected_revision_no=1, body=body())
    # A draft can coexist with the published revision.
    assert item.current_revision_id == first.id and second.status == "draft"
    await content.submit_for_review(db, author, item.id, 2)
    await content.approve(db, author, item.id, 2)
    await content.publish(db, author, item.id, 2)
    assert first.status == "archived" and first.published_at is not None
    assert item.current_revision_id == second.id


async def test_archived_item_rejects_new_revision(db, author):
    item, _ = await make_item(db, author)
    item.status = "archived"
    with pytest.raises(Conflict) as error:
        await content.create_revision(db, author, item.id, expected_revision_no=1, body=body())
    assert error.value.code == "content_archived"


async def test_list_revisions_newest_first(db, author):
    item, _ = await make_item(db, author)
    await content.create_revision(db, author, item.id, expected_revision_no=1, body=body())
    rows = await content.list_revisions(db, item)
    assert [r.revision_no for r in rows] == [2, 1]
    assert isinstance(db.all(ContentItem)[0], ContentItem)
