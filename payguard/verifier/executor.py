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
from datetime import UTC

import httpx

from payguard.shared.enums import (
    AuditActor,
    AuditEventKind,
    EvidenceTier,
    FindingState,
    VerificationStatus,
)
from payguard.verifier.scenarios import (
    SCENARIO_AC1_EXPECTED,
    SCENARIO_DP2_EXPECTED,
    SCENARIO_WI1_EXPECTED,
    VerificationOutcome,
)

log = logging.getLogger("payguard.verifier")

GATEWAY_MAX_ATTEMPTS = 3
GATEWAY_BACKOFF_SECONDS = 0.2
GATEWAY_TIMEOUT_SECONDS = 5.0

# Basic base64("rzp_test_DUMMY:dummy_secret") — the emulator's fixed test key. The gateway
# only checks the rzp_test_ prefix, never a live secret.
_DUMMY_AUTH = {"Authorization": "Basic cnpwX3Rlc3RfRFVNTVk6ZHVtbXlfc2VjcmV0"}

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
    from datetime import datetime

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
    vr.finished_at = datetime.now(UTC)

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

    Boots the target in a sandbox, drives the DP-2 scenario through the EMULATE gateway
    (bounded retries), streams each step into the VerificationResult, and persists the
    verdict. VERIFIED promotes a MEASURED amount; ERROR/BLOCKED/INCONCLUSIVE never do.
    """
    from datetime import datetime

    from sqlalchemy import select

    from payguard.shared.audit import append_audit_event
    from payguard.shared.config import get_settings
    from payguard.shared.models import Finding, Job, Repository, VerificationResult

    settings = get_settings()
    gateway_url = settings.gateway_url

    async with session_factory() as session:
        async with session.begin():
            vr = await session.get(VerificationResult, verification_id)
            finding = await session.scalar(select(Finding).where(Finding.id == finding_id))
            if vr is None or finding is None:
                log.error("Verification %s or finding %s missing", verification_id, finding_id)
                return
            vr.status = VerificationStatus.RUNNING.value
            vr.started_at = datetime.now(UTC)
            vr.responses_json = []
            repo = await session.scalar(select(Repository).where(Repository.id == finding.repository_id))
            job = await session.scalar(
                select(Job).where(Job.idempotency_key == f"verify:{verification_id}")
            )
            payload = (job.payload_json or {}) if job else {}
            target_dir = payload.get("target_dir") or (repo.locator if repo else None)
            order_amount = payload.get("order_amount_paise") or 150000
            scenario = _CLASS_TO_SCENARIO.get(finding.defect_class)
            await append_audit_event(
                session,
                actor=AuditActor.VERIFIER,
                event=AuditEventKind.VERIFICATION_STARTED,
                object_type="VerificationResult",
                object_id=verification_id,
                metadata={"finding_id": finding_id, "target_dir": target_dir},
            )

    steps: list[dict] = []

    async def emit(step: str, detail: str) -> None:
        steps.append({"step": step, "detail": detail})
        async with session_factory() as s2:
            async with s2.begin():
                v = await s2.get(VerificationResult, verification_id)
                if v is not None:
                    v.responses_json = list(steps)

    outcome = await drive_sandbox_scenario(gateway_url, target_dir, order_amount, emit, scenario=scenario)
    outcome.responses_log = steps

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


async def _noop_emit(step: str, detail: str) -> None:
    return None


# scenario id → (runner, expected-behavior text)
def _scenario_runners():
    return {
        "DP-2": (_run_dp2_on_sandbox, SCENARIO_DP2_EXPECTED),
        "WI-1": (_run_wi1_on_sandbox, SCENARIO_WI1_EXPECTED),
        "AC-1": (_run_ac1_on_sandbox, SCENARIO_AC1_EXPECTED),
    }


# defect class → scenario id
_CLASS_TO_SCENARIO = {
    "DUPLICATE_PAYMENT": "DP-2",
    "WEBHOOK_INTEGRITY": "WI-1",
    "AMOUNT_CURRENCY": "AC-1",
}


async def drive_sandbox_scenario(
    gateway_url: str,
    target_dir: str | None,
    order_amount_paise: int,
    emit=_noop_emit,
    scenario: str | None = None,
) -> VerificationOutcome:
    """Boot the target and run the scenario its manifest declares (DP-2 / WI-1 / AC-1).

    Common verdict grammar across all scenarios:
      - VERIFIED       → the defect reproduced (measured amount attached)
      - NOT_REPRODUCED → the safe behaviour held (no measured amount)
      - INCONCLUSIVE   → probe/response ambiguous
      - BLOCKED        → not a runnable target / unknown scenario / boot failed
      - ERROR          → gateway unavailable after bounded retries (e.g. gateway chaos)
    """
    from payguard.sandbox import SandboxError, boot_target, load_manifest

    manifest = load_manifest(target_dir) if target_dir else None
    if manifest is None:
        return VerificationOutcome(
            status=VerificationStatus.BLOCKED.value,
            expected_behavior="A runnable target is required to verify this finding.",
            observed_behavior=(
                "This finding's repository has no payguard.yml, so there is no runnable "
                "target to drive. Verification is blocked (static code can be read but not "
                "executed). Scan a target under examples/targets/ to reach a VERIFIED verdict."
            ),
            error_code="TARGET_UNAVAILABLE",
            measured_impact_paise=None,
        )

    scenario = (scenario or manifest.scenario or "").upper()
    entry = _scenario_runners().get(scenario)
    if entry is None:
        return VerificationOutcome(
            status=VerificationStatus.BLOCKED.value,
            expected_behavior="A supported scenario (DP-2 / WI-1 / AC-1) is required.",
            observed_behavior=f"Target declares scenario '{scenario}', which has no verifier.",
            error_code="UNSUPPORTED_SCENARIO",
            measured_impact_paise=None,
        )
    runner, _expected = entry

    await emit("boot", f"Booting sandbox target from {target_dir}")
    try:
        sandbox = await boot_target(target_dir, gateway_url)
    except SandboxError as exc:
        return VerificationOutcome(
            status=VerificationStatus.BLOCKED.value,
            expected_behavior=_expected,
            observed_behavior=f"Target failed to boot: {exc}",
            error_code="TARGET_BOOT_FAILED",
            measured_impact_paise=None,
        )

    await emit("health", f"Target healthy at {sandbox.base_url} "
                         f"(runtime={sandbox.runtime}, scenario={scenario})")
    try:
        return await runner(gateway_url, sandbox, order_amount_paise, emit)
    finally:
        await emit("teardown", "Tearing down sandbox")
        await sandbox.teardown()


# Back-compat alias (tests/callers): the manifest picks the scenario, so this works for any.
drive_dp2_sandbox = drive_sandbox_scenario


async def _run_dp2_on_sandbox(gateway_url, sandbox, order_amount_paise, emit) -> VerificationOutcome:
    deliveries: list[dict] = []
    total_attempts = 0
    async with httpx.AsyncClient() as client:
        # Establish a known key pair + webhook secret (matches the sandbox's env).
        try:
            await client.post(
                f"{gateway_url}/_test/reset",
                json={"key_id": "rzp_test_DUMMY", "key_secret": "dummy_secret",
                      "webhook_secret": "dummy_webhook_secret"},
                timeout=GATEWAY_TIMEOUT_SECONDS,
            )
        except _RETRYABLE_EXC:
            pass

        auth = {"Authorization": "Basic cnpwX3Rlc3RfRFVNTVk6ZHVtbXlfc2VjcmV0"}  # rzp_test_DUMMY:dummy_secret
        try:
            await emit("gateway", f"Creating a funded ₹{order_amount_paise // 100} order via EMULATE gateway")
            order_resp = await gateway_request(
                client, "POST", f"{gateway_url}/v1/orders",
                json={"amount": order_amount_paise, "currency": "INR"}, headers=auth,
            )
            total_attempts += len(order_resp.__dict__.get("_pg_attempts", []))
            order = _safe_json(order_resp)
            order_id = order.get("id", "")
            checkout_resp = await gateway_request(
                client, "POST", f"{gateway_url}/v1/internal/simulate-checkout",
                json={"order_id": order_id, "method": "card", "outcome": "success"},
            )
            payment_id = _safe_json(checkout_resp).get("payment_id", "")
            await gateway_request(
                client, "POST", f"{gateway_url}/v1/payments/{payment_id}/capture",
                json={"amount": order_amount_paise, "currency": "INR"}, headers=auth,
            )
        except GatewayUnavailable as gu:
            total_attempts += len(gu.attempts)
            return VerificationOutcome(
                status=VerificationStatus.ERROR.value,
                expected_behavior=SCENARIO_DP2_EXPECTED,
                observed_behavior=(
                    f"Gateway did not respond during payment setup after {len(gu.attempts)} "
                    "attempt(s). Verification aborted before any side effect; no impact measured."
                ),
                requests_log=[{"target": "gateway/setup", "attempts": gu.attempts}],
                error_code="GATEWAY_UNAVAILABLE",
                measured_impact_paise=None,
                attempts=total_attempts,
            )

        # Probe before.
        state_before = await _probe_state(sandbox.probe_url(order_id), client)
        count_before = (state_before or {}).get("fulfilled_count")
        if count_before is None:
            return VerificationOutcome(
                status=VerificationStatus.INCONCLUSIVE.value,
                expected_behavior=SCENARIO_DP2_EXPECTED,
                observed_behavior="State probe unreachable before delivery; cannot measure the side effect.",
                error_code="PROBE_UNAVAILABLE",
                measured_impact_paise=None,
                attempts=total_attempts,
            )
        await emit("probe-before", f"fulfilled_count(before) = {count_before}")

        # Deliver the SAME signed event twice (Razorpay retry semantics).
        event_id = f"evt_dp2_{payment_id}"
        for n in (1, 2):
            try:
                resp = await gateway_request(
                    client, "POST", f"{gateway_url}/v1/internal/deliver-webhook",
                    json={"target_url": sandbox.webhook_url, "event_type": "payment.captured",
                          "payment_id": payment_id, "custom_event_id": event_id},
                )
            except GatewayUnavailable as gu:
                total_attempts += len(gu.attempts)
                return VerificationOutcome(
                    status=VerificationStatus.ERROR.value,
                    expected_behavior=SCENARIO_DP2_EXPECTED,
                    observed_behavior=f"Gateway failed delivering webhook #{n} after {len(gu.attempts)} attempts.",
                    requests_log=[{"target": "gateway/deliver-webhook", "attempts": gu.attempts}],
                    webhook_deliveries=deliveries,
                    error_code="GATEWAY_UNAVAILABLE",
                    measured_impact_paise=None,
                    attempts=total_attempts,
                )
            total_attempts += len(resp.__dict__.get("_pg_attempts", []))
            body = _safe_json(resp)
            deliveries.append({
                "delivery": n,
                "event_id": event_id,
                "signature_status": "valid",
                "target_http_status": body.get("status"),
            })
            await emit("deliver", f"Delivered signed payment.captured #{n} (event_id={event_id}) "
                                  f"→ target HTTP {body.get('status')}")
            await asyncio.sleep(0.1)

        # Probe after.
        state_after = await _probe_state(sandbox.probe_url(order_id), client)
        count_after = (state_after or {}).get("fulfilled_count")
        if count_after is None:
            return VerificationOutcome(
                status=VerificationStatus.INCONCLUSIVE.value,
                expected_behavior=SCENARIO_DP2_EXPECTED,
                observed_behavior="State probe unreachable after delivery.",
                webhook_deliveries=deliveries,
                state_probe_before=state_before,
                error_code="PROBE_UNAVAILABLE",
                measured_impact_paise=None,
                attempts=total_attempts,
            )
        await emit("probe-after", f"fulfilled_count(after) = {count_after}")

    increment = count_after - count_before
    common = dict(
        expected_behavior=SCENARIO_DP2_EXPECTED,
        webhook_deliveries=deliveries,
        state_probe_before=state_before,
        state_probe_after=state_after,
        attempts=total_attempts,
    )
    if increment >= 2:
        await emit("verdict", f"VERIFIED — fulfilled twice for one payment (Δ={increment})")
        return VerificationOutcome(
            status=VerificationStatus.VERIFIED.value,
            observed_behavior=(
                f"Two deliveries of the same event_id={event_id} raised fulfilled_count "
                f"{count_before} → {count_after}. The order was fulfilled {increment} times for a "
                f"single payment — a duplicate fulfillment."
            ),
            proof_summary=(
                f"DP-2 VERIFIED: duplicate webhook delivery double-fulfilled order {order_id} "
                f"({count_before}→{count_after}). Measured impact = one duplicated ₹"
                f"{order_amount_paise // 100} fulfillment."
            ),
            measured_impact_paise=order_amount_paise,
            **common,
        )
    if increment == 1:
        await emit("verdict", "NOT_REPRODUCED — handler deduplicated the replay")
        return VerificationOutcome(
            status=VerificationStatus.NOT_REPRODUCED.value,
            observed_behavior=(
                f"fulfilled_count rose by only 1 ({count_before}→{count_after}); the handler "
                "deduplicated the replayed event. No duplicate fulfillment."
            ),
            measured_impact_paise=None,
            **common,
        )
    await emit("verdict", f"INCONCLUSIVE — no state change (Δ={increment})")
    return VerificationOutcome(
        status=VerificationStatus.INCONCLUSIVE.value,
        observed_behavior=f"fulfilled_count did not increase as expected ({count_before}→{count_after}).",
        error_code="NO_STATE_CHANGE",
        measured_impact_paise=None,
        **common,
    )


async def _setup_funded_payment(client, gateway_url, order_amount_paise) -> tuple[str, str, int]:
    """Reset the emulator, then create → checkout → capture an order. Returns
    (order_id, payment_id, gateway_attempts). Raises GatewayUnavailable under chaos."""
    try:
        await client.post(
            f"{gateway_url}/_test/reset",
            json={"key_id": "rzp_test_DUMMY", "key_secret": "dummy_secret",
                  "webhook_secret": "dummy_webhook_secret"},
            timeout=GATEWAY_TIMEOUT_SECONDS,
        )
    except _RETRYABLE_EXC:
        pass
    attempts = 0
    order_resp = await gateway_request(
        client, "POST", f"{gateway_url}/v1/orders",
        json={"amount": order_amount_paise, "currency": "INR"}, headers=_DUMMY_AUTH,
    )
    attempts += len(order_resp.__dict__.get("_pg_attempts", []))
    order_id = _safe_json(order_resp).get("id", "")
    checkout_resp = await gateway_request(
        client, "POST", f"{gateway_url}/v1/internal/simulate-checkout",
        json={"order_id": order_id, "method": "card", "outcome": "success"},
    )
    payment_id = _safe_json(checkout_resp).get("payment_id", "")
    cap_resp = await gateway_request(
        client, "POST", f"{gateway_url}/v1/payments/{payment_id}/capture",
        json={"amount": order_amount_paise, "currency": "INR"}, headers=_DUMMY_AUTH,
    )
    attempts += len(cap_resp.__dict__.get("_pg_attempts", []))
    return order_id, payment_id, attempts


def _gateway_error(expected: str, gu: "GatewayUnavailable", *, stage: str, extra=None) -> VerificationOutcome:
    return VerificationOutcome(
        status=VerificationStatus.ERROR.value,
        expected_behavior=expected,
        observed_behavior=(
            f"Gateway did not respond during {stage} after {len(gu.attempts)} attempt(s). "
            "Verification aborted before any side effect; no impact measured."
        ),
        requests_log=[{"target": f"gateway/{stage}", "attempts": gu.attempts}],
        webhook_deliveries=extra or [],
        error_code="GATEWAY_UNAVAILABLE",
        measured_impact_paise=None,
        attempts=len(gu.attempts),
    )


# ─── WI-1: forged webhook accepted (no signature verification) ────────────────


async def _run_wi1_on_sandbox(gateway_url, sandbox, order_amount_paise, emit) -> VerificationOutcome:
    async with httpx.AsyncClient() as client:
        try:
            await emit("gateway", f"Creating a funded ₹{order_amount_paise // 100} order via EMULATE gateway")
            order_id, payment_id, total_attempts = await _setup_funded_payment(
                client, gateway_url, order_amount_paise
            )
        except GatewayUnavailable as gu:
            return _gateway_error(SCENARIO_WI1_EXPECTED, gu, stage="setup")

        state_before = await _probe_state(sandbox.probe_url(order_id), client)
        count_before = (state_before or {}).get("fulfilled_count")
        if count_before is None:
            return VerificationOutcome(
                status=VerificationStatus.INCONCLUSIVE.value, expected_behavior=SCENARIO_WI1_EXPECTED,
                observed_behavior="State probe unreachable before delivery.",
                error_code="PROBE_UNAVAILABLE", measured_impact_paise=None, attempts=total_attempts,
            )
        await emit("probe-before", f"fulfilled_count(before) = {count_before}")

        # Deliver ONE FORGED event (invalid signature).
        try:
            resp = await gateway_request(
                client, "POST", f"{gateway_url}/v1/internal/deliver-webhook",
                json={"target_url": sandbox.webhook_url, "event_type": "payment.captured",
                      "payment_id": payment_id, "use_wrong_signature": True},
            )
        except GatewayUnavailable as gu:
            return _gateway_error(SCENARIO_WI1_EXPECTED, gu, stage="deliver-webhook")
        total_attempts += len(resp.__dict__.get("_pg_attempts", []))
        body = _safe_json(resp)
        target_status = body.get("status")
        deliveries = [{"delivery": 1, "signature_status": "forged/invalid",
                       "target_http_status": target_status}]
        await emit("deliver", f"Delivered a FORGED payment.captured (bad signature) "
                              f"→ target HTTP {target_status}")

        state_after = await _probe_state(sandbox.probe_url(order_id), client)
        count_after = (state_after or {}).get("fulfilled_count")
        if count_after is None:
            return VerificationOutcome(
                status=VerificationStatus.INCONCLUSIVE.value, expected_behavior=SCENARIO_WI1_EXPECTED,
                observed_behavior="State probe unreachable after delivery.",
                webhook_deliveries=deliveries, state_probe_before=state_before,
                error_code="PROBE_UNAVAILABLE", measured_impact_paise=None, attempts=total_attempts,
            )
        await emit("probe-after", f"fulfilled_count(after) = {count_after}")

    increment = count_after - count_before
    accepted_2xx = isinstance(target_status, int) and 200 <= target_status < 300
    common = dict(expected_behavior=SCENARIO_WI1_EXPECTED, webhook_deliveries=deliveries,
                  state_probe_before=state_before, state_probe_after=state_after, attempts=total_attempts)
    if accepted_2xx and increment >= 1:
        await emit("verdict", "VERIFIED — forged webhook accepted and fulfilled")
        return VerificationOutcome(
            status=VerificationStatus.VERIFIED.value,
            observed_behavior=(
                f"A forged webhook (invalid signature) returned HTTP {target_status} and raised "
                f"fulfilled_count {count_before}→{count_after}. Goods were released without a real payment."
            ),
            proof_summary=(
                f"WI-1 VERIFIED: handler accepted a forged signature (HTTP {target_status}) and fulfilled "
                f"order {order_id}. Measured impact = one ₹{order_amount_paise // 100} order released for free."
            ),
            measured_impact_paise=order_amount_paise, **common,
        )
    if (isinstance(target_status, int) and target_status >= 400) or increment == 0:
        await emit("verdict", "NOT_REPRODUCED — forged webhook rejected")
        return VerificationOutcome(
            status=VerificationStatus.NOT_REPRODUCED.value,
            observed_behavior=(
                f"The forged webhook was rejected (HTTP {target_status}); fulfilled_count unchanged "
                f"({count_before}→{count_after}). Signature verification held."
            ),
            measured_impact_paise=None, **common,
        )
    await emit("verdict", "INCONCLUSIVE")
    return VerificationOutcome(
        status=VerificationStatus.INCONCLUSIVE.value,
        observed_behavior=f"Ambiguous: HTTP {target_status}, Δ={increment}.",
        error_code="AMBIGUOUS_RESPONSE", measured_impact_paise=None, **common,
    )


# ─── AC-1: rupees-as-paise denomination error ─────────────────────────────────


async def _run_ac1_on_sandbox(gateway_url, sandbox, order_amount_paise, emit) -> VerificationOutcome:
    intended_inr = order_amount_paise // 100      # 150000 paise → ₹1500
    expected_paise = intended_inr * 100           # 150000
    charge_url = f"{sandbox.base_url}{sandbox.manifest.charge_path or '/charge'}"
    total_attempts = 0
    async with httpx.AsyncClient() as client:
        await emit("charge", f"POST /charge intended_amount_inr={intended_inr} (expect {expected_paise} paise)")
        try:
            charge_resp = await client.post(
                charge_url, json={"intended_amount_inr": intended_inr}, timeout=GATEWAY_TIMEOUT_SECONDS
            )
            charge = charge_resp.json()
        except Exception as exc:
            # The target's own call to the gateway may have failed — is the gateway down?
            try:
                await gateway_request(client, "GET", f"{gateway_url}/v1/orders/_probe_", headers=_DUMMY_AUTH)
            except GatewayUnavailable as gu:
                return _gateway_error(SCENARIO_AC1_EXPECTED, gu, stage="charge")
            return VerificationOutcome(
                status=VerificationStatus.INCONCLUSIVE.value, expected_behavior=SCENARIO_AC1_EXPECTED,
                observed_behavior=f"Target /charge did not respond cleanly: {exc}",
                error_code="TARGET_ERROR", measured_impact_paise=None, attempts=total_attempts,
            )

        order_id = charge.get("order_id")
        if not order_id:
            try:
                await gateway_request(client, "GET", f"{gateway_url}/v1/orders/_probe_", headers=_DUMMY_AUTH)
            except GatewayUnavailable as gu:
                return _gateway_error(SCENARIO_AC1_EXPECTED, gu, stage="charge")
            return VerificationOutcome(
                status=VerificationStatus.INCONCLUSIVE.value, expected_behavior=SCENARIO_AC1_EXPECTED,
                observed_behavior=f"Target /charge returned no order_id: {charge}",
                error_code="NO_ORDER_ID", measured_impact_paise=None, attempts=total_attempts,
            )

        try:
            order_resp = await gateway_request(
                client, "GET", f"{gateway_url}/v1/orders/{order_id}", headers=_DUMMY_AUTH
            )
        except GatewayUnavailable as gu:
            return _gateway_error(SCENARIO_AC1_EXPECTED, gu, stage="read-order")
        total_attempts += len(order_resp.__dict__.get("_pg_attempts", []))
        order = _safe_json(order_resp)
        actual = order.get("amount")
        await emit("order-amount", f"order {order_id} created with amount = {actual} paise")

    if not isinstance(actual, int):
        return VerificationOutcome(
            status=VerificationStatus.INCONCLUSIVE.value, expected_behavior=SCENARIO_AC1_EXPECTED,
            observed_behavior=f"Could not read the created order amount: {order}",
            error_code="NO_AMOUNT", measured_impact_paise=None, attempts=total_attempts,
        )

    common = dict(expected_behavior=SCENARIO_AC1_EXPECTED, attempts=total_attempts)
    if actual != expected_paise:
        discrepancy = abs(expected_paise - actual)
        await emit("verdict", f"VERIFIED — amount {actual} ≠ expected {expected_paise} paise")
        return VerificationOutcome(
            status=VerificationStatus.VERIFIED.value,
            observed_behavior=(
                f"Charging ₹{intended_inr} created an order for {actual} paise, not {expected_paise}. "
                f"The merchant charges ₹{actual / 100:.2f} instead of ₹{intended_inr:.2f} — a "
                "rupee/paise denomination error."
            ),
            proof_summary=(
                f"AC-1 VERIFIED: order {order_id} amount={actual} paise, expected {expected_paise} "
                f"(₹{intended_inr}×100). Measured discrepancy = {discrepancy} paise."
            ),
            measured_impact_paise=discrepancy, **common,
        )
    await emit("verdict", "NOT_REPRODUCED — amount correct")
    return VerificationOutcome(
        status=VerificationStatus.NOT_REPRODUCED.value,
        observed_behavior=f"Order created with the correct amount ({actual} paise = ₹{intended_inr}).",
        measured_impact_paise=None, **common,
    )
