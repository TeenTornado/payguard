"""
Razorpay protocol emulator (EMULATE mode).

Implements the Razorpay v1 API faithfully per docs/reference/razorpay-facts.md:
- Orders: POST /v1/orders, GET /v1/orders/:id
- Payments: checkout simulator (POST /v1/internal/simulate-checkout)
- Capture: POST /v1/payments/:id/capture
- Refunds: POST /v1/payments/:id/refund
- Webhook engine: sign, deliver, redeliver
- Checkout signature verification: HMAC_SHA256(secret, order_id|payment_id)
- Webhook signature verification: HMAC_SHA256(webhook_secret, raw_body)
- Error format: Razorpay-faithful JSON
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ─── Entity ID generators ─────────────────────────────────────────────────────

def _order_id() -> str:
    return "order_" + secrets.token_urlsafe(14)[:14]

def _payment_id() -> str:
    return "pay_" + secrets.token_urlsafe(14)[:14]

def _refund_id() -> str:
    return "rfnd_" + secrets.token_urlsafe(14)[:14]

def _event_id() -> str:
    return "evt_" + secrets.token_urlsafe(16)[:16]


# ─── Order ────────────────────────────────────────────────────────────────────

class OrderStatus(str, Enum):
    CREATED = "created"
    ATTEMPTED = "attempted"
    PAID = "paid"


@dataclass
class Order:
    id: str = field(default_factory=_order_id)
    amount: int = 0
    amount_paid: int = 0
    amount_due: int = 0
    currency: str = "INR"
    receipt: str | None = None
    status: OrderStatus = OrderStatus.CREATED
    notes: dict = field(default_factory=dict)
    partial_payment: bool = False
    created_at: int = field(default_factory=lambda: int(time.time()))
    entity: str = "order"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity": self.entity,
            "amount": self.amount,
            "amount_paid": self.amount_paid,
            "amount_due": self.amount_due,
            "currency": self.currency,
            "receipt": self.receipt,
            "status": self.status.value,
            "notes": self.notes,
            "partial_payment": self.partial_payment,
            "created_at": self.created_at,
        }


# ─── Payment ──────────────────────────────────────────────────────────────────

class PaymentStatus(str, Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    FAILED = "failed"


@dataclass
class Payment:
    id: str = field(default_factory=_payment_id)
    order_id: str = ""
    amount: int = 0
    currency: str = "INR"
    status: PaymentStatus = PaymentStatus.CREATED
    captured: bool = False
    method: str = "card"
    email: str = ""
    contact: str = ""
    description: str = ""
    created_at: int = field(default_factory=lambda: int(time.time()))
    entity: str = "payment"
    refunds: list[dict] = field(default_factory=list)
    _total_refunded: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "entity": self.entity,
            "order_id": self.order_id,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status.value,
            "captured": self.captured,
            "method": self.method,
            "email": self.email,
            "contact": self.contact,
            "description": self.description,
            "created_at": self.created_at,
        }


# ─── Razorpay-format errors ───────────────────────────────────────────────────

def razorpay_error(code: str, description: str, field: str | None = None) -> dict:
    return {
        "error": {
            "code": code,
            "description": description,
            "source": "business",
            "step": "payment_initiation",
            "reason": code.lower(),
            "metadata": {},
            "field": field,
        }
    }


BAD_REQUEST = "BAD_REQUEST_ERROR"


# ─── Emulator state ───────────────────────────────────────────────────────────

class RazorpayEmulator:
    """In-memory Razorpay emulator. One instance per gateway session."""

    def __init__(self, key_id: str = "rzp_test_DUMMY", key_secret: str = "dummy_secret",
                 webhook_secret: str = "dummy_webhook_secret") -> None:
        self.key_id = key_id
        self.key_secret = key_secret
        self.webhook_secret = webhook_secret
        self._orders: dict[str, Order] = {}
        self._payments: dict[str, Payment] = {}
        self._delivered_events: list[dict] = []

    # ── Orders ─────────────────────────────────────────────────────────────

    def create_order(self, data: dict) -> tuple[dict, int]:
        amount = data.get("amount")
        currency = data.get("currency", "INR")
        receipt = data.get("receipt")
        notes = data.get("notes", {})
        partial_payment = data.get("partial_payment", False)

        if not isinstance(amount, int) or amount < 100:
            return razorpay_error(
                BAD_REQUEST,
                "amount must be an integer in the smallest currency unit (paise). Minimum is 100.",
                "amount",
            ), 400

        order = Order(
            amount=amount,
            amount_due=amount,
            currency=currency,
            receipt=receipt,
            notes=notes,
            partial_payment=partial_payment,
        )
        self._orders[order.id] = order
        return order.to_dict(), 200

    def fetch_order(self, order_id: str) -> tuple[dict, int]:
        order = self._orders.get(order_id)
        if not order:
            return razorpay_error(BAD_REQUEST, f"The id provided does not exist"), 400
        return order.to_dict(), 200

    def list_payments_for_order(self, order_id: str) -> tuple[dict, int]:
        payments = [p.to_dict() for p in self._payments.values() if p.order_id == order_id]
        return {"entity": "collection", "count": len(payments), "items": payments}, 200

    # ── Checkout simulator ─────────────────────────────────────────────────

    def simulate_checkout(self, order_id: str, method: str = "card",
                          outcome: str = "success") -> tuple[dict, int]:
        """Simulate Razorpay Checkout completing a payment for an order."""
        order = self._orders.get(order_id)
        if not order:
            return razorpay_error(BAD_REQUEST, "Order not found"), 400
        if order.status == OrderStatus.PAID:
            return razorpay_error(BAD_REQUEST, "Order already paid"), 400

        if outcome == "failure":
            payment = Payment(
                order_id=order_id,
                amount=order.amount,
                currency=order.currency,
                status=PaymentStatus.FAILED,
                method=method,
            )
            self._payments[payment.id] = payment
            order.status = OrderStatus.ATTEMPTED
            return {"payment_id": payment.id, "status": "failed"}, 200

        payment = Payment(
            order_id=order_id,
            amount=order.amount,
            currency=order.currency,
            status=PaymentStatus.AUTHORIZED,
            method=method,
        )
        self._payments[payment.id] = payment
        order.status = OrderStatus.ATTEMPTED

        # Compute checkout signature
        signature = self._checkout_signature(order_id, payment.id)
        return {
            "payment_id": payment.id,
            "order_id": order_id,
            "razorpay_signature": signature,
        }, 200

    # ── Payments ──────────────────────────────────────────────────────────

    def capture_payment(self, payment_id: str, data: dict) -> tuple[dict, int]:
        payment = self._payments.get(payment_id)
        if not payment:
            return razorpay_error(BAD_REQUEST, "The id provided does not exist"), 400
        if payment.captured:
            return razorpay_error(BAD_REQUEST, "This payment has already been captured."), 400
        if payment.status not in (PaymentStatus.AUTHORIZED,):
            return razorpay_error(
                BAD_REQUEST, f"Payment cannot be captured in {payment.status.value} state."
            ), 400

        amount = data.get("amount", payment.amount)
        if amount != payment.amount:
            return razorpay_error(BAD_REQUEST, "Amount mismatch"), 400

        payment.captured = True
        payment.status = PaymentStatus.CAPTURED

        order = self._orders.get(payment.order_id)
        if order:
            order.status = OrderStatus.PAID
            order.amount_paid = payment.amount
            order.amount_due = 0

        return payment.to_dict(), 200

    def fetch_payment(self, payment_id: str) -> tuple[dict, int]:
        p = self._payments.get(payment_id)
        if not p:
            return razorpay_error(BAD_REQUEST, "The id provided does not exist"), 400
        return p.to_dict(), 200

    def create_refund(self, payment_id: str, data: dict) -> tuple[dict, int]:
        payment = self._payments.get(payment_id)
        if not payment:
            return razorpay_error(BAD_REQUEST, "The id provided does not exist"), 400
        if not payment.captured:
            return razorpay_error(BAD_REQUEST, "Payment is not captured"), 400

        amount = data.get("amount", payment.amount)
        if not isinstance(amount, int) or amount <= 0:
            return razorpay_error(BAD_REQUEST, "Refund amount must be a positive integer"), 400

        if payment._total_refunded + amount > payment.amount:
            return razorpay_error(
                BAD_REQUEST, "Refund amount exceeds captured amount"
            ), 400

        payment._total_refunded += amount
        if payment._total_refunded >= payment.amount:
            payment.status = PaymentStatus.REFUNDED

        refund = {
            "id": _refund_id(),
            "entity": "refund",
            "payment_id": payment_id,
            "amount": amount,
            "currency": payment.currency,
            "status": "processed",
            "created_at": int(time.time()),
        }
        payment.refunds.append(refund)
        return refund, 200

    # ── Signature verification ─────────────────────────────────────────────

    def _checkout_signature(self, order_id: str, payment_id: str) -> str:
        msg = f"{order_id}|{payment_id}"
        return hmac.new(
            self.key_secret.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()

    def verify_checkout_signature(self, order_id: str, payment_id: str, signature: str) -> bool:
        expected = self._checkout_signature(order_id, payment_id)
        return hmac.compare_digest(expected, signature)

    def sign_webhook(self, body: bytes) -> str:
        return hmac.new(
            self.webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:
        expected = self.sign_webhook(body)
        return hmac.compare_digest(expected, signature)

    # ── Webhook delivery ──────────────────────────────────────────────────

    def make_webhook_event(self, event_type: str, payment: Payment,
                           override_amount: int | None = None) -> tuple[dict, str]:
        """Build a signed webhook event. Returns (payload_dict, signature)."""
        import json

        pay_dict = payment.to_dict()
        if override_amount is not None:
            pay_dict["amount"] = override_amount

        payload: dict[str, Any] = {
            "entity": "event",
            "account_id": "acc_EMULATOR",
            "event": event_type,
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": pay_dict,
                }
            },
            "created_at": int(time.time()),
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = self.sign_webhook(body)
        event_id = _event_id()
        self._delivered_events.append({
            "event_id": event_id,
            "event_type": event_type,
            "body": body.decode(),
            "signature": signature,
        })
        return payload, signature, event_id

    # ── Statistics ────────────────────────────────────────────────────────

    def order_count(self) -> int:
        return len(self._orders)

    def payment_count(self) -> int:
        return len(self._payments)
