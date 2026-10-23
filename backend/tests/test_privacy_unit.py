"""Pure privacy rules (PILOT-05) and the export/erasure job handlers with fake sessions."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services import jobs as job_service
from app.services import privacy
from app.tasks import jobs as tasks

TODAY = date(2026, 10, 23)
NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


# ---- Age and consent status ----------------------------------------------------------------


def test_min_age_is_a_conservative_lower_bound():
    assert privacy.min_age(None, TODAY) is None
    assert privacy.min_age(2010, TODAY) == 15  # may already be 16; we assume not yet
    assert privacy.min_age(2009, TODAY) == 16


@pytest.mark.parametrize(
    "status,birth_year,required",
    [
        ("unknown", None, True),
        ("pending", None, True),
        ("revoked", None, True),
        ("unknown", 2012, True),
        ("pending", 2010, True),  # lower bound 15 < 16
        ("pending", 2009, False),  # 16, adult for this rule
        ("revoked", 2000, False),
        ("granted", None, False),
        ("granted", 2014, False),
        ("not_required", None, False),
    ],
)
def test_consent_required_mirrors_the_start_gate(status, birth_year, required):
    assert privacy.consent_required(status, birth_year, 16, TODAY) is required


def test_consent_age_is_a_parameter():
    assert privacy.consent_required("pending", 2012, 13, TODAY) is False
    assert privacy.consent_required("pending", 2012, 18, TODAY) is True


@pytest.mark.parametrize(
    "current,year,expected",
    [
        ("unknown", 2012, "pending"),
        ("pending", 2012, "pending"),
        ("granted", 2012, "granted"),
        ("revoked", 2012, "revoked"),
        ("unknown", 2005, "not_required"),
        ("revoked", 2005, "not_required"),
        ("granted", 2009, "not_required"),
    ],
)
def test_status_after_birth_year(current, year, expected):
    assert privacy.status_after_birth_year(current, year, 16, TODAY) == expected


def test_signup_mode_sends_the_sentinel_age_and_never_requires_consent():
    assert privacy.gate_age("signup", 16) == privacy.SIGNUP_GATE_AGE == 0
    assert privacy.gate_age("guardian", 15) == 15
    for status in privacy.CONSENT_STATUSES:
        for year in (None, 2015, 2000):
            assert privacy.consent_required(status, year, 0, TODAY) is False
            assert privacy.consent_required(status, year, -1, TODAY) is False
    for current in privacy.CONSENT_STATUSES:
        assert privacy.status_after_birth_year(current, 2015, 0, TODAY) == "not_required"


def test_birth_year_validation():
    assert privacy.validate_birth_year(2012, TODAY) == 2012
    for year in (1899, 2027):
        with pytest.raises(privacy.Invalid) as caught:
            privacy.validate_birth_year(year, TODAY)
        assert caught.value.code == "invalid_birth_year"


def test_local_today_uses_vietnam_time():
    assert privacy.local_today(datetime(2026, 12, 31, 18, 0, tzinfo=UTC)) == date(2027, 1, 1)


def test_settings_bounds():
    settings = Settings(_env_file=None)
    assert settings.privacy_consent_age == 16
    assert settings.privacy_policy_version == "2026-10-draft"
    assert settings.privacy_export_url_seconds == 300
    assert settings.privacy_consent_mode == "signup"  # decision 0009
    assert settings.terms_version == "2026-10-draft"
    assert Settings(_env_file=None, privacy_consent_mode="guardian").privacy_consent_mode == (
        "guardian"
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None, privacy_consent_mode="parental")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, terms_version="bad version!")
    for bad in ({"privacy_consent_age": 11}, {"privacy_consent_age": 19}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **bad)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, privacy_export_url_seconds=301)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, privacy_policy_version="bad version!")


# ---- Contact normalisation and hashing ------------------------------------------------------


@pytest.mark.parametrize(
    "raw,normalized",
    [
        ("  Me.Lan@Example.COM ", "me.lan@example.com"),
        ("ｍｅ@example.com", "me@example.com"),  # NFKC folds full-width characters
        ("0912 345 678", "0912345678"),
        ("+84 912-345-678", "0912345678"),
        ("84912345678", "0912345678"),
        ("(091) 234.5678", "0912345678"),
    ],
)
def test_contact_normalisation(raw, normalized):
    assert privacy.normalize_contact(raw) == normalized


@pytest.mark.parametrize("raw", ["", "abc", "12345", "me@", "@example.com", "09x2345678"])
def test_invalid_contacts_are_rejected(raw):
    with pytest.raises(privacy.Invalid) as caught:
        privacy.normalize_contact(raw)
    assert caught.value.code == "invalid_guardian_contact"


def test_contact_hash_is_a_digest_of_the_normalised_value():
    digest = privacy.hash_contact("+84 912 345 678")
    assert digest == privacy.hash_contact("0912345678")
    assert digest == hashlib.sha256(b"0912345678").digest()
    assert len(digest) == 32 and b"0912345678" not in digest
    assert privacy.hash_contact("A@B.vn") == privacy.hash_contact("a@b.vn")


# ---- Tokens, names, state machine, keys -----------------------------------------------------


def test_link_tokens_are_returned_once_and_stored_as_digest():
    token, digest = privacy.new_link_token()
    assert privacy.is_plausible_token(token)
    assert digest == privacy.hash_link_token(token) == hashlib.sha256(token.encode()).digest()
    assert token.encode() not in digest
    other, _ = privacy.new_link_token()
    assert other != token
    assert not privacy.is_plausible_token("short")
    assert not privacy.is_plausible_token("x" * 31 + "!")


def test_link_expiry_bounds():
    assert privacy.link_expiry(NOW, 30) == NOW + timedelta(days=30)
    assert privacy.link_expiry(NOW, 1) == NOW + timedelta(days=1)
    for days in (0, 31):
        with pytest.raises(ValueError):
            privacy.link_expiry(NOW, days)


def test_given_name_only():
    assert privacy.given_name("Nguyễn Văn An") == "An"
    assert privacy.given_name("  Lan ") == "Lan"
    assert privacy.given_name("") == ""


def test_request_state_machine():
    for to in ("succeeded", "failed", "rejected"):
        assert privacy.can_transition("queued", to)
    for final in ("succeeded", "failed", "rejected"):
        for to in ("queued", "succeeded", "failed", "rejected"):
            assert not privacy.can_transition(final, to)
    assert not privacy.can_transition("queued", "queued")
    assert not privacy.can_transition("unknown", "succeeded")


def test_export_object_keys_are_server_chosen():
    ws, rid, user, student = uuid4(), uuid4(), uuid4(), uuid4()
    staff = SimpleNamespace(id=rid, workspace_id=ws, student_id=student, user_id=None)
    assert privacy.export_object_key(staff) == f"ws/{ws}/privacy/{rid}.json"
    own = SimpleNamespace(id=rid, workspace_id=ws, student_id=None, user_id=user)
    assert privacy.export_object_key(own) == f"users/{user}/privacy/{rid}.json"


def test_summary_counts_every_status():
    counts = privacy.summarize(["granted", "pending", "not_required", "granted", "unknown"])
    assert counts == {"granted": 2, "pending": 1, "notRequired": 1, "revoked": 0, "unknown": 1}


def test_jobs_are_registered_on_the_default_queue():
    assert job_service.QUEUE_BY_KIND["privacy.export"] == "default"
    assert job_service.QUEUE_BY_KIND["privacy.erase"] == "default"
    assert tasks.HANDLERS["privacy.export"].on_permanent_failure is privacy.mark_failed
    assert tasks.HANDLERS["privacy.erase"].on_permanent_failure is privacy.mark_failed


# ---- Export payload safety ------------------------------------------------------------------


def fake_export(**extra):
    item = {"itemId": str(uuid4()), "selectedKey": "B", "savedAt": "2026-10-23T08:00:00Z"}
    item.update(extra)
    return {
        "kind": "student_export",
        "student": {
            "studentId": str(uuid4()),
            "displayName": "Nguyễn Văn An",
            "consents": [{"method": "paper_school", "policyVersion": "2026-10-draft"}],
            "attempts": [
                {
                    "attemptId": str(uuid4()),
                    "answers": [item],
                    "releasedGrade": {"score": "1.00", "maxScore": "2.00"},
                }
            ],
        },
    }


def test_clean_export_passes():
    privacy.assert_export_safe(fake_export())


@pytest.mark.parametrize(
    "field", ["correct_key", "correctKey", "explanation", "guardian_contact_hash", "token_hash"]
)
def test_export_with_secret_fields_is_refused(field):
    with pytest.raises(privacy.UnsafeExport):
        privacy.assert_export_safe(fake_export(**{field: "A"}))


# ---- Worker handlers ------------------------------------------------------------------------


class Scalar:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class FakeStore:
    def __init__(self):
        self.objects, self.deleted = {}, []

    def put(self, key, body, *, mime, size, sha256):
        data = body.read()
        assert len(data) == size and hashlib.sha256(data).digest() == sha256
        assert mime == "application/json"
        self.objects[key] = data

    def delete(self, key):
        self.deleted.append(key)
        self.objects.pop(key, None)


class WorkerDb:
    def __init__(self, request, results=None, exports=()):
        self.request = request
        self.results = results or {}
        self.exports = list(exports)
        self.calls = []

    def get(self, model, key, **kwargs):
        return self.request if key == self.request.id else None

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append(sql)
        for name, value in self.results.items():
            if name in sql:
                return Scalar(value)
        raise AssertionError(sql)

    def scalars(self, query):
        return list(self.exports)

    def flush(self):
        pass


def job_for(request, kind):
    return SimpleNamespace(
        id=request.background_job_id,
        workspace_id=request.workspace_id,
        requested_by_user_id=request.requested_by_user_id,
        kind=kind,
        attempt=1,
        input={"privacyRequestId": str(request.id)},
    )


def privacy_request(kind, *, student=True, status="queued"):
    user = uuid4()
    return SimpleNamespace(
        id=uuid4(),
        workspace_id=uuid4(),
        student_id=uuid4() if student else None,
        user_id=None if student else user,
        kind=kind,
        status=status,
        requested_by_user_id=user,
        background_job_id=uuid4(),
        object_key=None,
        finished_at=None,
        note=None,
    )


def ctx(db, job, store):
    return SimpleNamespace(db=db, job=job, store=store, clock=lambda: NOW)


def test_export_job_writes_json_without_keys():
    request = privacy_request("export")
    db = WorkerDb(request, {"edu.student_export": fake_export()})
    store = FakeStore()
    result = privacy.run_export(ctx(db, job_for(request, "privacy.export"), store))
    key = f"ws/{request.workspace_id}/privacy/{request.id}.json"
    assert result["status"] == "succeeded" and request.object_key == key
    assert request.status == "succeeded" and request.finished_at == NOW
    stored = store.objects[key].decode()
    assert "correct_key" not in stored and "explanation" not in stored
    assert json.loads(stored)["student"]["displayName"] == "Nguyễn Văn An"
    # Replay of a finished request writes nothing.
    again = privacy.run_export(ctx(db, job_for(request, "privacy.export"), FakeStore()))
    assert again["replay"] is True


def test_self_export_uses_the_user_prefix():
    request = privacy_request("export", student=False)
    db = WorkerDb(request, {"edu.self_export": {"kind": "self_export", "students": []}})
    store = FakeStore()
    privacy.run_export(ctx(db, job_for(request, "privacy.export"), store))
    assert list(store.objects) == [f"users/{request.user_id}/privacy/{request.id}.json"]


def test_unsafe_export_fails_permanently():
    request = privacy_request("export")
    db = WorkerDb(request, {"edu.student_export": fake_export(correctKey="A")})
    with pytest.raises(privacy.PrivacyJobFailed) as caught:
        privacy.run_export(ctx(db, job_for(request, "privacy.export"), FakeStore()))
    assert caught.value.code == "unsafe_export"


def test_job_must_match_its_request():
    request = privacy_request("export")
    job = job_for(request, "privacy.export")
    job.id = uuid4()
    with pytest.raises(privacy.PrivacyJobFailed):
        privacy.run_export(ctx(WorkerDb(request), job, FakeStore()))
    with pytest.raises(privacy.PrivacyJobFailed):
        privacy.run_erasure(ctx(WorkerDb(request), job_for(request, "privacy.erase"), FakeStore()))


def test_student_erasure_purges_exports_then_erases():
    request = privacy_request("erasure")
    old = SimpleNamespace(object_key="ws/x/privacy/y.json")
    db = WorkerDb(request, {"edu.erase_student": 1}, exports=[old])
    store = FakeStore()
    result = privacy.run_erasure(ctx(db, job_for(request, "privacy.erase"), store))
    assert result == {
        "privacyRequestId": str(request.id),
        "status": "succeeded",
        "erased": 1,
        "purgedExports": 1,
    }
    assert store.deleted == ["ws/x/privacy/y.json"] and old.object_key is None
    assert request.status == "succeeded"


def test_self_erasure_completes_the_job_before_the_actor_disappears(monkeypatch):
    request = privacy_request("erasure", student=False)
    db = WorkerDb(request, {"edu.erase_self": request.user_id})
    order = []
    monkeypatch.setattr(
        privacy.job_service, "complete_job", lambda *a, **k: order.append("complete") or True
    )
    original = db.execute
    db.execute = lambda s, p=None: order.append("erase") or original(s, p)
    privacy.run_erasure(ctx(db, job_for(request, "privacy.erase"), FakeStore()))
    assert order == ["complete", "erase"]
    assert request.status == "succeeded"


def test_permanent_failure_marks_the_request():
    request = privacy_request("erasure")
    job = job_for(request, "privacy.erase")
    privacy.mark_failed(ctx(WorkerDb(request), job, None), privacy.PrivacyJobFailed("boom"))
    assert (request.status, request.note) == ("failed", "boom")
    other = privacy_request("export")
    privacy.mark_failed(
        ctx(WorkerDb(other), job_for(other, "privacy.export"), None),
        tasks.PermanentJobError("student_not_found"),
    )
    assert other.status == "rejected"
    # A finished request is final.
    privacy.mark_failed(ctx(WorkerDb(request), job, None), privacy.PrivacyJobFailed("again"))
    assert request.note == "boom"
