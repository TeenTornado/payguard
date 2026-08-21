import hashlib
import hmac
import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

_orders: dict = {}
_processed_event_ids: dict = {}


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
    raw_body = request.get_data()
    provided_sig = request.headers.get("X-Razorpay-Signature", "")

    mac = hmac.new(_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256)
    expected_sig = mac.hexdigest()

    if not hmac.compare_digest(provided_sig, expected_sig):
        return jsonify({"error": "signature mismatch"}), 400

    payload = request.get_json(force=True) or {}
    event_id = payload.get("id", "")

    if _processed_event_ids.get(event_id):
        return jsonify({"status": "already_processed"}), 200

    _processed_event_ids[event_id] = True

    if payload.get("event") == "payment.captured":
        return jsonify({"status": "ok"})
    return jsonify({"status": "ignored"})
