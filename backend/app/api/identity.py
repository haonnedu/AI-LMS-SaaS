"""Authenticated API. Browser identity headers and body identities are never trusted."""

import asyncio
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.auth import CLAIM_NAMESPACE, IdentityUnavailable, TokenError
from app.infrastructure.context import WorkspaceContext, set_identity
from app.models.identity import User, UserIdentity, Workspace, WorkspaceMember
from app.services.user_provisioning import provision_user_from_claims


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


class UserDTO(BaseModel):
    id: UUID
    name: str
    email: str


class WorkspaceDTO(BaseModel):
    id: UUID
    name: str
    kind: Literal["personal", "school"]
    role: str


class BootstrapDTO(BaseModel):
    user: UserDTO
    personalWorkspace: WorkspaceDTO


class WorkspaceListDTO(BaseModel):
    items: list[WorkspaceDTO]
    nextCursor: UUID | None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorDTO(BaseModel):
    error: ErrorDetail
    requestId: str


router = APIRouter(
    prefix="/v1",
    tags=["identity"],
    responses={status: {"model": ErrorDTO} for status in (401, 403, 404, 409, 422, 503)},
)
bearer = HTTPBearer(auto_error=False)


async def verified_claims(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> dict[str, Any]:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise ApiError(401, "unauthorized", "Sign in to continue.")
    verifier = request.app.state.token_verifier
    if verifier is None:
        raise ApiError(503, "auth_unavailable", "Authentication is not configured.")
    try:
        claims = await asyncio.to_thread(verifier.verify_token, credentials.credentials)
    except TokenError:
        raise ApiError(401, "invalid_token", "Your session is invalid or expired.") from None
    except IdentityUnavailable:
        raise ApiError(
            503, "identity_unavailable", "Authentication is temporarily unavailable."
        ) from None
    if claims.get(CLAIM_NAMESPACE + "email_verified") is not True:
        raise ApiError(403, "email_unverified", "Verify your email before continuing.")
    email = claims.get(CLAIM_NAMESPACE + "email")
    if not isinstance(email, str) or not email or len(email) > 255:
        raise ApiError(401, "invalid_identity", "The identity profile is incomplete.")
    return claims


Claims = Annotated[dict[str, Any], Depends(verified_claims)]
Database = Annotated[AsyncSession, Depends(get_session)]


async def current_user(db: AsyncSession, claims: dict[str, Any]) -> User:
    await set_identity(db, claims["iss"], claims["sub"])
    user = await db.scalar(
        select(User).where(
            User.id.in_(
                select(UserIdentity.user_id).where(
                    UserIdentity.issuer == claims["iss"], UserIdentity.subject == claims["sub"]
                )
            )
        )
    )
    if user is None:
        raise ApiError(409, "onboarding_required", "Complete onboarding first.")
    if not user.is_active:
        raise ApiError(403, "account_disabled", "This account is disabled.")
    return user


def user_dto(user: User) -> UserDTO:
    return UserDTO(id=user.id, name=user.display_name or "Giáo viên", email=user.email)


def accessible_workspaces(user: User):
    return (
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.status == "active",
            Workspace.is_active.is_(True),
        )
    )


def workspace_dto(row) -> WorkspaceDTO:
    workspace, role = row
    return WorkspaceDTO(
        id=workspace.id, name=workspace.name, kind=workspace.workspace_type, role=role
    )


@router.post("/auth/bootstrap", response_model=BootstrapDTO)
async def bootstrap(db: Database, claims: Claims):
    try:
        async with db.begin():
            await set_identity(db, claims["iss"], claims["sub"])
            await provision_user_from_claims(db, claims)
            user = await current_user(db, claims)
            row = (
                await db.execute(
                    accessible_workspaces(user).where(Workspace.personal_owner_user_id == user.id)
                )
            ).first()
            if row is None:
                raise ApiError(
                    403, "workspace_unavailable", "Your personal workspace is unavailable."
                )
            return BootstrapDTO(user=user_dto(user), personalWorkspace=workspace_dto(row))
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "28000":
            raise ApiError(403, "account_disabled", "This account is disabled.") from None
        raise


@router.get("/me", response_model=UserDTO)
async def me(db: Database, claims: Claims):
    async with db.begin():
        return user_dto(await current_user(db, claims))


@router.get("/workspaces", response_model=WorkspaceListDTO)
async def workspaces(
    db: Database,
    claims: Claims,
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    async with db.begin():
        user = await current_user(db, claims)
        query = accessible_workspaces(user).order_by(Workspace.id).limit(limit + 1)
        if cursor:
            query = query.where(Workspace.id > cursor)
        rows = (await db.execute(query)).all()
        return WorkspaceListDTO(
            items=[workspace_dto(row) for row in rows[:limit]],
            nextCursor=rows[limit - 1][0].id if len(rows) > limit else None,
        )


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceDTO)
async def workspace(workspace_id: UUID, db: Database, claims: Claims):
    async with db.begin():
        user = await current_user(db, claims)
        row = (
            await db.execute(accessible_workspaces(user).where(Workspace.id == workspace_id))
        ).first()
        if row is None:
            raise ApiError(404, "workspace_not_found", "Workspace not found.")
        await WorkspaceContext(user.id, workspace_id).apply(db)
        return workspace_dto(row)


class TransferRequest(BaseModel):
    proof: str = Field(min_length=1, max_length=16384)


@router.post("/auth/migrate", response_model=UserDTO)
async def migrate_identity(body: TransferRequest, request: Request, db: Database, claims: Claims):
    settings = request.app.state.settings
    verifier = request.app.state.migration_verifier
    if verifier is None:
        raise ApiError(404, "not_found", "Migration is not enabled.")
    try:
        proof = await asyncio.to_thread(verifier.verify_token, body.proof)
    except TokenError:
        raise ApiError(401, "invalid_migration_proof", "The migration proof is invalid.") from None
    except IdentityUnavailable:
        raise ApiError(
            503, "identity_unavailable", "Migration is temporarily unavailable."
        ) from None
    if (
        claims["iss"] != settings.auth_issuer
        or proof.get("sub") != claims["sub"]
        or proof.get("purpose") != "identity_transfer"
        or proof.get("source_issuer") != settings.legacy_auth_issuer
        or not isinstance(proof.get("source_subject"), str)
        or not proof["source_subject"]
        or not isinstance(proof.get("jti"), str)
        or len(proof["jti"]) > 100
        or proof["exp"] - proof["iat"] > 300
    ):
        raise ApiError(401, "invalid_migration_proof", "The migration proof is invalid.")
    try:
        async with db.begin():
            await set_identity(db, claims["iss"], claims["sub"])
            await db.execute(
                text(
                    "SELECT edu.transfer_identity(:source_issuer,:source_subject,"
                    ":target_issuer,:target_subject,:proof_id)"
                ),
                {
                    "source_issuer": proof["source_issuer"],
                    "source_subject": proof["source_subject"],
                    "target_issuer": claims["iss"],
                    "target_subject": claims["sub"],
                    "proof_id": proof["jti"],
                },
            )
            return user_dto(await current_user(db, claims))
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "23505":
            raise ApiError(
                409, "identity_conflict", "This identity belongs to another account."
            ) from None
        if getattr(exc.orig, "sqlstate", None) == "28000":
            raise ApiError(403, "account_disabled", "The source account is unavailable.") from None
        raise
