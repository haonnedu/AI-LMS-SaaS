"""Real PostgreSQL verification of the PILOT-05 privacy slice (migration 0016).

Use only a disposable *_test database (``AUTH_TEST_DATABASE_URL``, superuser/migrator). Covers:
an under-age student is blocked from starting an attempt, a guardian consents through a
single-use link, then the start succeeds; staff erasure pseudonymises the student while the
attempt and grade rows remain countable; a self export contains only the requester's data and
no answer keys; no plaintext guardian contact exists anywhere the runtime role can read; self
erasure deactivates the account.
"""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4

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
from app.api import consent_links as public_api
from app.api import privacy as privacy_api
from app.api import student as student_api
from app.api import student_privacy as student_privacy_api
from app.core.auth import CLAIM_NAMESPACE
from app.core.config import Settings, get_settings
from app.main import create_app
from app.services import jobs as job_service

ADMIN_URL = os.getenv("AUTH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="Set AUTH_TEST_DATABASE_URL to disposable PostgreSQL"
)
ISSUER = "https://identity.example/"
CHOICES = [{"key": "A", "text": "Một"}, {"key": "B", "text": "Hai"}]
CONTACT = "phuhuynh.binh@example.com"
UNDER_AGE_YEAR = datetime.now(UTC).year - 12
ADULT_YEAR = datetime.now(UTC).year - 30


def runtime_url():
    return make_url(ADMIN_URL).set(username="eduvia_runtime", password="runtime_test_only")


@pytest.fixture(scope="module")
def database():
    assert ADMIN_URL and ADMIN_URL.rsplit("/", 1)[-1].endswith("_test"), "Test database required"
    engine = create_engine(ADMIN_URL)
    with engine.begin() as db:
        db.execute(text("DROP SCHEMA IF EXISTS edu CASCADE"))
        db.execute(text("DROP SCHEMA IF EXISTS auth CASCADE"))
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


class MemoryStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put(self, key, body, *, mime, size, sha256):
        self.objects[key] = body.read()

    def delete(self, key):
        self.deleted.append(key)
        self.objects.pop(key, None)

    def presign_get(self, key, *, file_name, mime, ttl_seconds):
        return "https://storage.example/signed", datetime.now(UTC) + timedelta(seconds=ttl_seconds)


@pytest.fixture
async def api(database, monkeypatch):
    classes_api.token_limiter.reset()
    classes_api.actor_limiter.reset()
    public_api.token_limiter.reset()
    public_api.global_limiter.reset()
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
    for router in (
        classes_api.router,
        teacher_api.router,
        student_api.router,
        privacy_api.router,
        student_privacy_api.router,
        public_api.router,
    ):
        if not any(route.path in paths for route in router.routes):
            app.include_router(router)
    store = MemoryStore()
    app.state.object_store = store
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
            yield client, headers, store


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


def teacher_context(db, teacher):
    db.execute(
        text(
            "SELECT set_config('edu.issuer', :iss, true), "
            "set_config('edu.subject', :sub, true), "
            "set_config('edu.current_user_id', :user, true), "
            "set_config('edu.current_workspace_id', :ws, true)"
        ),
        {"iss": ISSUER, "sub": teacher.subject, "user": teacher.id, "ws": teacher.workspace},
    )


def published_exam(database, teacher):
    with database.begin() as db:
        teacher_context(db, teacher)
        ids = {"ws": teacher.workspace, "user": teacher.id}
        exam = db.scalar(
            text(
                "INSERT INTO edu.exams(workspace_id, title, created_by_user_id) "
                "VALUES (:ws, 'Kiểm tra', :user) RETURNING id"
            ),
            ids,
        )
        version = db.scalar(
            text(
                "INSERT INTO edu.exam_versions(workspace_id, exam_id, version_no, total_points) "
                "VALUES (:ws, :exam, 1, 1) RETURNING id"
            ),
            ids | {"exam": exam},
        )
        item = db.scalar(
            text(
                "INSERT INTO edu.exam_items(workspace_id, exam_version_id, position, stem, "
                "choices, points) VALUES (:ws, :version, 1, 'Câu 1', CAST(:choices AS jsonb), "
                "1.00) RETURNING id"
            ),
            ids | {"version": version, "choices": json.dumps(CHOICES)},
        )
        db.execute(
            text(
                "INSERT INTO edu.exam_answer_keys(exam_item_id, workspace_id, exam_version_id, "
                "correct_key, explanation) VALUES (:item, :ws, :version, 'A', 'Bí mật đáp án')"
            ),
            ids | {"item": item, "version": version},
        )
        db.execute(
            text(
                "UPDATE edu.exam_versions SET status = 'published', "
                "published_at = clock_timestamp(), published_by_user_id = :user, "
                "content_hash = sha256(CAST('v1' AS bytea)) WHERE id = :version"
            ),
            ids | {"version": version},
        )
    return str(version), str(item)


async def setup(client, headers, database):
    teacher = await person(client, headers, "teacher", "Cô Lan")
    minor = await person(client, headers, "minor", "Nguyễn Văn An")
    adult = await person(client, headers, "adult", "Trần Thị Bích")
    base = f"/v1/workspaces/{teacher.workspace}"
    created = await client.post(f"{base}/classes", json={"name": "10A1"}, headers=teacher.h)
    class_id = created.json()["id"]
    invite = await client.post(
        f"{base}/classes/{class_id}/invitations", json={"maxUses": 5}, headers=teacher.h
    )
    token = invite.json()["token"]
    for student in (minor, adult):
        joined = await client.post(f"/v1/invitations/{token}/accept", headers=student.h)
        assert joined.status_code == 200, joined.text
    version, item = published_exam(database, teacher)
    now = datetime.now(UTC)
    assignment = await client.post(
        f"{base}/classes/{class_id}/assignments",
        json={
            "examVersionId": version,
            "title": "Kiểm tra",
            "opensAt": (now - timedelta(minutes=1)).isoformat(),
            "closesAt": (now + timedelta(hours=1)).isoformat(),
            "maxAttempts": 1,
            "timezone": "Asia/Ho_Chi_Minh",
            "scoreRelease": "immediate",
            "solutionRelease": "manual",
        },
        headers=teacher.h,
    )
    assert assignment.status_code == 201, assignment.text
    aid = assignment.json()["id"]
    published = await client.post(f"{base}/assignments/{aid}/publish", headers=teacher.h)
    assert published.status_code == 200, published.text
    roster = (await client.get(f"{base}/classes/{class_id}/consents", headers=teacher.h)).json()
    ids = {i["displayName"]: i["studentId"] for i in roster["items"]}
    return SimpleNamespace(
        teacher=teacher,
        minor=minor,
        adult=adult,
        base=base,
        class_id=class_id,
        assignment=aid,
        item=item,
        minor_student=ids["Nguyễn Văn An"],
        adult_student=ids["Trần Thị Bích"],
    )


def run_job(worker_sessions, store, job_id):
    from app.tasks import jobs as tasks

    return tasks.execute_job(UUID(str(job_id)), sessions=worker_sessions, store=store)


def admin_scalar(database, sql, **params):
    with database.connect() as db:
        return db.execute(text(sql), params).scalar()


async def test_under_age_student_is_blocked_until_a_guardian_consents(api, database):
    client, headers, _ = api
    s = await setup(client, headers, database)
    start_url = f"/v1/student/assignments/{s.assignment}/attempts"

    # Age unknown -> blocked.
    blocked = await client.post(start_url, headers=s.minor.h | {"Idempotency-Key": "a1"})
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["error"]["code"] == "consent_required"

    declared = await client.put(
        "/v1/student/me/birth-year", json={"birthYear": UNDER_AGE_YEAR}, headers=s.minor.h
    )
    assert declared.status_code == 200, declared.text
    item = declared.json()["items"][0]
    assert item["consentStatus"] == "pending" and item["consentRequired"] is True
    assert item["className"] == "10A1"
    locked = await client.put(
        "/v1/student/me/birth-year", json={"birthYear": ADULT_YEAR}, headers=s.minor.h
    )
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "birth_year_locked"
    again = await client.post(start_url, headers=s.minor.h | {"Idempotency-Key": "a1"})
    assert again.status_code == 403

    # The teacher issues a single-use link; the guardian consents without an account.
    link = await client.post(
        f"{s.base}/students/{s.minor_student}/consent-links", headers=s.teacher.h
    )
    assert link.status_code == 201, link.text
    token = link.json()["token"]
    info = await client.get(f"/v1/public/consent-links/{token}")
    assert info.status_code == 200, info.text
    assert info.json()["studentDisplayName"] == "An"  # given name only
    body = {"guardianName": "Nguyễn Thị Hoa", "guardianContact": CONTACT, "agree": True}
    granted = await client.post(f"/v1/public/consent-links/{token}", json=body)
    assert granted.status_code == 200 and granted.json() == {"status": "granted"}
    reused = await client.post(f"/v1/public/consent-links/{token}", json=body)
    assert reused.status_code == 410
    assert (await client.get(f"/v1/public/consent-links/{'z' * 43}")).status_code == 404

    started = await client.post(start_url, headers=s.minor.h | {"Idempotency-Key": "a1"})
    assert started.status_code == 201, started.text

    roster = (
        await client.get(f"{s.base}/classes/{s.class_id}/consents", headers=s.teacher.h)
    ).json()
    minor_row = next(i for i in roster["items"] if i["studentId"] == s.minor_student)
    assert minor_row["consentStatus"] == "granted"
    assert minor_row["consents"][0]["method"] == "guardian_link"
    assert roster["summary"]["granted"] == 1 and roster["summary"]["unknown"] == 1

    # Adults are not gated once they declare their birth year.
    adult = await client.put(
        "/v1/student/me/birth-year", json={"birthYear": ADULT_YEAR}, headers=s.adult.h
    )
    assert adult.json()["items"][0]["consentStatus"] == "not_required"
    adult_start = await client.post(start_url, headers=s.adult.h | {"Idempotency-Key": "b1"})
    assert adult_start.status_code == 201, adult_start.text


async def test_no_plaintext_guardian_contact_is_readable(api, database):
    client, headers, _ = api
    s = await setup(client, headers, database)
    recorded = await client.post(
        f"{s.base}/students/{s.minor_student}/consents",
        json={
            "method": "paper_school",
            "guardianName": "Lê Văn Cường",
            "guardianContact": "+84 912 345 678",
            "evidenceNote": "Phiếu số 7",
        },
        headers=s.teacher.h,
    )
    assert recorded.status_code == 201, recorded.text
    runtime = create_engine(runtime_url())
    try:
        with runtime.begin() as db:
            teacher_context(db, s.teacher)
            rows = db.execute(text("SELECT * FROM edu.student_consents")).mappings().all()
        assert rows, "runtime sees its own workspace consents"
        for row in rows:
            for value in row.values():
                if isinstance(value, str):
                    assert "912" not in value and "@" not in value
                if isinstance(value, bytes | memoryview):
                    assert b"0912345678" not in bytes(value)
            assert len(bytes(row["guardian_contact_hash"])) == 32
    finally:
        runtime.dispose()


async def test_staff_erasure_keeps_grades_countable(api, database, worker_sessions):
    client, headers, store = api
    s = await setup(client, headers, database)
    paper = await client.post(
        f"{s.base}/students/{s.minor_student}/consents",
        json={"method": "paper_school", "guardianName": "Phạm Thị Dung"},
        headers=s.teacher.h,
    )
    assert paper.status_code == 201, paper.text
    started = await client.post(
        f"/v1/student/assignments/{s.assignment}/attempts",
        headers=s.minor.h | {"Idempotency-Key": "e1"},
    )
    attempt = started.json()["attemptId"]
    saved = await client.put(
        f"/v1/student/attempts/{attempt}/answers/{s.item}",
        json={"selectedKey": "A", "expectedRevision": 0, "clientSequence": 1},
        headers=s.minor.h,
    )
    assert saved.status_code == 200, saved.text
    submitted = await client.post(
        f"/v1/student/attempts/{attempt}/submit", headers=s.minor.h | {"Idempotency-Key": "e2"}
    )
    assert submitted.status_code == 200, submitted.text
    grade_job = admin_scalar(
        database,
        "SELECT id FROM edu.background_jobs WHERE kind = 'attempt.grade' "
        "AND input->>'attemptId' = :attempt",
        attempt=attempt,
    )
    assert run_job(worker_sessions, None, grade_job) == "succeeded"

    export = await client.post(
        f"{s.base}/students/{s.minor_student}/privacy-requests",
        json={"kind": "export"},
        headers=s.teacher.h,
    )
    assert export.status_code == 202, export.text
    assert run_job(worker_sessions, store, export.json()["job"]["id"]) == "succeeded"
    export_id = export.json()["request"]["id"]
    fetched = await client.get(f"{s.base}/privacy-requests/{export_id}", headers=s.teacher.h)
    assert fetched.json()["status"] == "succeeded" and fetched.json()["downloadUrl"]
    key = f"ws/{s.teacher.workspace}/privacy/{export_id}.json"
    assert "Bí mật đáp án" not in store.objects[key].decode()

    erase = await client.post(f"{s.base}/students/{s.minor_student}/erase", headers=s.teacher.h)
    assert erase.status_code == 202, erase.text
    assert run_job(worker_sessions, store, erase.json()["job"]["id"]) == "succeeded"
    assert key in store.deleted and key not in store.objects

    with database.connect() as db:
        student = (
            db.execute(text("SELECT * FROM edu.students WHERE id = :id"), {"id": s.minor_student})
            .mappings()
            .one()
        )
        assert student["display_name"] == "Học sinh đã xóa"
        assert student["user_id"] is None and student["birth_year"] is None
        assert student["erased_at"] is not None and student["consent_status"] == "revoked"
        grades = db.execute(
            text(
                "SELECT count(*) FROM edu.grades g JOIN edu.quiz_attempts q ON q.id = g.attempt_id "
                "WHERE q.student_id = :id"
            ),
            {"id": s.minor_student},
        ).scalar()
        assert grades == 1
        consent = db.execute(
            text(
                "SELECT guardian_name, revoked_at FROM edu.student_consents WHERE student_id = :id"
            ),
            {"id": s.minor_student},
        ).one()
        assert consent.guardian_name is None and consent.revoked_at is not None
    # Replay is a no-op and further consents are refused.
    assert run_job(worker_sessions, store, erase.json()["job"]["id"]) == "not_claimed"
    refused = await client.post(
        f"{s.base}/students/{s.minor_student}/consents",
        json={"method": "paper_school"},
        headers=s.teacher.h,
    )
    assert refused.status_code == 409


async def test_self_export_and_self_erasure(api, database, worker_sessions):
    client, headers, store = api
    s = await setup(client, headers, database)
    await client.put("/v1/student/me/birth-year", json={"birthYear": ADULT_YEAR}, headers=s.adult.h)
    requested = await client.post(
        "/v1/student/me/privacy-requests", json={"kind": "export"}, headers=s.adult.h
    )
    assert requested.status_code == 202, requested.text
    assert run_job(worker_sessions, store, requested.json()["job"]["id"]) == "succeeded"
    request_id = requested.json()["request"]["id"]
    key = f"users/{s.adult.id}/privacy/{request_id}.json"
    exported = json.loads(store.objects[key])
    text_dump = json.dumps(exported, ensure_ascii=False)
    assert exported["profile"]["userId"] == s.adult.id
    assert [st["studentId"] for st in exported["students"]] == [s.adult_student]
    assert "Nguyễn Văn An" not in text_dump and s.minor_student not in text_dump
    assert "correct_key" not in text_dump and "Bí mật đáp án" not in text_dump
    # Another student cannot read it.
    other = await client.get(f"/v1/student/me/privacy-requests/{request_id}", headers=s.minor.h)
    assert other.status_code == 404
    mine = await client.get(f"/v1/student/me/privacy-requests/{request_id}", headers=s.adult.h)
    assert mine.json()["downloadUrl"]

    erase = await client.post(
        "/v1/student/me/privacy-requests", json={"kind": "erasure"}, headers=s.adult.h
    )
    assert erase.status_code == 202, erase.text
    assert run_job(worker_sessions, store, erase.json()["job"]["id"]) == "succeeded"
    assert key in store.deleted
    with database.connect() as db:
        user = db.execute(
            text("SELECT email, display_name, is_active FROM edu.users WHERE id = :id"),
            {"id": s.adult.id},
        ).one()
        assert user.email == f"erased+{s.adult.id}@invalid" and user.is_active is False
        job_status = db.execute(
            text("SELECT status FROM edu.background_jobs WHERE id = :id"),
            {"id": erase.json()["job"]["id"]},
        ).scalar()
        assert job_status == "succeeded"
        student = db.execute(
            text("SELECT display_name, user_id FROM edu.students WHERE id = :id"),
            {"id": s.adult_student},
        ).one()
        assert student.display_name == "Học sinh đã xóa" and student.user_id is None
    gone = await client.get("/v1/student/me/consent-status", headers=s.adult.h)
    assert gone.status_code in {403, 409}
