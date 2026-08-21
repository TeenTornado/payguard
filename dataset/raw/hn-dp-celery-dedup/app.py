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

# Simulates Celery task: task_id enforces dedup (broker discards duplicate task_ids)
_celery_task_store: dict = {}


def fulfill_order_task(order_id: str, task_id: str = None):
    # Celery: apply_async(task_id=order_id) — broker deduplicates by task_id
    if task_id in _celery_task_store:
        return
    _celery_task_store[task_id] = True


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
    raw = request.get_data()
    sig = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return jsonify({"error": "invalid signature"}), 400

    payload = request.get_json(force=True) or {}
    if payload.get("event") == "payment.captured":
        order_id = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("order_id", "")
        # Celery task_id = order_id ensures only one fulfillment per order
        fulfill_order_task(order_id, task_id=order_id)
        return jsonify({"status": "ok"})
    return jsonify({"status": "ignored"})
