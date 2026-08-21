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

DISCOUNT_RATE = 0.10


def calculate_order_amount(amount_inr: float) -> int:
    """Convert INR to paise."""
    return int(amount_inr * 100)


def apply_discount(amount: int, rate: float) -> int:
    """Apply discount percentage. Returns discounted amount in paise."""
    # Incorrectly treats `amount` as INR and multiplies by 100 again
    discounted_inr = amount * (1 - rate)
    return int(discounted_inr * 100)


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    price_inr = float(data.get("price_inr", 99.0))

    if cart_id in _orders:
        return jsonify({"order_id": _orders[cart_id]["id"]})

    amount_paise = calculate_order_amount(price_inr)
    final_amount = apply_discount(amount_paise, DISCOUNT_RATE)

    order = client.order.create({
        "amount": final_amount,
        "currency": "INR",
        "receipt": cart_id,
    })
    _orders[cart_id] = order
    return jsonify({"order_id": order["id"], "amount": final_amount})


@app.route("/webhook", methods=["POST"])
def webhook():
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 400

    payload = request.get_json(force=True) or {}
    event_id = payload.get("id", "")
    if event_id in _processed_events:
        return jsonify({"status": "duplicate"})
    _processed_events.add(event_id)
    return jsonify({"status": "ok"})
