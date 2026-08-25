"""Integration-test fixtures: an in-memory SQLite DB wired into the real get_db path.

The ORM models are SQLite-compatible (String PKs, JSON columns, Integer autoincrement),
so we can exercise the real FastAPI app and the real ``get_db`` transaction behaviour
without Postgres. A StaticPool keeps the one in-memory connection alive across sessions.
"""
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import payguard.shared.db as dbmod
import payguard.shared.models  # noqa: F401 — register tables on Base.metadata
from payguard.shared.db import Base


@pytest_asyncio.fixture
async def sqlite_factory(monkeypatch):
    """Bind get_session_factory() to a fresh in-memory SQLite DB for one test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # get_db() resolves the factory via this module global at call time.
    monkeypatch.setattr(dbmod, "_session_factory", factory)
    monkeypatch.setattr(dbmod, "_engine", engine)

    yield factory

    await engine.dispose()
