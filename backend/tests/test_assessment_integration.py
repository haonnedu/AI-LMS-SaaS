"""Real PostgreSQL verification of assignments, attempts, grading and releases (M5/M6).

Use only a disposable *_test database (``AUTH_TEST_DATABASE_URL``, superuser/migrator). Covers:
invite -> join -> assign -> start -> autosave -> submit -> grade -> release with two students;
student B cannot read or write A's attempt; stale and late answers are rejected; a concurrent
double submit yields one snapshot and one grading job; the deadline sweeper finalizes an expired
attempt; a teacher override appends a revision that students see only after re-release.
"""

import asyncio
import json
import os
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.api import assignments as teacher_api
from app.api import classes as classes_api
from app.api import student as student_api
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services import jobs as job_service

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)
ISSUER = "https://identity.example/"
CHOICES = [{"key": "A", "text": "Một"}, {"key": "B", "text": "Hai"}, {"key": "C", "text": "Ba"}]


def runtime_url():
    return make_url(ADMIN_URL).set(username="eduvia_runtime", password="runtime_test_only")


@pytest.fixture(scope="module")
def database():
    assert ADMIN_URL and ADMIN_URL.rsplit("/", 1)[-1].endswith("_test"), "Test database required"
    engine = create_engine(ADMIN_URL)
    with engine.begin() as db:
        db.execute(text("DROP SCHEMA IF EXISTS edu CASCADE"))
        db.execute(text("DROP TABLE IF EXISTS public.alembic_version"))
        db.execute(
            text("""DO $$ BEGIN
        IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='eduvia_runtime') THEN
          CREATE ROLE eduvia_runtime LOGIN PASSWORD 'runtime_test_only'
            NOSUPERUSER NOCREATEROLE NOBYPASSRLS;
        END IF;
        END $$;""")
        )
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = ADMIN_URL
    get_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if old is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old
        get_settings.cache_clear()
    with engine.begin() as db:
        db.execute(text("GRANT USAGE ON SCHEMA edu TO eduvia_runtime"))
        database_name = engine.dialect.identifier_preparer.quote(engine.url.database)
        db.execute(text(f"GRANT CONNECT ON DATABASE {database_name} TO eduvia_runtime"))
    yield engine
    engine.dispose()


@pytest.fixture
def worker_sessions(database):
    engine = create_engine(runtime_url())
    yield sessionmaker(engine, expire_on_commit=False, autoflush=False)
    engine.dispose()


@pytest.fixture
async def api(database, monkeypatch):
    classes_api.token_limiter.reset()
    classes_api.ip_limiter.reset()
    monkeypatch.setattr(job_service, "send_job", lambda *args, **kwargs: None)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=runtime_url().render_as_string(hide_password=False),
        auth_issuer=ISSUER,
        auth_audience="eduvia-api",
        auth_jwks_url="https://identity.example/jwks",
        db_pool_size=3,
        db_max_overflow=3,
    )
    app = create_app(settings)
    paths = {getattr(route, "path", "") for route in app.routes}
    for router in (classes_api.router, teacher_api.router, student_api.router):
        if not any(route.path in paths for route in router.routes):
            app.include_router(router)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks.get_signing_key_from_jwt = Mock(
        return_value=SimpleNamespace(key=key.public_key())
    )

    def headers(subject, name="Người dùng"):
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": "eduvia-api",
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            CLAIM_NAMESPACE + "email": subject + "@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
            CLAIM_NAMESPACE + "name": name,
        }
        token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "t"})
        return {"Authorization": "Bearer " + token}

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, headers


async def person(client, headers, prefix, name="Người dùng"):
    subject = prefix + "-" + str(uuid4())
    response = await client.post("/v1/auth/bootstrap", headers=headers(subject, name))
    assert response.status_code == 200, response.text
    body = response.json()
    return SimpleNamespace(
        subject=subject,
        id=body["user"]["id"],
        workspace=body["personalWorkspace"]["id"],
        h=headers(subject, name),
    )


def published_exam(database, teacher, keys=("A", "B")):
    """Draft version + items + keys, then publish (validated by the 0010 version guard)."""
    with database.begin() as db:
        db.execute(
            text(
                "SELECT set_config('edu.issuer', :iss, true), "
                "set_config('edu.subject', :sub, true), "
                "set_config('edu.current_user_id', :user, true), "
                "set_config('edu.current_workspace_id', :ws, true)"
            ),
            {"iss": ISSUER, "sub": teacher.subject, "user": teacher.id, "ws": teacher.workspace},
        )
        ids = {"ws": teacher.workspace, "user": teacher.id}
        exam = db.scalar(
            text(
                "INSERT INTO edu.exams(workspace_id, title, created_by_user_id) "
                "VALUES (:ws, 'Kiểm tra 15 phút', :user) RETURNING id"
            ),
            ids,
        )
        version = db.scalar(
            text(
                "INSERT INTO edu.exam_versions(workspace_id, exam_id, version_no, total_points) "
                "VALUES (:ws, :exam, 1, :total) RETURNING id"
            ),
            ids | {"exam": exam, "total": len(keys)},
        )
        items = []
        for position, key in enumerate(keys, 1):
            item = db.scalar(
                text(
                    "INSERT INTO edu.exam_items(workspace_id, exam_version_id, position, stem, "
                    "choices, points) VALUES (:ws, :version, :position, :stem, "
                    "CAST(:choices AS jsonb), 1.00) RETURNING id"
                ),
                ids
                | {
                    "version": version,
                    "position": position,
                    "stem": f"Câu {position}",
                    "choices": json.dumps(CHOICES),
                },
            )
            db.execute(
                text(
                    "INSERT INTO edu.exam_answer_keys(exam_item_id, workspace_id, "
                    "exam_version_id, correct_key, explanation) "
                    "VALUES (:item, :ws, :version, :key, :why)"
                ),
                ids | {"item": item, "version": version, "key": key, "why": f"Giải thích {key}"},
            )
            items.append(str(item))
        db.execute(
            text(
                "UPDATE edu.exam_versions SET status = 'published', "
                "published_at = clock_timestamp(), published_by_user_id = :user, "
                "content_hash = sha256(CAST('v1' AS bytea)) WHERE id = :version"
            ),
            ids | {"version": version},
        )
    return str(version), items


async def setup_class(client, headers, database):
    teacher = await person(client, headers, "teacher", "Cô Lan")
    s1 = await person(client, headers, "student-a", "Nguyễn Văn A")
    s2 = await person(client, headers, "student-b", "Trần Thị B")
    created = await client.post(
        f"/v1/workspaces/{teacher.workspace}/classes", json={"name": "10A1"}, headers=teacher.h
    )
    assert created.status_code == 201, created.text
    class_id = created.json()["id"]
    invite = await client.post(
        f"/v1/workspaces/{teacher.workspace}/classes/{class_id}/invitations",
        json={"maxUses": 5},
        headers=teacher.h,
    )
    token = invite.json()["token"]
    for student in (s1, s2):
        joined = await client.post(f"/v1/invitations/{token}/accept", headers=student.h)
        assert joined.status_code == 200, joined.text
        # Adult students: the consent gate (migration 0016) must not block attempt start here.
        adult = await client.put(
            "/v1/student/me/birth-year", json={"birthYear": 2000}, headers=student.h
        )
        assert adult.status_code == 200, adult.text
    version, items = published_exam(database, teacher)
    return teacher, s1, s2, class_id, version, items


async def assign(client, teacher, class_id, version, **overrides):
    now = datetime.now(UTC)
    body = {
        "examVersionId": version,
        "title": "Kiểm tra 15 phút",
        "opensAt": (now - timedelta(minutes=1)).isoformat(),
        "closesAt": (now + timedelta(hours=1)).isoformat(),
        "timeLimitSeconds": 1200,
        "maxAttempts": 1,
        "timezone": "Asia/Ho_Chi_Minh",
        "scoreRelease": "immediate",
        "solutionRelease": "manual",
    } | overrides
    base = f"/v1/workspaces/{teacher.workspace}"
    created = await client.post(
        f"{base}/classes/{class_id}/assignments", json=body, headers=teacher.h
    )
    assert created.status_code == 201, created.text
    assignment = created.json()
    assert assignment["status"] == "draft"
    published = await client.post(
        f"{base}/assignments/{assignment['id']}/publish", headers=teacher.h
    )
    assert published.status_code == 200, published.text
    return published.json()


async def answer(client, student, attempt, item, key, expected, sequence):
    return await client.put(
        f"/v1/student/attempts/{attempt}/answers/{item}",
        json={"selectedKey": key, "expectedRevision": expected, "clientSequence": sequence},
        headers=student.h,
    )


def grade_jobs(database, attempt):
    with database.connect() as db:
        return list(
            db.execute(
                text(
                    "SELECT id FROM edu.background_jobs WHERE kind = 'attempt.grade' "
                    "AND input->>'attemptId' = :attempt"
                ),
                {"attempt": attempt},
            ).scalars()
        )


def run_grading(worker_sessions, job_id):
    from app.tasks import jobs as tasks

    return tasks.execute_job(job_id, sessions=worker_sessions, store=None)


async def test_full_flow_two_students(api, database, worker_sessions):
    client, headers = api
    teacher, s1, s2, class_id, version, items = await setup_class(client, headers, database)
    assignment = await assign(client, teacher, class_id, version)
    aid = assignment["id"]
    base = f"/v1/workspaces/{teacher.workspace}/assignments/{aid}"

    listed = (await client.get("/v1/student/assignments", headers=s1.h)).json()["items"]
    assert [(a["id"], a["availability"]) for a in listed] == [(aid, "open")]
    # The teacher is not enrolled: the student surface shows nothing.
    assert (
        await client.get(f"/v1/student/assignments/{aid}", headers=teacher.h)
    ).status_code == 404

    url = f"/v1/student/assignments/{aid}/attempts"
    first = await client.post(url, headers=s1.h | {"Idempotency-Key": "start-1"})
    assert first.status_code == 201, first.text
    attempt = first.json()["attemptId"]
    other_key = await client.post(url, headers=s1.h | {"Idempotency-Key": "start-2"})
    assert other_key.status_code == 200 and other_key.json()["attemptId"] == attempt
    assert first.json()["deadlineAt"] is not None

    view = await client.get(f"/v1/student/attempts/{attempt}", headers=s1.h)
    assert view.status_code == 200 and len(view.json()["items"]) == 2
    assert "correctKey" not in view.text and "Giải thích" not in view.text

    assert (await answer(client, s1, attempt, items[0], "A", 0, 1)).json()["answerRevision"] == 1
    stale = await answer(client, s1, attempt, items[0], "B", 0, 1)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_answer"
    assert (await answer(client, s1, attempt, items[1], "C", 0, 2)).status_code == 200
    invalid = await answer(client, s1, attempt, items[1], "E", 1, 3)
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_option"

    # Student B can neither read nor write A's attempt; nor can another teacher workspace.
    for response in (
        await client.get(f"/v1/student/attempts/{attempt}", headers=s2.h),
        await client.get(f"/v1/student/attempts/{attempt}/results", headers=s2.h),
        await answer(client, s2, attempt, items[0], "B", 1, 9),
        await client.post(
            f"/v1/student/attempts/{attempt}/submit", headers=s2.h | {"Idempotency-Key": "x"}
        ),
    ):
        assert response.status_code == 404, response.text
    outsider = await person(client, headers, "teacher-b")
    spoof = await client.get(
        f"/v1/workspaces/{outsider.workspace}/assignments/{aid}", headers=outsider.h
    )
    assert spoof.status_code == 404

    submit_url = f"/v1/student/attempts/{attempt}/submit"
    submitted = await client.post(submit_url, headers=s1.h | {"Idempotency-Key": "submit-1"})
    assert submitted.status_code == 200, submitted.text
    replay = await client.post(submit_url, headers=s1.h | {"Idempotency-Key": "submit-1"})
    assert replay.json()["replayed"] is True
    assert replay.json()["snapshotSha256"] == submitted.json()["snapshotSha256"]
    late = await answer(client, s1, attempt, items[1], "B", 1, 4)
    assert late.status_code == 409 and late.json()["error"]["code"] == "attempt_closed"

    # Student B: concurrent double submit -> one snapshot, one grading job.
    b_attempt = (await client.post(url, headers=s2.h | {"Idempotency-Key": "b-start"})).json()[
        "attemptId"
    ]
    await answer(client, s2, b_attempt, items[0], "C", 0, 1)
    b_url = f"/v1/student/attempts/{b_attempt}/submit"
    both = await asyncio.gather(
        client.post(b_url, headers=s2.h | {"Idempotency-Key": "b-1"}),
        client.post(b_url, headers=s2.h | {"Idempotency-Key": "b-2"}),
    )
    assert [r.status_code for r in both] == [200, 200], [r.text for r in both]
    assert both[0].json()["snapshotSha256"] == both[1].json()["snapshotSha256"]
    assert sorted(r.json()["replayed"] for r in both) == [False, True]
    assert len(grade_jobs(database, b_attempt)) == 1

    # Before grading: pending, never zero.
    pending = (await client.get(f"/v1/student/attempts/{attempt}/results", headers=s1.h)).json()
    assert pending["gradingStatus"] == "pending" and pending["score"] is None

    [job] = grade_jobs(database, attempt)
    assert run_grading(worker_sessions, job) == "succeeded"
    graded = (await client.get(f"/v1/student/attempts/{attempt}/results", headers=s1.h)).json()
    assert graded["gradingStatus"] == "graded" and graded["scoreReleased"] is True
    assert (graded["score"], graded["maxScore"]) == ("1.00", "2.00")
    assert all(item["solution"] is None for item in graded["items"])

    results = (await client.get(f"{base}/results", headers=teacher.h)).json()
    assert results["denominators"] == {
        "enrolled": 2,
        "started": 2,
        "submitted": 2,
        "graded": 1,
        "pending": 1,
    }
    by_student = {row["displayName"]: row for row in results["items"]}
    assert by_student["Trần Thị B"]["score"] is None
    assert by_student["Trần Thị B"]["gradingStatus"] == "pending"
    [b_job] = grade_jobs(database, b_attempt)
    assert run_grading(worker_sessions, b_job) == "succeeded"

    detail = (await client.get(f"{base}/attempts/{attempt}", headers=teacher.h)).json()
    assert [i["correctKey"] for i in detail["items"]] == ["A", "B"]
    assert [i["awardedPoints"] for i in detail["items"]] == ["1.00", "0.00"]

    # Solutions only once no new attempts are possible.
    early = await client.post(f"{base}/release-solutions", headers=teacher.h)
    assert early.status_code == 409 and early.json()["error"]["code"] == "assignment_still_open"
    assert (await client.post(f"{base}/close", headers=teacher.h)).status_code == 200
    released = await client.post(f"{base}/release-solutions", headers=teacher.h)
    assert released.status_code == 200 and released.json()["solutionsReleasedAt"]
    solved = (await client.get(f"/v1/student/attempts/{attempt}/results", headers=s1.h)).json()
    assert [i["solution"]["correctKey"] for i in solved["items"]] == ["A", "B"]

    # Override: reason required; appended revision visible to the student only after release.
    override_url = f"{base}/attempts/{attempt}/override"
    assert (
        await client.post(override_url, json={"score": "2.00"}, headers=teacher.h)
    ).status_code == 422
    override = await client.post(
        override_url,
        json={"score": "2.00", "reason": "Phúc khảo: chấp nhận cách làm khác"},
        headers=teacher.h,
    )
    assert override.status_code == 201, override.text
    assert override.json()["revisionNo"] == 2 and override.json()["released"] is False
    still = (await client.get(f"/v1/student/attempts/{attempt}/results", headers=s1.h)).json()
    assert still["score"] == "1.00"
    teacher_view = (await client.get(f"{base}/results", headers=teacher.h)).json()
    scores = {row["displayName"]: row["score"] for row in teacher_view["items"]}
    assert scores == {"Nguyễn Văn A": "2.00", "Trần Thị B": "0.00"}
    rerelease = await client.post(f"{base}/release-scores", headers=teacher.h)
    assert rerelease.status_code == 200 and rerelease.json()["releasedGrades"] >= 1
    final = (await client.get(f"/v1/student/attempts/{attempt}/results", headers=s1.h)).json()
    assert final["score"] == "2.00"
    with database.connect() as db:
        rows = db.execute(
            text("SELECT revision_no, is_current FROM edu.grades WHERE attempt_id = :a"),
            {"a": attempt},
        ).all()
    assert sorted(rows) == [(1, False), (2, True)]


async def test_late_answer_rejected_and_sweeper_expires(api, database, worker_sessions):
    from app.tasks import jobs as tasks

    client, headers = api
    teacher, s1, _, class_id, version, items = await setup_class(client, headers, database)
    assignment = await assign(client, teacher, class_id, version, timeLimitSeconds=60)
    started = await client.post(
        f"/v1/student/assignments/{assignment['id']}/attempts",
        headers=s1.h | {"Idempotency-Key": "late-1"},
    )
    attempt = started.json()["attemptId"]
    assert (await answer(client, s1, attempt, items[0], "A", 0, 1)).status_code == 200
    with database.begin() as db:
        # Test-only time travel; the attempt guard (identity/deadline) is bypassed on purpose.
        db.execute(text("SET LOCAL session_replication_role = replica"))
        db.execute(
            text(
                "UPDATE edu.quiz_attempts SET started_at = clock_timestamp() - interval '10 min', "
                "deadline_at = clock_timestamp() - interval '9 min' WHERE id = :a"
            ),
            {"a": attempt},
        )
    late = await answer(client, s1, attempt, items[1], "B", 0, 2)
    assert late.status_code == 409 and late.json()["error"]["code"] == "attempt_expired"

    sent = []
    summary = tasks.sweep_assessments(
        sessions=worker_sessions, send=lambda *args: sent.append(args)
    )
    assert summary["expired"] >= 1
    with database.connect() as db:
        row = db.execute(
            text(
                "SELECT status, submission_reason, submitted_at = deadline_at AS at_deadline "
                "FROM edu.quiz_attempts WHERE id = :a"
            ),
            {"a": attempt},
        ).one()
    assert tuple(row) == ("submitted", "deadline", True)
    [job] = grade_jobs(database, attempt)
    assert (job, "attempt.grade") in sent
    again = await client.post(
        f"/v1/student/attempts/{attempt}/submit", headers=s1.h | {"Idempotency-Key": "late-s"}
    )
    assert again.status_code == 200
    assert again.json()["replayed"] is True and again.json()["submissionReason"] == "deadline"
    # A second sweep finds nothing new for this attempt and enqueues no duplicate job.
    tasks.sweep_assessments(sessions=worker_sessions, send=lambda *args: None)
    assert len(grade_jobs(database, attempt)) == 1


async def test_published_pin_is_immutable(api, database):
    client, headers = api
    teacher, _, _, class_id, version, _ = await setup_class(client, headers, database)
    assignment = await assign(client, teacher, class_id, version)
    with pytest.raises(Exception) as caught:
        with database.begin() as db:
            db.execute(
                text("UPDATE edu.assignments SET max_attempts = 3 WHERE id = :a"),
                {"a": assignment["id"]},
            )
    assert "immutable" in str(caught.value)
    base = f"/v1/workspaces/{teacher.workspace}/assignments/{assignment['id']}"
    earlier = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    shorter = await client.post(f"{base}/extend", json={"closesAt": earlier}, headers=teacher.h)
    assert shorter.status_code == 422
    later = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    extended = await client.post(f"{base}/extend", json={"closesAt": later}, headers=teacher.h)
    assert extended.status_code == 200, extended.text
