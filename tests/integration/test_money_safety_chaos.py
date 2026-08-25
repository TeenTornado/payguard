"""Money-safety under gateway chaos (ADR-010).

The invariant: a MEASURED exposure amount is written ONLY for a VERIFIED verdict. When the
gateway is failing (gateway chaos), a DP-2 verification must:
  - retry with a bounded budget,
  - record every attempt,
  - end in a terminal ERROR (never VERIFIED),
  - persist no MEASURED amount.

We drive the real gateway app (in-process) with the shared chaos sentinel turned on, then
assert the executor + the persistence choke point uphold the invariant. persist_outcome is
also tested directly, including a defensive case where a buggy scenario tries to smuggle a
measured amount onto a non-VERIFIED outcome.
"""
from __future__ import annotations

import uuid

import httpx
import pytest

from payguard.gateway.app import app as gateway_app
from payguard.shared.chaos import ChaosState, set_chaos, write_chaos
from payguard.shared.enums import VerificationStatus
from payguard.shared.models import Finding, Repository, Scan, VerificationResult
from payguard.verifier.executor import persist_outcome, run_dp2_verification
from payguard.verifier.scenarios import SCENARIO_DP2_EXPECTED, VerificationOutcome


@pytest.fixture
def chaos_file(monkeypatch, tmp_path):
    """Point the chaos sentinel at an isolated temp file for this test."""
    path = tmp_path / "chaos.json"
    monkeypatch.setenv("PAYGUARD_CHAOS_FILE", str(path))
    write_chaos(ChaosState())
    yield path
    write_chaos(ChaosState())


def _gateway_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=gateway_app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://gw")


@pytest.mark.asyncio
async def test_dp2_under_gateway_chaos_errors_without_measuring(chaos_file) -> None:
    set_chaos(gateway=True)  # gateway now returns 503 on /v1/*

    async with _gateway_client() as client:
        outcome = await run_dp2_verification(
            gateway_url="http://gw",
            target_webhook_url="http://target/hook",
            state_probe_url=None,
            payment_id="pay_dummy",
            order_amount_paise=150000,
            client=client,
        )

    assert outcome.status == VerificationStatus.ERROR.value
    assert outcome.error_code == "GATEWAY_UNAVAILABLE"
    assert outcome.measured_impact_paise is None
    assert outcome.attempts >= 2, "must retry before giving up"
    # The attempt log is preserved as evidence.
    assert outcome.requests_log and outcome.requests_log[0]["attempts"]


@pytest.mark.asyncio
async def test_gateway_recovers_when_chaos_off(chaos_file) -> None:
    """Control: with chaos off the same gateway call is not a 5xx (no false ERROR)."""
    set_chaos(gateway=False)
    async with _gateway_client() as client:
        resp = await client.post(
            "http://gw/v1/internal/deliver-webhook",
            json={"target_url": "http://target/hook", "payment_id": "pay_x"},
        )
    # payment not found → 404 (a definitive answer), NOT a retryable 5xx.
    assert resp.status_code < 500


async def _seed_finding(factory) -> str:
    repo_id, scan_id, finding_id = (str(uuid.uuid4()) for _ in range(3))
    async with factory() as session:
        async with session.begin():
            session.add(Repository(id=repo_id, source_type="LOCAL_PATH", locator="/tmp/x"))
            session.add(Scan(id=scan_id, repository_id=repo_id, state="DONE"))
            session.add(
                Finding(
                    id=finding_id, scan_id=scan_id, repository_id=repo_id,
                    defect_class="DUPLICATE_PAYMENT", scenario_ids=["DP-2"], severity="HIGH",
                    confidence=0.8, file="app.py", start_line=1, end_line=2,
                    evidence_lines=["x"], explanation="seed", detector_source="STATIC",
                    state="QUEUED_FOR_VERIFICATION",
                )
            )
    return finding_id


async def _seed_pending_vr(factory, finding_id: str) -> str:
    vid = str(uuid.uuid4())
    async with factory() as session:
        async with session.begin():
            session.add(
                VerificationResult(
                    id=vid, finding_id=finding_id, scenario_id="DP-2",
                    status=VerificationStatus.PENDING.value, tier="EMULATED",
                    expected_behavior=SCENARIO_DP2_EXPECTED,
                )
            )
    return vid


@pytest.mark.asyncio
async def test_persist_error_outcome_writes_no_measured_exposure(sqlite_factory) -> None:
    finding_id = await _seed_finding(sqlite_factory)
    vid = await _seed_pending_vr(sqlite_factory, finding_id)

    error_outcome = VerificationOutcome(
        status=VerificationStatus.ERROR.value,
        expected_behavior=SCENARIO_DP2_EXPECTED,
        observed_behavior="gateway down",
        error_code="GATEWAY_UNAVAILABLE",
        measured_impact_paise=None,
        attempts=3,
    )

    async with sqlite_factory() as session:
        async with session.begin():
            finding = await session.get(Finding, finding_id)
            await persist_outcome(
                session, verification_id=vid, finding=finding, outcome=error_outcome
            )

    async with sqlite_factory() as session:
        finding = await session.get(Finding, finding_id)
        vr = await session.get(VerificationResult, vid)
    assert finding.exposure_measured_paise is None
    assert finding.state != "VERIFIED"
    assert vr.status == VerificationStatus.ERROR.value
    assert vr.attempts == 3
    assert vr.error_code == "GATEWAY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_persist_verified_outcome_promotes_measured_exposure(sqlite_factory) -> None:
    finding_id = await _seed_finding(sqlite_factory)
    vid = await _seed_pending_vr(sqlite_factory, finding_id)

    verified = VerificationOutcome(
        status=VerificationStatus.VERIFIED.value,
        expected_behavior=SCENARIO_DP2_EXPECTED,
        observed_behavior="double fulfillment observed",
        proof_summary="DP-2 VERIFIED",
        measured_impact_paise=150000,
        attempts=2,
    )

    async with sqlite_factory() as session:
        async with session.begin():
            finding = await session.get(Finding, finding_id)
            await persist_outcome(session, verification_id=vid, finding=finding, outcome=verified)

    async with sqlite_factory() as session:
        finding = await session.get(Finding, finding_id)
        vr = await session.get(VerificationResult, vid)
    assert finding.exposure_measured_paise == 150000
    assert finding.state == "VERIFIED"
    assert vr.measured_impact_paise == 150000
    assert vr.status == VerificationStatus.VERIFIED.value


@pytest.mark.asyncio
async def test_persist_drops_smuggled_measured_amount_on_non_verified(sqlite_factory) -> None:
    """Defense in depth: a non-VERIFIED outcome carrying a measured amount is scrubbed."""
    finding_id = await _seed_finding(sqlite_factory)
    vid = await _seed_pending_vr(sqlite_factory, finding_id)

    smuggled = VerificationOutcome(
        status=VerificationStatus.NOT_REPRODUCED.value,
        expected_behavior=SCENARIO_DP2_EXPECTED,
        observed_behavior="dedup worked",
        measured_impact_paise=999999,  # must be ignored — status is not VERIFIED
        attempts=1,
    )

    async with sqlite_factory() as session:
        async with session.begin():
            finding = await session.get(Finding, finding_id)
            await persist_outcome(session, verification_id=vid, finding=finding, outcome=smuggled)

    async with sqlite_factory() as session:
        finding = await session.get(Finding, finding_id)
        vr = await session.get(VerificationResult, vid)
    assert finding.exposure_measured_paise is None
    assert vr.measured_impact_paise is None
