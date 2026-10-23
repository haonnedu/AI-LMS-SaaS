"""Public guardian consent links (PILOT-05). No account and no bearer token.

The token is a single-use bearer secret (sha256 digest stored). The page shows only the
student's given name and the workspace name. The guardian contact is normalised and hashed
before the database call and is never logged or echoed. Rate limited per token prefix and
globally (per process, like invitation accept; production needs a shared limiter, M7).
Unknown tokens answer 404, used/expired ones 410, throttled callers 429.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.classes import TokenBucketLimiter
from app.api.identity import ApiError, Database, ErrorDTO
from app.core.audit import audit
from app.services import privacy as service

router = APIRouter(
    prefix="/v1/public",
    tags=["public-consent"],
    responses={status: {"model": ErrorDTO} for status in (404, 410, 422, 429, 503)},
)

# 10 calls per token prefix then one per 30 s; 300 overall then 5 per second.
token_limiter = TokenBucketLimiter(capacity=10, refill_per_second=1 / 30)
global_limiter = TokenBucketLimiter(capacity=300, refill_per_second=5)


def check_rate(token: str) -> None:
    if not (global_limiter.allow("all") and token_limiter.allow(token[:8])):
        raise ApiError(429, "rate_limited", "Bạn thử quá nhiều lần. Vui lòng đợi rồi thử lại.")


class ConsentLinkInfoDTO(BaseModel):
    studentDisplayName: str
    workspaceName: str
    policyVersion: str
    expiresAt: datetime


class GuardianConsentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    guardianName: str = Field(min_length=1, max_length=200)
    guardianContact: str = Field(min_length=3, max_length=254)
    agree: Literal[True]


class GuardianConsentResultDTO(BaseModel):
    status: Literal["granted"]


def request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


@router.get("/consent-links/{token}", response_model=ConsentLinkInfoDTO)
async def consent_link(token: str, request: Request, db: Database):
    check_rate(token)
    try:
        async with db.begin():
            info = await service.link_info(db, token)
    except service.PrivacyError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    return ConsentLinkInfoDTO(
        studentDisplayName=info.student_given_name,
        workspaceName=info.workspace_name,
        policyVersion=request.app.state.settings.privacy_policy_version,
        expiresAt=info.expires_at,
    )


@router.post("/consent-links/{token}", response_model=GuardianConsentResultDTO)
async def give_consent(token: str, body: GuardianConsentDTO, request: Request, db: Database):
    check_rate(token)
    try:
        async with db.begin():
            granted = await service.consent_by_link(
                db,
                token,
                guardian_name=body.guardianName,
                contact=body.guardianContact,
                policy_version=request.app.state.settings.privacy_policy_version,
            )
    except service.PrivacyError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from None
    audit(
        "privacy.consent_granted_by_link",
        request_id=request_id(request),
        user_id=None,
        workspace_id=granted.workspace_id,
        student_id=granted.student_id,
        consent_id=granted.consent_id,
    )
    return GuardianConsentResultDTO(status="granted")
