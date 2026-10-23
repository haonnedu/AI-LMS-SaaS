"""User agreement acceptance at registration (decision 0009) with a fake session: status,
recording (versions, method, client hash, audit), outdated versions and the bootstrap guard."""

import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.api import agreements as agreements_api
from app.api.dependencies import get_session
from app.core.auth import CLAIM_NAMESPACE, TokenError
from app.core.config import Settings
from app.main import create_app

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
AUTH = {"Authorization": "Bearer good"}
VERSION = "2026-10-draft"


class FakeVerifier:
    def verify_token(self, token):
        if token == "bad":
            raise TokenError("bad")
        return {
            "iss": "https://identity.example/",
            "sub": "user-1",
            CLAIM_NAMESPACE + "email": "u@example.com",
            CLAIM_NAMESPACE + "email_verified": True,
        }


class Result(list):
    def all(self):
        return list(self)

    def first(self):
        return self[0] if self else None

    def scalar_one(self):
        return self[0]


def db_error(sqlstate):
    class Orig(Exception):
        pass

    orig = Orig("hidden")
    orig.sqlstate = sqlstate
    return DBAPIError("SELECT 1", {}, orig)


class FakeSession:
    """Keeps accepted versions per document like edu.user_agreements (unique per version)."""

    def __init__(self):
        self.user = SimpleNamespace(
            id=uuid4(), is_active=True, display_name="Lan", email="u@example.com"
        )
        self.rows: list[dict] = []
        self.records: list[dict] = []
        self.provisioned = 0
        self.provision_error = None
        self.workspace = SimpleNamespace(id=uuid4(), name="Cá nhân", workspace_type="personal")

    @asynccontextmanager
    async def _transaction(self):
        yield

    def begin(self):
        return self._transaction()

    async def execute(self, statement, params=None):
        sql = str(statement)
        if "set_config" in sql:
            return Result()
        if "edu.bootstrap_identity" in sql:
            if self.provision_error is not None:
                raise self.provision_error
            self.provisioned += 1
            return Result([self.user.id])
        if "edu.current_agreements" in sql:
            latest = {}
            for row in self.rows:
                latest[row["document"]] = row
            return Result(
                SimpleNamespace(
                    out_document=r["document"],
                    out_version=r["version"],
                    out_accepted_at=NOW,
                    out_method=r["method"],
                )
                for r in latest.values()
            )
        if "edu.record_agreements" in sql:
            self.records.append(params)
            inserted = 0
            for document, version in (
                ("user_agreement", params["terms"]),
                ("privacy_notice", params["privacy"]),
            ):
                if any(r["document"] == document and r["version"] == version for r in self.rows):
                    continue
                self.rows.append(
                    {"document": document, "version": version, "method": params["method"]}
                )
                inserted += 1
            return Result([inserted])
        if "workspace_members" in sql:
            return Result([(self.workspace, "owner")])
        raise AssertionError(sql)

    async def scalar(self, statement, params=None):
        return self.user


@pytest.fixture
def fake():
    app = create_app(Settings(_env_file=None, environment="test"))
    paths = {getattr(r, "path", "") for r in app.routes}
    if not any(route.path in paths for route in agreements_api.router.routes):
        app.include_router(agreements_api.router)
    app.state.token_verifier = FakeVerifier()
    session = FakeSession()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), session


def accept(client, terms=VERSION, privacy=VERSION, **extra):
    body = {"userAgreementVersion": terms, "privacyVersion": privacy, "accepted": True}
    return client.post("/v1/auth/agreements", json=body | extra, headers=AUTH)


def test_routes_require_a_token(fake):
    client, _ = fake
    for headers in ({}, {"Authorization": "Bearer bad"}):
        assert client.get("/v1/auth/agreements", headers=headers).status_code == 401
        response = client.post("/v1/auth/agreements", json={}, headers=headers)
        assert response.status_code == 401
        assert client.post("/v1/auth/bootstrap", headers=headers).status_code == 401


def test_status_before_any_acceptance(fake):
    client, session = fake
    response = client.get("/v1/auth/agreements", headers=AUTH)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "required": {"userAgreement": VERSION, "privacy": VERSION},
        "accepted": {"userAgreement": None, "privacy": None},
        "upToDate": False,
    }
    assert session.provisioned == 0  # reading never creates the account


def test_accept_records_both_documents_once(fake, caplog):
    client, session = fake
    ua_hash = hashlib.sha256(b"Mozilla/5.0").hexdigest()
    with caplog.at_level(logging.INFO, logger="eduvia.audit"):
        response = accept(client, clientHash=ua_hash)
    assert response.status_code == 200, response.text
    assert response.json()["upToDate"] is True
    assert response.json()["accepted"] == {"userAgreement": VERSION, "privacy": VERSION}
    assert session.provisioned == 1
    record = session.records[0]
    assert record["method"] == "signup"
    assert record["client_hash"] == bytes.fromhex(ua_hash) and len(record["client_hash"]) == 32
    assert {(r["document"], r["version"]) for r in session.rows} == {
        ("user_agreement", VERSION),
        ("privacy_notice", VERSION),
    }
    audits = [r for r in caplog.records if getattr(r, "audit", None)]
    assert any(r.audit["event"] == "auth.agreements_accepted" for r in audits)
    # Replay: nothing new, no second audit entry, still up to date.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="eduvia.audit"):
        replay = accept(client)
    assert replay.status_code == 200 and replay.json()["upToDate"] is True
    assert len(session.rows) == 2
    assert not [r for r in caplog.records if getattr(r, "audit", None)]


def test_new_version_is_recorded_as_reaccept(fake):
    client, session = fake
    assert accept(client).status_code == 200
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"terms_version": "2026-11-v1"}
    )
    status = client.get("/v1/auth/agreements", headers=AUTH).json()
    assert status["upToDate"] is False and status["required"]["userAgreement"] == "2026-11-v1"
    assert accept(client, terms="2026-11-v1").status_code == 200
    assert session.records[-1]["method"] == "reaccept"


@pytest.mark.parametrize(
    "terms,privacy", [("2026-09-draft", VERSION), (VERSION, "2026-09-draft"), ("x", "y")]
)
def test_outdated_versions_are_refused(fake, terms, privacy):
    client, session = fake
    response = accept(client, terms=terms, privacy=privacy)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agreement_version_outdated"
    assert session.records == [] and session.provisioned == 0


@pytest.mark.parametrize(
    "body",
    [
        {"userAgreementVersion": VERSION, "privacyVersion": VERSION, "accepted": False},
        {"userAgreementVersion": VERSION, "privacyVersion": VERSION},
        {"userAgreementVersion": VERSION, "privacyVersion": VERSION, "accepted": True, "ip": "1"},
        {
            "userAgreementVersion": VERSION,
            "privacyVersion": VERSION,
            "accepted": True,
            "clientHash": "not-hex",
        },
        {"userAgreementVersion": "bad version", "privacyVersion": VERSION, "accepted": True},
    ],
)
def test_invalid_bodies_are_422(fake, body):
    client, session = fake
    response = client.post("/v1/auth/agreements", json=body, headers=AUTH)
    assert response.status_code == 422
    assert session.records == []


def test_disabled_account_cannot_accept(fake):
    client, session = fake
    session.provision_error = db_error("28000")
    response = accept(client)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


def test_bootstrap_requires_the_current_agreements(fake):
    client, session = fake
    refused = client.post("/v1/auth/bootstrap", headers=AUTH)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "agreement_required"
    assert accept(client).status_code == 200
    allowed = client.post("/v1/auth/bootstrap", headers=AUTH)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["personalWorkspace"]["id"] == str(session.workspace.id)
    # A newer privacy notice gates bootstrap again until it is accepted.
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"privacy_policy_version": "2026-11-v1"}
    )
    again = client.post("/v1/auth/bootstrap", headers=AUTH)
    assert again.status_code == 409 and again.json()["error"]["code"] == "agreement_required"
