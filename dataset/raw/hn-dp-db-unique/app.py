import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

# Simulated DB with unique constraint on receipt column
_db_orders: dict = {}  # receipt -> order dict; INSERT raises KeyError if exists


class IntegrityError(Exception):
    pass


def db_insert_order(receipt: str, order: dict):
    # Enforces UNIQUE constraint on receipt; raises IntegrityError on duplicate
    if receipt in _db_orders:
        raise IntegrityError(f"duplicate key value: receipt={receipt}")
    _db_orders[receipt] = order


def db_find_order(receipt: str):
    return _db_orders.get(receipt)


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    amount_paise = 9900

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    try:
        db_insert_order(cart_id, order)
    except IntegrityError:
        existing = db_find_order(cart_id)
        return jsonify({"order_id": existing["id"], "cached": True})

    return jsonify({"order_id": order["id"], "amount": amount_paise})


@app.route("/webhook", methods=["POST"])
def webhook():
    import hmac
    import hashlib
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 400
    payload = request.get_json(force=True) or {}
    if payload.get("event") == "payment.captured":
        return jsonify({"status": "ok"})
    return jsonify({"status": "ignored"})
