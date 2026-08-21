"""
Demo merchant — realistic AI-generated-looking Flask shop.

Seeded defects (for demo purposes):
  - DP-2: webhook handler fulfills without event-id dedup (CRITICAL)
  - WI-1: webhook accepts forged signatures (CRITICAL) — signature check present but broken
  - AC-1: amount_inr passed to Razorpay without *100 conversion

Safe decoys (to show false-positive trap):
  - DB unique constraint on order creation (LLM may flag DP-R1 but verifier catches it's safe)

Note: RAZORPAY_BASE_URL env var routes all Razorpay SDK calls to the PayGuard gateway.
"""
import os

import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy_secret")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret")
RAZORPAY_BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

# Configure SDK base URL if provided (routes to PayGuard gateway)
client_opts: dict = {"auth": (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)}
if RAZORPAY_BASE_URL:
    client_opts["base_url"] = RAZORPAY_BASE_URL

client = razorpay.Client(**client_opts)

# In-memory state (production would use a DB)
_orders: dict = {}
_fulfillment_count = 0
_created_orders: list[str] = []  # for dedup tracking (safe decoy)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/probe/fulfillment-count")
def probe():
    return jsonify({"fulfillment_count": _fulfillment_count})


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    intended_amount_inr = data.get("intended_amount_inr", 1500)
    cart_id = data.get("cart_id", "cart_001")

    # DEFECT AC-1: amount in rupees, not paise
    order = client.order.create({
        "amount": intended_amount_inr,  # BUG: should be intended_amount_inr * 100
        "currency": "INR",
        "receipt": cart_id,
    })
    _orders[order["id"]] = order
    _created_orders.append(cart_id)
    return jsonify({"order_id": order["id"], "amount": order["amount"]})


@app.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():
    global _fulfillment_count

    raw_body = request.get_data(as_text=False)
    signature = request.headers.get("X-Razorpay-Signature", "")

    # DEFECT WI-1: signature verification present but uses re-parsed body (broken)
    # This verifies a different signature than what Razorpay sends
    try:
        import json
        reparsed = json.loads(raw_body)  # parse then re-serialize = different bytes
        import json as j
        body_str = j.dumps(reparsed)
        client.utility.verify_webhook_signature(body_str, signature, RAZORPAY_WEBHOOK_SECRET)
    except Exception:
        pass  # BUG: silently ignores verification failure

    payload = request.json
    event = payload.get("event", "")

    if event == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        payment_id = payment["id"]
        amount = payment["amount"]

        # DEFECT DP-2: no event-id dedup — Razorpay delivers at-least-once
        _fulfillment_count += 1
        _do_fulfillment(payment_id, amount)

    return jsonify({"status": "ok"}), 200


def _do_fulfillment(payment_id: str, amount: int):
    """Side effect: ship order, grant access, etc."""
    app.logger.info(f"Fulfilling order: payment={payment_id}, amount={amount}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
