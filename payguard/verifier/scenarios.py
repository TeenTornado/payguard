"""
Verification scenario definitions.

Each scenario is a function:
  run(gateway_url, target_url, state_probe_url, manifest) -> VerificationOutcome

The verifier is the arbiter (ADR-001): only it may declare VERIFIED.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class VerificationOutcome:
    status: str  # VERIFIED / NOT_REPRODUCED / INCONCLUSIVE / BLOCKED / ERROR
    expected_behavior: str
    observed_behavior: str
    requests_log: list[dict] = field(default_factory=list)
    responses_log: list[dict] = field(default_factory=list)
    webhook_deliveries: list[dict] = field(default_factory=list)
    state_probe_before: dict | None = None
    state_probe_after: dict | None = None
    proof_summary: str = ""
    measured_impact_paise: int | None = None
    error_code: str | None = None
    attempts: int = 1  # total gateway attempts made (incl. retries)


async def _probe_state(probe_url: str | None, client: httpx.AsyncClient) -> dict | None:
    if not probe_url:
        return None
    try:
        resp = await client.get(probe_url, timeout=5.0)
        return resp.json()
    except Exception:
        return None


async def _deliver_webhook(
    gateway_url: str,
    target_webhook_url: str,
    payment_id: str,
    event_id: str | None = None,
    use_wrong_signature: bool = False,
    override_amount: int | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict:
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.post(
            f"{gateway_url}/v1/internal/deliver-webhook",
            json={
                "target_url": target_webhook_url,
                "event_type": "payment.captured",
                "payment_id": payment_id,
                "use_wrong_signature": use_wrong_signature,
                "override_amount": override_amount,
                "custom_event_id": event_id,
            },
        )
        return resp.json()
    finally:
        if should_close:
            await client.aclose()


# ─── DP-2: Webhook handler does double fulfillment on duplicate delivery ──────

SCENARIO_DP2_EXPECTED = (
    "Delivering the same validly signed payment.captured event twice "
    "(same X-Razorpay-Event-Id) causes the side effect (fulfillment_count) "
    "to be observed twice (state_probe_count == 2)."
)


async def run_dp2(
    gateway_url: str,
    target_webhook_url: str,
    state_probe_url: str | None,
    payment_id: str,
) -> VerificationOutcome:
    """
    DP-2: Deliver the same signed payment.captured event twice.
    Pass condition: side effect executed twice (state_probe_count increases by 2).
    """
    FIXED_EVENT_ID = "evt_dp2_test_replay_" + str(int(time.time()))

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Record initial state
        state_before = await _probe_state(state_probe_url, client)
        count_before = (state_before or {}).get("fulfillment_count", 0)

        deliveries = []

        # Delivery 1
        d1 = await _deliver_webhook(
            gateway_url, target_webhook_url, payment_id,
            event_id=FIXED_EVENT_ID, client=client
        )
        deliveries.append({"delivery": 1, "result": d1})
        await asyncio.sleep(0.2)

        # Delivery 2 — same event_id (Razorpay retry simulation)
        d2 = await _deliver_webhook(
            gateway_url, target_webhook_url, payment_id,
            event_id=FIXED_EVENT_ID, client=client
        )
        deliveries.append({"delivery": 2, "result": d2})
        await asyncio.sleep(0.2)

        # Record final state
        state_after = await _probe_state(state_probe_url, client)
        count_after = (state_after or {}).get("fulfillment_count", 0)

    increment = count_after - count_before

    if increment >= 2:
        return VerificationOutcome(
            status="VERIFIED",
            expected_behavior=SCENARIO_DP2_EXPECTED,
            observed_behavior=(
                f"fulfillment_count increased by {increment} "
                f"(from {count_before} to {count_after}) after two deliveries of the same event."
            ),
            webhook_deliveries=deliveries,
            state_probe_before=state_before,
            state_probe_after=state_after,
            proof_summary=(
                f"DP-2 VERIFIED: duplicate webhook delivery caused fulfillment_count "
                f"to increment twice ({count_before} → {count_after}). "
                f"Both deliveries used event_id={FIXED_EVENT_ID}."
            ),
            measured_impact_paise=None,  # impact depends on order amount, set by caller
        )
    elif increment == 1:
        return VerificationOutcome(
            status="NOT_REPRODUCED",
            expected_behavior=SCENARIO_DP2_EXPECTED,
            observed_behavior=(
                f"fulfillment_count increased by only 1 (from {count_before} to {count_after}). "
                "The handler appears to have deduplicated the second delivery."
            ),
            webhook_deliveries=deliveries,
            state_probe_before=state_before,
            state_probe_after=state_after,
        )
    elif state_probe_url is None:
        return VerificationOutcome(
            status="INCONCLUSIVE",
            expected_behavior=SCENARIO_DP2_EXPECTED,
            observed_behavior="No state probe available. Both deliveries returned 2xx but cannot confirm side effect count.",
            webhook_deliveries=deliveries,
            error_code="PROBE_UNAVAILABLE",
        )
    else:
        return VerificationOutcome(
            status="INCONCLUSIVE",
            expected_behavior=SCENARIO_DP2_EXPECTED,
            observed_behavior=(
                f"fulfillment_count did not change (before={count_before}, after={count_after}). "
                "Either the webhook endpoint returned errors or the probe is broken."
            ),
            webhook_deliveries=deliveries,
            state_probe_before=state_before,
            state_probe_after=state_after,
            error_code="NO_STATE_CHANGE",
        )


# ─── WI-1: Webhook accepts forged signature ────────────────────────────────────

SCENARIO_WI1_EXPECTED = (
    "A POST to the webhook endpoint with an invalid X-Razorpay-Signature "
    "is accepted (2xx response) and the side effect executes."
)


async def run_wi1(
    gateway_url: str,
    target_webhook_url: str,
    state_probe_url: str | None,
    payment_id: str,
) -> VerificationOutcome:
    """WI-1: Deliver a forged webhook (wrong signature). Pass: side effect executes."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        state_before = await _probe_state(state_probe_url, client)
        count_before = (state_before or {}).get("fulfillment_count", 0)

        d = await _deliver_webhook(
            gateway_url, target_webhook_url, payment_id,
            use_wrong_signature=True, client=client
        )
        await asyncio.sleep(0.2)

        state_after = await _probe_state(state_probe_url, client)
        count_after = (state_after or {}).get("fulfillment_count", 0)

    http_status = d.get("status", 0)
    increment = count_after - count_before

    # Vulnerable: returns 2xx AND side effect executed
    if http_status in range(200, 300) and increment >= 1:
        return VerificationOutcome(
            status="VERIFIED",
            expected_behavior=SCENARIO_WI1_EXPECTED,
            observed_behavior=(
                f"Forged webhook returned HTTP {http_status} and "
                f"fulfillment_count increased by {increment}."
            ),
            webhook_deliveries=[d],
            state_probe_before=state_before,
            state_probe_after=state_after,
            proof_summary=(
                f"WI-1 VERIFIED: webhook handler accepted forged signature "
                f"(HTTP {http_status}), side effect count {count_before}→{count_after}."
            ),
        )
    elif http_status in range(400, 500):
        return VerificationOutcome(
            status="NOT_REPRODUCED",
            expected_behavior=SCENARIO_WI1_EXPECTED,
            observed_behavior=f"Webhook correctly rejected forged signature with HTTP {http_status}.",
            webhook_deliveries=[d],
            state_probe_before=state_before,
            state_probe_after=state_after,
        )
    else:
        return VerificationOutcome(
            status="INCONCLUSIVE",
            expected_behavior=SCENARIO_WI1_EXPECTED,
            observed_behavior=f"HTTP {http_status}, count delta={increment}. Ambiguous.",
            webhook_deliveries=[d],
            state_probe_before=state_before,
            state_probe_after=state_after,
            error_code="AMBIGUOUS_RESPONSE",
        )


# ─── AC-1: Amount denomination error ──────────────────────────────────────────

SCENARIO_AC1_EXPECTED = (
    "Driving the charge endpoint with intended_amount_inr=1500 (₹1,500) "
    "creates a Razorpay order with amount != 150000 paise, "
    "indicating a rupee/paise denomination error."
)


async def run_ac1(
    gateway_url: str,
    target_charge_url: str,
    intended_amount_inr: int = 1500,
) -> VerificationOutcome:
    """AC-1: Drive charge endpoint and check created order amount."""
    import asyncio

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.post(
                target_charge_url,
                json={"intended_amount_inr": intended_amount_inr},
            )
        except Exception as e:
            return VerificationOutcome(
                status="BLOCKED",
                expected_behavior=SCENARIO_AC1_EXPECTED,
                observed_behavior=str(e),
                error_code="TARGET_UNREACHABLE",
            )

        try:
            body = resp.json()
        except Exception:
            return VerificationOutcome(
                status="INCONCLUSIVE",
                expected_behavior=SCENARIO_AC1_EXPECTED,
                observed_behavior=f"HTTP {resp.status_code}, non-JSON response",
                error_code="PARSE_ERROR",
            )

        # Query gateway for the created order amount
        order_id = body.get("order_id")
        if not order_id:
            return VerificationOutcome(
                status="INCONCLUSIVE",
                expected_behavior=SCENARIO_AC1_EXPECTED,
                observed_behavior=f"No order_id in response: {body}",
                error_code="NO_ORDER_ID",
            )

        order_resp = await client.get(
            f"{gateway_url}/v1/orders/{order_id}",
            headers={"Authorization": "Basic cnpwX3Rlc3RfRFVNTVk6ZHVtbXlfc2VjcmV0"},
        )
        order = order_resp.json()
        actual_amount = order.get("amount", -1)
        expected_paise = intended_amount_inr * 100

    if actual_amount != expected_paise:
        return VerificationOutcome(
            status="VERIFIED",
            expected_behavior=SCENARIO_AC1_EXPECTED,
            observed_behavior=(
                f"Order created with amount={actual_amount} paise. "
                f"Expected {expected_paise} paise (₹{intended_amount_inr} × 100). "
                f"Actual ₹{actual_amount/100:.2f} instead of ₹{intended_amount_inr:.2f}."
            ),
            proof_summary=(
                f"AC-1 VERIFIED: amount denomination error confirmed. "
                f"Order {order_id} has amount={actual_amount}, expected={expected_paise}. "
                f"{'100× error' if actual_amount * 100 == expected_paise else 'Unknown denomination error'}."
            ),
            measured_impact_paise=abs(expected_paise - actual_amount),
        )
    else:
        return VerificationOutcome(
            status="NOT_REPRODUCED",
            expected_behavior=SCENARIO_AC1_EXPECTED,
            observed_behavior=f"Order amount={actual_amount} paise, exactly {expected_paise} as expected.",
        )


import asyncio
