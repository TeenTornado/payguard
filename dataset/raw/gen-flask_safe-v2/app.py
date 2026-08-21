import hashlib
import hmac
import os
from decimal import Decimal

import razorpay
from flask import Flask, abort, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

opts = {"auth": (KEY_ID, KEY_SECRET)}
if BASE_URL:
    opts["base_url"] = BASE_URL
client = razorpay.Client(**opts)

# In-memory store (production: use a database)
_processed_events: set = set()
_orders: dict = {}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")

    # Safe: check for existing order first
    if cart_id in _orders:
        return jsonify({"order_id": _orders[cart_id]["id"]})

    # Safe: amount computed server-side, already in paise
    amount_paise = 150000  # ₹1500 in paise

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    _orders[cart_id] = order
    return jsonify({"order_id": order["id"], "amount": order["amount"]})


@app.route("/webhook/razorpay", methods=["POST"])
def webhook():
    raw_body = request.get_data(as_text=False)
    sig = request.headers.get("X-Razorpay-Signature", "")
    event_id = request.headers.get("X-Razorpay-Event-Id", "")

    # Safe: verify over raw bytes
    try:
        client.utility.verify_webhook_signature(
            raw_body.decode(), sig, WEBHOOK_SECRET
        )
    except Exception:
        abort(400, "Invalid signature")

    # Safe: event-id dedup
    if event_id in _processed_events:
        return jsonify({"status": "already_processed"}), 200
    _processed_events.add(event_id)

    payload = request.json
    if payload.get("event") == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        _fulfill(payment["id"], payment["amount"])

    return jsonify({"status": "ok"}), 200


def _fulfill(payment_id: str, amount: int) -> None:
    app.logger.info(f"Fulfilling {payment_id}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
