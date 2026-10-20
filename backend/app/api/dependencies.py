from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.resources import Infrastructure


def get_infrastructure(request: Request) -> Infrastructure:
    return request.app.state.infrastructure


async def get_session(
    infrastructure: Annotated[Infrastructure, Depends(get_infrastructure)],
) -> AsyncIterator[AsyncSession]:
    """Services must explicitly begin/commit transactions; this closes and rolls back.

    This is an infrastructure dependency, not authorization. Before tenant routes
    exist, add verified identity and transaction-local RLS context to each service.
    Never accept workspace/user context directly from a client header.
    """
    async with infrastructure.sessions() as session:
        yield session
