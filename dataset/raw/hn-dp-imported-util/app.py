import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

# Simulates: from utils.idempotency import is_idempotent_request, mark_processed
_idempotency_store: dict = {}


def is_idempotent_request(key: str):
    return _idempotency_store.get(key)


def mark_processed(key: str, value: dict):
    _idempotency_store[key] = value


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    amount_paise = 9900

    existing = is_idempotent_request(cart_id)
    if existing:
        return jsonify({"order_id": existing["id"], "cached": True})

    order = client.order.create({"amount": amount_paise, "currency": "INR", "receipt": cart_id})
    mark_processed(cart_id, order)
    return jsonify({"order_id": order["id"]})


@app.route("/webhook", methods=["POST"])
def webhook():
    import hmac
    import hashlib
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 400
    payload = request.get_json(force=True) or {}
    if payload.get("event") == "payment.captured":
        return jsonify({"status": "ok"})
    return jsonify({"status": "ignored"})
