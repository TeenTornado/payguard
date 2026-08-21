import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
client = razorpay.Client(auth=(KEY_ID, KEY_SECRET))

# Simulated Redis client (production: redis.Redis(...))
class _FakeRedis:
    def __init__(self):
        self._store: dict = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self._store:
            return None  # NX: only set if not exists
        self._store[key] = value
        return True

    def get(self, key):
        return self._store.get(key)


redis_client = _FakeRedis()


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "cart_001")
    amount_paise = 9900
    redis_key = f"order:{cart_id}"

    cached = redis_client.get(redis_key)
    if cached:
        return jsonify({"order_id": cached, "cached": True})

    order = client.order.create({"amount": amount_paise, "currency": "INR", "receipt": cart_id})
    redis_client.set(redis_key, order["id"], ex=86400, nx=True)
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
