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
_fulfilled_orders: set = set()


def confirm_payment(payment_id: str) -> bool:
    # External call — assume always succeeds in dev
    return True


def fulfill_order(order_id: str, payment_id: str) -> dict:
    # No event_id dedup here — relies on caller to deduplicate
    if confirm_payment(payment_id):
        _fulfilled_orders.add(order_id)
        return {"fulfilled": True, "order_id": order_id}
    return {"fulfilled": False}


def handle_payment_captured(event: dict) -> dict:
    payment = event.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = payment.get("order_id", "")
    payment_id = payment.get("id", "")
    # Delegates to fulfill_order without passing event_id for dedup
    return fulfill_order(order_id, payment_id)


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
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 400

    payload = request.get_json(force=True) or {}
    event_type = payload.get("event", "")

    if event_type == "payment.captured":
        result = handle_payment_captured(payload)
        return jsonify({"status": "ok", **result})
    return jsonify({"status": "ignored"})
