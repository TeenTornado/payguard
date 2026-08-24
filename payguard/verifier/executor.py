"""Verification executor — the arbiter path (ADR-001) with the money-safety choke point.

Two responsibilities live here, deliberately in one place:

1. **Bounded-retry gateway calls.** Every call to the gateway goes through
   :func:`gateway_request`, which retries a fixed number of times on 5xx / timeout /
   connection errors, records every attempt, and finally raises
   :class:`GatewayUnavailable`. This is what turns a chaotic gateway into a clean,
   terminal ERROR instead of an unbounded hang or a raw stack trace.

2. **The money-safety invariant (ADR-010).** :func:`persist_outcome` is the ONLY code
   that writes ``exposure_measured_paise`` onto a finding, and it writes it *only* for a
   ``VERIFIED`` verdict. Any other status — ERROR from gateway chaos, NOT_REPRODUCED,
   INCONCLUSIVE, BLOCKED — persists no MEASURED amount, even if a buggy scenario tried
   to attach one. MEASURED and ESTIMATED are never conflated.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from payguard.shared.enums import (
    AuditActor,
    AuditEventKind,
    EvidenceTier,
    FindingState,
    VerificationStatus,
)
from payguard.verifier.scenarios import SCENARIO_DP2_EXPECTED, VerificationOutcome

log = logging.getLogger("payguard.verifier")

GATEWAY_MAX_ATTEMPTS = 3
GATEWAY_BACKOFF_SECONDS = 0.2
GATEWAY_TIMEOUT_SECONDS = 5.0

_RETRYABLE_EXC = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)


class GatewayUnavailable(Exception):
    """Raised when a gateway call exhausts its retry budget."""

    def __init__(self, attempts: list[dict]):
        super().__init__(f"gateway unavailable after {len(attempts)} attempt(s)")
        self.attempts = attempts


async def gateway_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_attempts: int = GATEWAY_MAX_ATTEMPTS,
    **kwargs,
) -> httpx.Response:
    """Issue a gateway request with bounded retries. Records each attempt.

    Retries on HTTP 5xx and transport errors (timeout / connect / read). A 4xx is a
    definitive answer from the gateway and is returned as-is (not retried). On budget
    exhaustion raises :class:`GatewayUnavailable` carrying the per-attempt log.
    """
    attempts: list[dict] = []
    for i in range(1, max_attempts + 1):
        try:
            resp = await client.request(method, url, timeout=GATEWAY_TIMEOUT_SECONDS, **kwargs)
        except _RETRYABLE_EXC as exc:
            attempts.append({"attempt": i, "error": type(exc).__name__})
            if i < max_attempts:
                await asyncio.sleep(GATEWAY_BACKOFF_SECONDS)
                continue
            raise GatewayUnavailable(attempts) from exc

        attempts.append({"attempt": i, "status": resp.status_code})
        if resp.status_code >= 500:
            if i < max_attempts:
                await asyncio.sleep(GATEWAY_BACKOFF_SECONDS)
                continue
            raise GatewayUnavailable(attempts)
        resp.__dict__["_pg_attempts"] = attempts
        return resp

    raise GatewayUnavailable(attempts)  # pragma: no cover - loop always returns/raises


# ─── DP-2 verification (duplicate webhook delivery) ───────────────────────────


async def run_dp2_verification(
    gateway_url: str,
    target_webhook_url: str,
    state_probe_url: str | None,
    payment_id: str,
    order_amount_paise: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> VerificationOutcome:
    """Deliver the same signed event twice through the gateway; measure double fulfillment.

    If the gateway is unavailable (e.g. gateway chaos) the retries are exhausted and the
    outcome is a terminal ERROR with the attempt log — never VERIFIED, never a MEASURED
    amount.
    """
    own_client = client is None
    if client is None:
        client = httpx.AsyncClient()
    event_id = f"evt_dp2_{payment_id}"  # deterministic → idempotent re-runs
    total_attempts = 0
    deliveries: list[dict] = []
    try:
        state_before = await _probe_state(state_probe_url, client)
        count_before = (state_before or {}).get("fulfillment_count", 0)

        for n in (1, 2):
            resp = await gateway_request(
                client,
                "POST",
                f"{gateway_url}/v1/internal/deliver-webhook",
                json={
                    "target_url": target_webhook_url,
                    "event_type": "payment.captured",
                    "payment_id": payment_id,
                    "custom_event_id": event_id,
                },
            )
            attempts = resp.__dict__.get(
                "_pg_attempts", [{"attempt": 1, "status": resp.status_code}]
            )
            total_attempts += len(attempts)
            deliveries.append({"delivery": n, "attempts": attempts, "result": _safe_json(resp)})
            await asyncio.sleep(0.1)

        state_after = await _probe_state(state_probe_url, client)
        count_after = (state_after or {}).get("fulfillment_count", 0)
    except GatewayUnavailable as gu:
        total_attempts += len(gu.attempts)
        return VerificationOutcome(
            status=VerificationStatus.ERROR.value,
            expected_behavior=SCENARIO_DP2_EXPECTED,
            observed_behavior=(
                f"Gateway did not respond successfully after {len(gu.attempts)} attempt(s). "
                "Verification was aborted before any side effect could be observed, so no "
                "impact could be measured."
            ),
            requests_log=[{"target": "gateway/deliver-webhook", "attempts": gu.attempts}],
            webhook_deliveries=deliveries,
            error_code="GATEWAY_UNAVAILABLE",
            measured_impact_paise=None,  # money-safety: ERROR never carries a MEASURED amount
            attempts=total_attempts,
        )
    finally:
        if own_client:
            await client.aclose()

    increment = count_after - count_before
    if increment >= 2:
        return VerificationOutcome(
            status=VerificationStatus.VERIFIED.value,
            expected_behavior=SCENARIO_DP2_EXPECTED,
            observed_behavior=(
                f"fulfillment_count increased by {increment} ({count_before} → {count_after}) "
                f"after two deliveries of the same event_id={event_id}."
            ),
            webhook_deliveries=deliveries,
            state_probe_before=state_before,
            state_probe_after=state_after,
            proof_summary=(
                f"DP-2 VERIFIED: duplicate webhook delivery double-fulfilled "
                f"({count_before} → {count_after}); event_id={event_id}."
            ),
            measured_impact_paise=order_amount_paise,
            attempts=total_attempts,
        )
    if increment == 1:
        return VerificationOutcome(
            status=VerificationStatus.NOT_REPRODUCED.value,
            expected_behavior=SCENARIO_DP2_EXPECTED,
            observed_behavior=(
                f"fulfillment_count increased by only 1 ({count_before} → {count_after}); "
                "the handler deduplicated the replayed event."
            ),
            webhook_deliveries=deliveries,
            state_probe_before=state_before,
            state_probe_after=state_after,
            attempts=total_attempts,
        )
    return VerificationOutcome(
        status=VerificationStatus.INCONCLUSIVE.value,
        expected_behavior=SCENARIO_DP2_EXPECTED,
        observed_behavior=(
            f"fulfillment_count did not increase ({count_before} → {count_after}); "
            "no state probe change to confirm the side effect."
        ),
        webhook_deliveries=deliveries,
        state_probe_before=state_before,
        state_probe_after=state_after,
        error_code="NO_STATE_CHANGE" if state_probe_url else "PROBE_UNAVAILABLE",
        attempts=total_attempts,
    )


async def _probe_state(probe_url: str | None, client: httpx.AsyncClient) -> dict | None:
    if not probe_url:
        return None
    try:
        resp = await client.get(probe_url, timeout=GATEWAY_TIMEOUT_SECONDS)
        return resp.json()
    except Exception:
        return None


def _safe_json(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except Exception:
        return {"status": resp.status_code, "body": resp.text[:200]}


# ─── Persistence: the money-safety choke point ────────────────────────────────


async def persist_outcome(
    session,
    *,
    verification_id: str,
    finding,
    outcome: VerificationOutcome,
    tier: str = EvidenceTier.EMULATED.value,
):
    """Write a VerificationResult and, only for VERIFIED, promote the finding to MEASURED.

    This is the single writer of ``exposure_measured_paise``. It cannot be bypassed by a
    scenario returning a stray ``measured_impact_paise`` on a non-VERIFIED status — the
    amount is dropped unless the verdict is VERIFIED.
    """
    from datetime import datetime, timezone

    from payguard.shared.models import VerificationResult

    is_verified = outcome.status == VerificationStatus.VERIFIED.value
    measured = outcome.measured_impact_paise if is_verified else None

    vr = await session.get(VerificationResult, verification_id)
    if vr is None:
        vr = VerificationResult(
            id=verification_id,
            finding_id=finding.id,
            scenario_id="",
            tier=tier,
            expected_behavior=outcome.expected_behavior,
        )
        session.add(vr)

    vr.status = outcome.status
    vr.tier = tier
    vr.expected_behavior = outcome.expected_behavior
    vr.observed_behavior = outcome.observed_behavior
    vr.requests_json = outcome.requests_log
    vr.responses_json = outcome.responses_log
    vr.webhook_deliveries_json = outcome.webhook_deliveries
    vr.state_probe_before = outcome.state_probe_before
    vr.state_probe_after = outcome.state_probe_after
    vr.proof_summary = outcome.proof_summary or None
    vr.measured_impact_paise = measured
    vr.attempts = outcome.attempts
    vr.error_code = outcome.error_code
    vr.finished_at = datetime.now(timezone.utc)

    # Money-safety: a MEASURED amount and the VERIFIED state are promoted together, and
    # only on a VERIFIED verdict. Everything else leaves exposure MEASURED-null.
    if is_verified:
        finding.exposure_measured_paise = measured
        finding.state = FindingState.VERIFIED
    elif outcome.status == VerificationStatus.NOT_REPRODUCED.value:
        finding.state = FindingState.UNVERIFIED
    # ERROR / INCONCLUSIVE / BLOCKED: finding keeps its prior state; never MEASURED.
    return vr


# ─── Worker entry point ───────────────────────────────────────────────────────


async def execute_verification(session_factory, verification_id: str, finding_id: str) -> None:
    """Run a queued verification to a terminal state and persist it.

    Drives the gateway with bounded retries. Under gateway chaos every gateway call 503s,
    so setup exhausts its retries and the verdict is a terminal ERROR (the API-failure
    beat). Without a sandbox target to drive, a healthy gateway yields BLOCKED — honest,
    not faked.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from payguard.shared.audit import append_audit_event
    from payguard.shared.config import get_settings
    from payguard.shared.models import Finding, Job, VerificationResult

    settings = get_settings()
    gateway_url = settings.gateway_url

    # Mark RUNNING + audit start.
    async with session_factory() as session:
        async with session.begin():
            vr = await session.get(VerificationResult, verification_id)
            finding = await session.scalar(select(Finding).where(Finding.id == finding_id))
            if vr is None or finding is None:
                log.error("Verification %s or finding %s missing", verification_id, finding_id)
                return
            vr.status = VerificationStatus.RUNNING.value
            vr.started_at = datetime.now(timezone.utc)
            job = await session.scalar(
                select(Job).where(Job.idempotency_key == f"verify:{verification_id}")
            )
            payload = (job.payload_json or {}) if job else {}
            target_url = payload.get("target_url")
            probe_url = payload.get("probe_url")
            order_amount = payload.get("order_amount_paise", 150000)
            await append_audit_event(
                session,
                actor=AuditActor.VERIFIER,
                event=AuditEventKind.VERIFICATION_STARTED,
                object_type="VerificationResult",
                object_id=verification_id,
                metadata={"finding_id": finding_id},
            )

    outcome = await _drive_verification(gateway_url, target_url, probe_url, order_amount)

    async with session_factory() as session:
        async with session.begin():
            finding = await session.scalar(select(Finding).where(Finding.id == finding_id))
            await persist_outcome(
                session, verification_id=verification_id, finding=finding, outcome=outcome
            )
            completed = outcome.status == VerificationStatus.VERIFIED.value
            await append_audit_event(
                session,
                actor=AuditActor.VERIFIER,
                event=(
                    AuditEventKind.VERIFICATION_COMPLETED
                    if outcome.status
                    in (VerificationStatus.VERIFIED.value, VerificationStatus.NOT_REPRODUCED.value)
                    else AuditEventKind.VERIFICATION_FAILED
                ),
                object_type="VerificationResult",
                object_id=verification_id,
                metadata={
                    "status": outcome.status,
                    "error_code": outcome.error_code,
                    "attempts": outcome.attempts,
                    "measured_impact_paise": outcome.measured_impact_paise if completed else None,
                },
            )


async def _drive_verification(
    gateway_url: str, target_url: str | None, probe_url: str | None, order_amount_paise: int
) -> VerificationOutcome:
    """Set up a funded payment via the gateway, then run DP-2 against the target.

    Gateway setup goes through the retrying client, so gateway chaos surfaces here as a
    terminal ERROR before any target is touched.
    """
    async with httpx.AsyncClient() as client:
        # Reset is a /_test/* call (never chaos-gated) — establishes a known key pair.
        try:
            await client.post(
                f"{gateway_url}/_test/reset",
                json={"key_id": "rzp_test_DUMMY", "key_secret": "dummy_secret",
                      "webhook_secret": "dummy_webhook_secret"},
                timeout=GATEWAY_TIMEOUT_SECONDS,
            )
        except _RETRYABLE_EXC:
            pass  # handled by the first real gateway call below

        # Basic base64("rzp_test_DUMMY:dummy_secret") — the emulator's fixed test key.
        auth = {"Authorization": "Basic cnpwX3Rlc3RfRFVNTVk6ZHVtbXlfc2VjcmV0"}
        try:
            order_resp = await gateway_request(
                client, "POST", f"{gateway_url}/v1/orders",
                json={"amount": order_amount_paise, "currency": "INR"}, headers=auth,
            )
            order = _safe_json(order_resp)
            checkout_resp = await gateway_request(
                client, "POST", f"{gateway_url}/v1/internal/simulate-checkout",
                json={"order_id": order.get("id"), "method": "card", "outcome": "success"},
            )
            checkout = _safe_json(checkout_resp)
            payment_id = checkout.get("payment_id", "")
            await gateway_request(
                client, "POST", f"{gateway_url}/v1/payments/{payment_id}/capture",
                json={"amount": order_amount_paise, "currency": "INR"}, headers=auth,
            )
        except GatewayUnavailable as gu:
            return VerificationOutcome(
                status=VerificationStatus.ERROR.value,
                expected_behavior=SCENARIO_DP2_EXPECTED,
                observed_behavior=(
                    f"Gateway did not respond during payment setup after {len(gu.attempts)} "
                    "attempt(s). Verification aborted; no impact measured."
                ),
                requests_log=[{"target": "gateway/setup", "attempts": gu.attempts}],
                error_code="GATEWAY_UNAVAILABLE",
                measured_impact_paise=None,
                attempts=len(gu.attempts),
            )

        if not target_url:
            return VerificationOutcome(
                status=VerificationStatus.BLOCKED.value,
                expected_behavior=SCENARIO_DP2_EXPECTED,
                observed_behavior=(
                    "No sandbox target is running for this finding, so the webhook handler "
                    "cannot be driven. Verification is blocked (a sandbox runner is required "
                    "to reach a VERIFIED verdict with a MEASURED amount)."
                ),
                error_code="TARGET_UNAVAILABLE",
                measured_impact_paise=None,
            )

        return await run_dp2_verification(
            gateway_url, target_url, probe_url, payment_id, order_amount_paise, client=client
        )
