import os
import razorpay
from flask import Flask, abort, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

opts = {"auth": (KEY_ID, KEY_SECRET)}
if BASE_URL:
    opts["base_url"] = BASE_URL
client = razorpay.Client(**opts)

PRODUCT_PRICE_PAISE = 150000  # ₹1500 in paise
_orders: dict = {}
_processed_events: set = set()


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    cart_id = data.get("cart_id", "default")
    if cart_id in _orders:
        return jsonify({"order_id": _orders[cart_id]["id"]})
    # Safe: amount is already in paise by convention
    amount_paise = PRODUCT_PRICE_PAISE
    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    _orders[cart_id] = order
    return jsonify({"order_id": order["id"]})


@app.route("/webhook/razorpay", methods=["POST"])
def webhook():
    raw_body = request.get_data(as_text=False)
    sig = request.headers.get("X-Razorpay-Signature", "")
    event_id = request.headers.get("X-Razorpay-Event-Id", "")
    try:
        client.utility.verify_webhook_signature(raw_body.decode(), sig, WEBHOOK_SECRET)
    except Exception:
        abort(400, "Invalid signature")
    if event_id in _processed_events:
        return jsonify({"status": "already_processed"}), 200
    _processed_events.add(event_id)
    payload = request.json
    if payload.get("event") == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        _fulfill(payment["id"], payment["amount"])
    return jsonify({"status": "ok"}), 200


def _fulfill(payment_id: str, amount: int) -> None:
    app.logger.info(f"Fulfilling {payment_id}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
