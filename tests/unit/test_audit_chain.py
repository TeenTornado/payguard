"""Audit hash-chain tests: valid chain passes, tampered chain fails."""
import asyncio
import hashlib
import json

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from payguard.shared.audit import (
    GENESIS_HASH,
    _canonical_json,
    _compute_hash,
    append_audit_event,
    verify_audit_chain,
)
from payguard.shared.db import Base
from payguard.shared.enums import AuditActor, AuditEventKind
from payguard.shared.models import AuditEvent

# Use SQLite for unit tests (no Postgres needed)
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


class TestHashComputation:
    def test_genesis_hash_is_zeros(self) -> None:
        assert GENESIS_HASH == "0" * 64

    def test_compute_hash_deterministic(self) -> None:
        data = {"ts": "2026-08-21T00:00:00", "actor": "SYSTEM", "event": "SCAN_STARTED",
                "object_type": None, "object_id": None, "metadata": {}}
        h1 = _compute_hash(GENESIS_HASH, data)
        h2 = _compute_hash(GENESIS_HASH, data)
        assert h1 == h2
        assert len(h1) == 64

    def test_different_prev_hash_yields_different_hash(self) -> None:
        data = {"ts": "2026-08-21T00:00:00", "actor": "SYSTEM", "event": "SCAN_STARTED",
                "object_type": None, "object_id": None, "metadata": {}}
        h1 = _compute_hash(GENESIS_HASH, data)
        h2 = _compute_hash("a" * 64, data)
        assert h1 != h2

    def test_canonical_json_sorts_keys(self) -> None:
        d = {"z": 1, "a": 2, "m": 3}
        s = _canonical_json(d)
        assert s == '{"a":2,"m":3,"z":1}'


@pytest.mark.asyncio
class TestAuditChain:
    async def test_empty_chain_is_valid(self, session: AsyncSession) -> None:
        ok, msg = await verify_audit_chain(session)
        assert ok, msg

    async def test_single_event_chain_valid(self, session: AsyncSession) -> None:
        await append_audit_event(
            session, AuditActor.SYSTEM, AuditEventKind.SCAN_STARTED,
            object_type="Scan", object_id="scan-001"
        )
        await session.commit()
        ok, msg = await verify_audit_chain(session)
        assert ok, msg

    async def test_multiple_events_chain_valid(self, session: AsyncSession) -> None:
        for kind in [
            AuditEventKind.SCAN_STARTED,
            AuditEventKind.DISCOVERY_COMPLETED,
            AuditEventKind.STATIC_ANALYSIS_COMPLETED,
        ]:
            await append_audit_event(session, AuditActor.SYSTEM, kind)
        await session.commit()
        ok, msg = await verify_audit_chain(session)
        assert ok, msg

    async def test_tampered_hash_detected(self, session: AsyncSession) -> None:
        await append_audit_event(session, AuditActor.SYSTEM, AuditEventKind.SCAN_STARTED)
        await append_audit_event(session, AuditActor.SYSTEM, AuditEventKind.FINDING_CREATED,
                                 object_id="finding-001")
        await session.commit()

        # Tamper: directly overwrite the hash of the first row
        await session.execute(
            text("UPDATE audit_events SET hash = 'deadbeef' || substr(hash, 9) WHERE seq = 1")
        )
        await session.commit()

        ok, msg = await verify_audit_chain(session)
        assert not ok
        assert "mismatch" in msg.lower() or "broken" in msg.lower()

    async def test_tampered_prev_hash_detected(self, session: AsyncSession) -> None:
        await append_audit_event(session, AuditActor.SYSTEM, AuditEventKind.SCAN_STARTED)
        await append_audit_event(session, AuditActor.VERIFIER, AuditEventKind.VERIFICATION_COMPLETED,
                                 object_id="v-001")
        await session.commit()

        # Tamper: break the chain link
        await session.execute(
            text("UPDATE audit_events SET prev_hash = 'badhash' WHERE seq = 2")
        )
        await session.commit()

        ok, msg = await verify_audit_chain(session)
        assert not ok

    async def test_human_actor_string(self, session: AsyncSession) -> None:
        await append_audit_event(
            session, "HUMAN:alice", AuditEventKind.HUMAN_APPROVED,
            object_type="Finding", object_id="f-001"
        )
        await session.commit()
        ok, msg = await verify_audit_chain(session)
        assert ok, msg
