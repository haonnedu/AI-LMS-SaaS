import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from app import __version__
from app.api.dependencies import get_infrastructure
from app.infrastructure.resources import Infrastructure

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger("eduvia.health")


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["eduvia-api"] = "eduvia-api"
    version: str = __version__


class ReadinessChecks(BaseModel):
    postgres: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    checks: ReadinessChecks


async def probe_postgres(infrastructure: Infrastructure) -> None:
    async with infrastructure.engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def probe_redis(infrastructure: Infrastructure) -> None:
    if not await infrastructure.redis.ping():
        raise ConnectionError("Redis ping was not acknowledged")


async def bounded_probe(
    name: str, probe: Callable[[], Awaitable[None]], deadline_seconds: float
) -> Literal["ok", "unavailable"]:
    try:
        async with asyncio.timeout(deadline_seconds):
            await probe()
        return "ok"
    except Exception as exc:
        logger.warning(
            "dependency_unavailable", extra={"dependency": name, "error_type": type(exc).__name__}
        )
        return "unavailable"


@router.get("/live", response_model=LiveResponse, operation_id="getLiveness")
async def liveness(response: Response) -> LiveResponse:
    """Process liveness without external dependency checks."""
    response.headers["Cache-Control"] = "no-store"
    return LiveResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={
        503: {"model": ReadyResponse, "description": "A required dependency is unavailable"}
    },
    operation_id="getReadiness",
)
async def readiness(
    request: Request,
    response: Response,
    infrastructure: Annotated[Infrastructure, Depends(get_infrastructure)],
) -> ReadyResponse:
    """Bounded concurrent probes; never returns connection details or credentials."""
    timeout = request.app.state.settings.health_timeout_seconds
    postgres, redis = await asyncio.gather(
        bounded_probe("postgres", lambda: probe_postgres(infrastructure), timeout),
        bounded_probe("redis", lambda: probe_redis(infrastructure), timeout),
    )
    ready = postgres == "ok" and redis == "ok"
    response.status_code = 200 if ready else 503
    response.headers["Cache-Control"] = "no-store"
    return ReadyResponse(
        status="ready" if ready else "unavailable",
        checks=ReadinessChecks(postgres=postgres, redis=redis),
    )
