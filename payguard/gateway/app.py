"""
Gateway service — EMULATE mode + FORWARD_TEST recording proxy.
Phase 3: full EMULATE mode with Razorpay-faithful protocol.
"""
from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from payguard.gateway.emulator import RazorpayEmulator
from payguard.shared.chaos import read_chaos
from payguard.shared.config import validate_key_prefix

app = FastAPI(title="PayGuard Gateway", version="0.3.0")

GATEWAY_MODE = os.environ.get("GATEWAY_MODE", "EMULATE")

# One global emulator instance (for testing; production would be per-scan)
_global_emulator = RazorpayEmulator()


def _get_emulator(request: Request) -> RazorpayEmulator:
    """Get the emulator — either global or per-request (set by test harness)."""
    if hasattr(request.state, "emulator"):
        return request.state.emulator
    return _global_emulator


def _check_auth(request: Request) -> str | None:
    """Validate Basic auth. Returns key_id or raises."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    import base64
    try:
        decoded = base64.b64decode(auth[6:]).decode()
        key_id = decoded.split(":")[0]
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    try:
        validate_key_prefix(key_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=f"LIVE_KEY_REJECTED: {e}")
    return key_id


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "mode": GATEWAY_MODE}


# ─── Reset (for test harness) ────────────────────────────────────────────────

@app.post("/_test/reset")
async def reset_emulator(request: Request) -> dict:
    """Reset emulator state. Used by the test harness to isolate scenarios."""
    global _global_emulator
    body = await request.json()
    key_id = body.get("key_id", "rzp_test_DUMMY")
    key_secret = body.get("key_secret", "dummy_secret")
    webhook_secret = body.get("webhook_secret", "dummy_webhook_secret")
    validate_key_prefix(key_id)
    _global_emulator = RazorpayEmulator(key_id, key_secret, webhook_secret)
    return {"status": "reset"}


@app.get("/_test/stats")
async def emulator_stats(request: Request) -> dict:
    """Return emulator statistics for verification assertions."""
    em = _get_emulator(request)
    return {
        "order_count": em.order_count(),
        "payment_count": em.payment_count(),
        "delivered_events": em._delivered_events,
    }


# ─── Orders ──────────────────────────────────────────────────────────────────

@app.post("/v1/orders")
async def create_order(request: Request) -> Response:
    _check_auth(request)
    em = _get_emulator(request)
    data = await request.json()
    result, status = em.create_order(data)
    return JSONResponse(content=result, status_code=status)


@app.get("/v1/orders/{order_id}")
async def fetch_order(order_id: str, request: Request) -> Response:
    _check_auth(request)
    em = _get_emulator(request)
    result, status = em.fetch_order(order_id)
    return JSONResponse(content=result, status_code=status)


@app.get("/v1/orders/{order_id}/payments")
async def list_order_payments(order_id: str, request: Request) -> Response:
    _check_auth(request)
    em = _get_emulator(request)
    result, status = em.list_payments_for_order(order_id)
    return JSONResponse(content=result, status_code=status)


# ─── Checkout simulator ───────────────────────────────────────────────────────

@app.post("/v1/internal/simulate-checkout")
async def simulate_checkout(request: Request) -> Response:
    """
    Internal endpoint: simulate Razorpay Checkout completing a payment.
    Used by the verifier to drive scenarios without a browser.
    """
    em = _get_emulator(request)
    data = await request.json()
    order_id = data.get("order_id", "")
    method = data.get("method", "card")
    outcome = data.get("outcome", "success")
    result, status = em.simulate_checkout(order_id, method, outcome)
    return JSONResponse(content=result, status_code=status)


# ─── Payments ─────────────────────────────────────────────────────────────────

@app.post("/v1/payments/{payment_id}/capture")
async def capture_payment(payment_id: str, request: Request) -> Response:
    _check_auth(request)
    em = _get_emulator(request)
    data = await request.json()
    result, status = em.capture_payment(payment_id, data)
    return JSONResponse(content=result, status_code=status)


@app.get("/v1/payments/{payment_id}")
async def fetch_payment(payment_id: str, request: Request) -> Response:
    _check_auth(request)
    em = _get_emulator(request)
    result, status = em.fetch_payment(payment_id)
    return JSONResponse(content=result, status_code=status)


@app.post("/v1/payments/{payment_id}/refund")
async def create_refund(payment_id: str, request: Request) -> Response:
    _check_auth(request)
    em = _get_emulator(request)
    data = await request.json()
    result, status = em.create_refund(payment_id, data)
    return JSONResponse(content=result, status_code=status)


# ─── Webhook delivery (internal) ─────────────────────────────────────────────

@app.post("/v1/internal/deliver-webhook")
async def deliver_webhook(request: Request) -> Response:
    """
    Deliver a signed webhook event to a target URL.
    Used by verification scenarios to replay/forge events.
    """
    import httpx

    em = _get_emulator(request)
    data = await request.json()
    target_url: str = data["target_url"]
    event_type: str = data.get("event_type", "payment.captured")
    payment_id: str = data["payment_id"]
    override_amount: int | None = data.get("override_amount")
    use_wrong_signature: bool = data.get("use_wrong_signature", False)
    custom_event_id: str | None = data.get("custom_event_id")

    payment_result, pstatus = em.fetch_payment(payment_id)
    if pstatus != 200:
        return JSONResponse(content={"error": "payment not found"}, status_code=404)

    from payguard.gateway.emulator import Payment, PaymentStatus
    pay_dict = payment_result

    payload, signature, event_id = em.make_webhook_event(
        event_type, _dict_to_payment(pay_dict), override_amount
    )

    if custom_event_id:
        event_id = custom_event_id
    if use_wrong_signature:
        signature = "badinvalidsignature0000000000000000000000000000000000000000000000"

    body = json.dumps(payload, separators=(",", ":")).encode()

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(
                target_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Razorpay-Signature": signature,
                    "X-Razorpay-Event-Id": event_id,
                },
            )
            return JSONResponse(content={
                "status": resp.status_code,
                "body": resp.text[:1000],
                "event_id": event_id,
                "signature": signature[:16] + "...",
            })
        except Exception as e:
            return JSONResponse(content={"error": str(e)}, status_code=502)


def _dict_to_payment(d: dict):
    from payguard.gateway.emulator import Payment, PaymentStatus
    p = Payment()
    p.id = d["id"]
    p.order_id = d.get("order_id", "")
    p.amount = d.get("amount", 0)
    p.currency = d.get("currency", "INR")
    p.status = PaymentStatus(d.get("status", "captured"))
    p.captured = d.get("captured", True)
    return p


# ─── Chaos mode ──────────────────────────────────────────────────────────────
#
# Two sources of chaos, both server-side (the gateway is the dependency being made to
# fail, so injection belongs here — not in the verifier client):
#   1. The shared cross-process sentinel (payguard.shared.chaos). When its ``gateway``
#      switch is on, every payment/verification call (/v1/*) returns a deterministic 503.
#      Deterministic so the verifier's bounded-retry → ERROR path is reproducible in
#      tests and demos.
#   2. A legacy in-process toggle (/_test/chaos) kept for older harnesses, which injects
#      random 5xx / latency.
# /_test/* and /healthz are never chaos-gated so state can still be inspected.

_chaos_active = False


@app.post("/_test/chaos")
async def toggle_chaos(request: Request) -> dict:
    global _chaos_active
    data = await request.json()
    _chaos_active = data.get("enabled", False)
    return {"chaos": _chaos_active}


def _chaos_exempt(path: str) -> bool:
    return path.startswith("/_test") or path == "/healthz"


@app.middleware("http")
async def chaos_middleware(request: Request, call_next):
    import asyncio
    import random

    path = request.url.path
    if _chaos_exempt(path):
        return await call_next(request)

    if read_chaos().gateway:
        return JSONResponse(
            content={"error": {"code": "GATEWAY_UNAVAILABLE", "description": "Chaos: gateway down"}},
            status_code=503,
        )

    if _chaos_active:
        r = random.random()
        if r < 0.2:
            return JSONResponse(
                content={"error": {"code": "GATEWAY_ERROR", "description": "Chaos: 5xx"}},
                status_code=500,
            )
        elif r < 0.3:
            await asyncio.sleep(3.0)
    return await call_next(request)
