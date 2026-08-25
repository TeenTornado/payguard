"""Integration tests for the get_db transaction convention.

Two guards, both against the real FastAPI app over an in-memory SQLite DB:

1. read-then-write succeeds — a handler that SELECTs (triggering SQLAlchemy 2.0
   autobegin) and then writes commits cleanly. This is the regression that a nested
   ``db.begin()`` broke (InvalidRequestError → 500).
2. write-raises rolls back — if a handler raises after a partial write, get_db rolls the
   whole unit back: no orphan row, no half-written audit event.
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import func, select

import payguard.api.app as app_module
from payguard.api.app import app
from payguard.shared.models import AuditEvent, Finding, Remediation, Repository, Scan


async def _seed_finding(factory) -> str:
    """Insert a Repository → Scan → Finding and return the finding id."""
    repo_id, scan_id, finding_id = (str(uuid.uuid4()) for _ in range(3))
    async with factory() as session:
        async with session.begin():
            session.add(Repository(id=repo_id, source_type="LOCAL_PATH", locator="/tmp/x"))
            session.add(Scan(id=scan_id, repository_id=repo_id, state="DONE"))
            session.add(
                Finding(
                    id=finding_id,
                    scan_id=scan_id,
                    repository_id=repo_id,
                    defect_class="DUPLICATE_PAYMENT",
                    scenario_ids=["DP-1"],
                    severity="HIGH",
                    confidence=0.8,
                    file="app.py",
                    start_line=10,
                    end_line=12,
                    evidence_lines=["x"],
                    explanation="seed",
                    detector_source="STATIC",
                    state="ADVISORY",
                )
            )
    return finding_id


def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_read_then_write_commits(sqlite_factory) -> None:
    """dismiss reads the finding (autobegin) then writes — must succeed and persist."""
    finding_id = await _seed_finding(sqlite_factory)

    async with _client() as client:
        resp = await client.post(
            f"/findings/{finding_id}/dismiss", json={"reason": "false positive", "actor": "tester"}
        )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    # The write is durable and the audit event was written in the same unit of work.
    async with sqlite_factory() as session:
        finding = await session.get(Finding, finding_id)
        assert finding.state == "DISMISSED"
        audit_count = await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.object_id == finding_id)
        )
        assert audit_count == 1


@pytest.mark.asyncio
async def test_write_that_raises_rolls_back(sqlite_factory, monkeypatch) -> None:
    """If the audit append raises mid-handler, the partial remediation is rolled back."""
    finding_id = await _seed_finding(sqlite_factory)

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure after partial write")

    # propose_remediation adds a Remediation and flips finding.remediation_status BEFORE
    # appending the audit event; make that append explode.
    monkeypatch.setattr(app_module, "append_audit_event", _boom)

    async with _client() as client:
        resp = await client.post(
            f"/findings/{finding_id}/remediation/propose", json={"actor": "tester"}
        )
    assert resp.status_code == 500

    async with sqlite_factory() as session:
        rem_count = await session.scalar(
            select(func.count())
            .select_from(Remediation)
            .where(Remediation.finding_id == finding_id)
        )
        assert rem_count == 0, "remediation row must not persist after rollback"

        finding = await session.get(Finding, finding_id)
        assert finding.remediation_status == "NONE", "finding mutation must be rolled back"

        audit_count = await session.scalar(select(func.count()).select_from(AuditEvent))
        assert audit_count == 0, "no audit event should survive a rolled-back unit of work"
