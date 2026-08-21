import hashlib
import hmac
import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

_orders: dict = {}
_processed_events: set = set()


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    amount_paise = int(data.get("amount_paise", 9900))

    if cart_id in _orders:
        return jsonify({"order_id": _orders[cart_id]["id"]})

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    _orders[cart_id] = order
    return jsonify({"order_id": order["id"], "amount": amount_paise})


@app.route("/webhook", methods=["POST"])
def webhook():
    # Uses as_text=True — decodes bytes to str before HMAC
    body_text = request.get_data(as_text=True)
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(
        WEBHOOK_SECRET.encode(), body_text.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 400

    payload = request.get_json(force=True) or {}
    event_id = payload.get("id", "")
    event_type = payload.get("event", "")

    if event_id in _processed_events:
        return jsonify({"status": "duplicate"})
    _processed_events.add(event_id)

    if event_type == "payment.captured":
        order_id = (payload.get("payload", {})
                    .get("payment", {})
                    .get("entity", {})
                    .get("order_id", ""))
        return jsonify({"status": "ok", "order_id": order_id})
    return jsonify({"status": "ignored"})
