"""
Static-blind positive: DUPLICATE_PAYMENT via dedup on wrong field.

The code uses `session_id` as the idempotency key instead of a stable
order identifier. Two separate checkout attempts from the same cart
produce different session_ids → two orders are created → duplicate payment.

Static rules look for the ABSENCE of a dedup check, but this code HAS a
dedup check (`if session_id in _order_cache`). The bug is the wrong key,
which a regex rule cannot detect without semantic understanding.
"""
import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

# Dedup cache — but keyed by session_id, not cart_id
_order_cache: dict = {}


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    amount_paise = data.get("amount_paise", 9900)

    # BUG: session_id changes on every browser session; two retries from
    # the same cart get different session_ids and both create orders.
    session_id = request.headers.get("X-Session-Id", "default")

    if session_id in _order_cache:
        return jsonify({"order_id": _order_cache[session_id]["id"]})

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    _order_cache[session_id] = order
    return jsonify({"order_id": order["id"], "amount": amount_paise})


@app.route("/webhook", methods=["POST"])
def webhook():
    import hmac
    import hashlib
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 400

    payload = request.get_json(force=True) or {}
    event = payload.get("event", "")
    if event == "payment.captured":
        order_id = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("order_id", "")
        # Process fulfillment
        return jsonify({"status": "ok"})
    return jsonify({"status": "ignored"})
