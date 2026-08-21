from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from payguard.shared.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    settings = get_settings()
    db_url = url or settings.database_url
    return create_async_engine(db_url, pool_pre_ping=True, echo=False)


def make_session_factory(url: str | None = None) -> async_sessionmaker[AsyncSession]:
    engine = make_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = make_session_factory()
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
