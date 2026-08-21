import os
from decimal import Decimal, ROUND_HALF_UP
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

_orders: dict = {}

PRICE_INR = Decimal("199.99")


def to_paise(price_inr: Decimal) -> int:
    paise = (price_inr * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(paise)


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")

    if cart_id in _orders:
        return jsonify({"order_id": _orders[cart_id]["id"]})

    amount_paise = to_paise(PRICE_INR)
    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    _orders[cart_id] = order
    return jsonify({"order_id": order["id"], "amount_paise": amount_paise})


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
