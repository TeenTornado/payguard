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

# Simulated DB: stores prices already in paise despite column name
_PRODUCT_CATALOG = {
    "prod_001": {"name": "Widget", "price_inr": 9900},  # actually paise
    "prod_002": {"name": "Gadget", "price_inr": 49900},  # actually paise
}


def get_product_price(product_id: str) -> int:
    """Returns the product price from catalog (stored as paise)."""
    return _PRODUCT_CATALOG.get(product_id, {}).get("price_inr", 0)


def create_razorpay_order(product_id: str, cart_id: str) -> dict:
    price = get_product_price(product_id)
    # Already paise; multiplying by 100 inflates 100x
    amount_paise = price * 100
    return client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    product_id = data.get("product_id", "prod_001")

    if cart_id in _orders:
        return jsonify({"order_id": _orders[cart_id]["id"]})

    order = create_razorpay_order(product_id, cart_id)
    _orders[cart_id] = order
    return jsonify({"order_id": order["id"]})


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
