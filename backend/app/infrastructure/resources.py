from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.infrastructure.database import create_engine, create_session_factory


@dataclass
class Infrastructure:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    redis: Redis

    @classmethod
    def create(cls, settings: Settings) -> "Infrastructure":
        engine = create_engine(settings)
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            decode_responses=True,
            socket_timeout=settings.health_timeout_seconds,
            socket_connect_timeout=settings.health_timeout_seconds,
            health_check_interval=30,
        )
        return cls(engine=engine, sessions=create_session_factory(engine), redis=redis)

    async def close(self) -> None:
        try:
            await self.redis.aclose()
        finally:
            await self.engine.dispose()
