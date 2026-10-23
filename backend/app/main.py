from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app import __version__
from app.api.assignments import router as assignments_router
from app.api.authoring import router as authoring_router
from app.api.classes import router as classes_router
from app.api.documents import router as documents_router
from app.api.generation import router as generation_router
from app.api.health import router as health_router
from app.api.identity import ApiError
from app.api.identity import router as identity_router
from app.api.jobs import router as jobs_router
from app.api.knowledge import router as knowledge_router
from app.api.retrieval import router as retrieval_router
from app.api.student import router as student_router
from app.core.auth import TokenVerifier, TokenVerifierSet
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.resources import Infrastructure


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if (
        settings.auth_issuer
        and make_url(settings.database_url.get_secret_value()).username != "eduvia_runtime"
    ):
        raise ValueError("Authenticated API requires the restricted eduvia_runtime database role")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        resources = Infrastructure.create(settings)
        application.state.infrastructure = resources
        try:
            yield
        finally:
            await resources.close()

    application = FastAPI(
        title="Eduvia API",
        version=__version__,
        description=(
            "Eduvia identity API: verified access tokens, atomic personal workspace bootstrap "
            "and membership-scoped workspace access. Teaching, AI and grading remain planned."
        ),
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.state.token_verifier = (
        TokenVerifier(settings.auth_issuer, settings.auth_audience, settings.auth_jwks_url)
        if settings.auth_issuer
        else None
    )

    if settings.legacy_auth_issuer:
        application.state.token_verifier = TokenVerifierSet(
            [
                application.state.token_verifier,
                TokenVerifier(
                    settings.legacy_auth_issuer,
                    settings.legacy_auth_audience,
                    settings.legacy_auth_jwks_url,
                ),
            ]
        )

    application.state.migration_verifier = (
        TokenVerifier(
            settings.auth_issuer + "/migration",
            settings.auth_audience + "/migration",
            settings.auth_jwks_url,
        )
        if settings.legacy_auth_issuer
        else None
    )

    def error_response(request: Request, status: int, code: str, message: str):
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": code, "message": message},
                "requestId": getattr(request.state, "request_id", ""),
            },
            headers={
                "Cache-Control": "no-store",
                **({"WWW-Authenticate": "Bearer"} if status == 401 else {}),
            },
        )

    @application.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(request, 422, "invalid_request", "Invalid request parameters.")

    @application.exception_handler(DBAPIError)
    async def database_error(request: Request, exc: DBAPIError):
        return error_response(
            request, 503, "database_unavailable", "The service is temporarily unavailable."
        )

    application.include_router(health_router)
    application.include_router(identity_router)
    application.include_router(classes_router)
    application.include_router(documents_router)
    application.include_router(jobs_router)
    application.include_router(knowledge_router)
    application.include_router(retrieval_router)
    application.include_router(authoring_router)
    application.include_router(generation_router)
    application.include_router(assignments_router)
    application.include_router(student_router)
    application.add_middleware(RequestContextMiddleware)
    # Last added executes outermost, so CORS headers cover our bounded 500 responses.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    return application


app = create_app()
