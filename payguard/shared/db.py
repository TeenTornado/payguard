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
    """FastAPI dependency: yield a session, commit on clean return, roll back on error.

    Route handlers MUST NOT call ``session.begin()``, ``commit()`` or ``rollback()``
    themselves. This is the single place a request's unit of work is committed, so a
    handler that reads (which starts SQLAlchemy 2.0 autobegin) and then writes cannot
    collide with a nested ``begin()``. See docs/failure-modes.md and FAILURES.md
    (2026-08-24, autobegin vs db.begin()). Enforced by
    tests/unit/test_transaction_convention.py.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
