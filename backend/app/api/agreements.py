"""User agreement + privacy notice acceptance at registration (decision 0009, migration 0017).

Accepting the current ``terms_version`` (user agreement) and ``privacy_policy_version``
(privacy notice) is the legal basis for every role. Acceptance is recorded per user through the
SECURITY DEFINER functions ``edu.record_agreements`` / ``edu.current_agreements`` with only the
verified identity applied (no workspace context). ``POST /v1/auth/bootstrap`` refuses with 409
``agreement_required`` until the current versions are accepted (``require_current_agreements``).

The user is not signed in right after ``sign-up/email`` (email verification first), so the
acceptance is recorded at the first authenticated step: ``POST /v1/auth/agreements`` provisions
the account (same idempotent ``edu.bootstrap_identity`` as bootstrap) and records both rows.
Only a sha256 of the browser user agent may be stored, never the IP address.
"""

from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.identity import ApiError, Claims, Database, ErrorDTO, current_user
from app.core.audit import audit
from app.infrastructure.context import set_identity
from app.services.user_provisioning import provision_user_from_claims

USER_AGREEMENT = "user_agreement"
PRIVACY_NOTICE = "privacy_notice"
VERSION_PATTERN = r"^[A-Za-z0-9._-]{1,32}$"

router = APIRouter(
    prefix="/v1/auth",
    tags=["agreements"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 409, 422, 503)},
)


class AgreementVersionsDTO(BaseModel):
    userAgreement: str | None
    privacy: str | None


class AgreementStatusDTO(BaseModel):
    required: AgreementVersionsDTO
    accepted: AgreementVersionsDTO
    upToDate: bool


class AgreementAcceptDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    userAgreementVersion: str = Field(pattern=VERSION_PATTERN)
    privacyVersion: str = Field(pattern=VERSION_PATTERN)
    accepted: Literal[True]
    # Hex sha256 of the browser user agent, computed by the BFF. Never an IP address.
    clientHash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class Agreements:
    required_terms: str
    required_privacy: str
    accepted_terms: str | None
    accepted_privacy: str | None

    @property
    def up_to_date(self) -> bool:
        return (
            self.accepted_terms == self.required_terms
            and self.accepted_privacy == self.required_privacy
        )

    @property
    def any_accepted(self) -> bool:
        return self.accepted_terms is not None or self.accepted_privacy is not None


def required_versions(settings) -> tuple[str, str]:
    return settings.terms_version, settings.privacy_policy_version


async def load_agreements(db: AsyncSession, settings) -> Agreements:
    """The actor's latest accepted versions (identity must already be applied)."""
    rows = (await db.execute(text("SELECT * FROM edu.current_agreements()"))).all()
    latest = {row.out_document: row.out_version for row in rows}
    terms, privacy = required_versions(settings)
    return Agreements(terms, privacy, latest.get(USER_AGREEMENT), latest.get(PRIVACY_NOTICE))


async def require_current_agreements(db: AsyncSession, settings) -> None:
    """Bootstrap guard: 409 ``agreement_required`` until the current versions are accepted."""
    if not (await load_agreements(db, settings)).up_to_date:
        raise ApiError(
            409,
            "agreement_required",
            "Vui lòng đồng ý với Thỏa thuận người dùng và Thông báo quyền riêng tư để tiếp tục.",
        )


def status_dto(agreements: Agreements) -> AgreementStatusDTO:
    return AgreementStatusDTO(
        required=AgreementVersionsDTO(
            userAgreement=agreements.required_terms, privacy=agreements.required_privacy
        ),
        accepted=AgreementVersionsDTO(
            userAgreement=agreements.accepted_terms, privacy=agreements.accepted_privacy
        ),
        upToDate=agreements.up_to_date,
    )


@router.get("/agreements", response_model=AgreementStatusDTO)
async def agreements_status(request: Request, db: Database, claims: Claims):
    # No provisioning here: before the first acceptance the account may not exist yet, in which
    # case edu.actor_id() is NULL and nothing is accepted.
    async with db.begin():
        await set_identity(db, claims["iss"], claims["sub"])
        return status_dto(await load_agreements(db, request.app.state.settings))


@router.post("/agreements", response_model=AgreementStatusDTO)
async def accept_agreements(
    body: AgreementAcceptDTO, request: Request, db: Database, claims: Claims
):
    settings = request.app.state.settings
    terms, privacy = required_versions(settings)
    if body.userAgreementVersion != terms or body.privacyVersion != privacy:
        raise ApiError(
            409,
            "agreement_version_outdated",
            "Văn bản đã được cập nhật. Vui lòng tải lại trang và đọc phiên bản mới.",
        )
    client_hash = bytes.fromhex(body.clientHash) if body.clientHash else None
    try:
        async with db.begin():
            await set_identity(db, claims["iss"], claims["sub"])
            await provision_user_from_claims(db, claims)
            user = await current_user(db, claims)
            before = await load_agreements(db, settings)
            method = "reaccept" if before.any_accepted else "signup"
            inserted = (
                await db.execute(
                    text("SELECT edu.record_agreements(:terms, :privacy, :method, :client_hash)"),
                    {
                        "terms": terms,
                        "privacy": privacy,
                        "method": method,
                        "client_hash": client_hash,
                    },
                )
            ).scalar_one()
            after = await load_agreements(db, settings)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "28000":
            raise ApiError(403, "account_disabled", "This account is disabled.") from None
        raise
    if inserted:
        audit(
            "auth.agreements_accepted",
            request_id=getattr(request.state, "request_id", None) or None,
            user_id=user.id,
            workspace_id=None,
            terms_version=terms,
            privacy_version=privacy,
            method=method,
        )
    return status_dto(after)
