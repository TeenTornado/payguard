import hashlib
import hmac
import os
import razorpay
from flask import Flask, abort, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

_orders: dict = {}


def verify_razorpay_signature():
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        abort(400, "invalid signature")


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    if cart_id in _orders:
        return jsonify({"order_id": _orders[cart_id]["id"]})
    amount_paise = 9900
    order = client.order.create({"amount": amount_paise, "currency": "INR", "receipt": cart_id})
    _orders[cart_id] = order
    return jsonify({"order_id": order["id"]})


@app.route("/webhook", methods=["POST"])
def webhook():
    verify_razorpay_signature()
    payload = request.get_json(force=True) or {}
    if payload.get("event") == "payment.captured":
        return jsonify({"status": "ok"})
    return jsonify({"status": "ignored"})
