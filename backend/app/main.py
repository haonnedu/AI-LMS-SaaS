from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.infrastructure.resources import Infrastructure


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

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
            "Development foundation. Health checks are implemented; tenant, teaching, "
            "AI, and grading endpoints require the identity and authorization milestone."
        ),
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.environment != "production" else None,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.include_router(health_router)
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
