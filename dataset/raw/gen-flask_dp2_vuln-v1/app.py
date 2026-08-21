import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dummy")
BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

opts = {"auth": (KEY_ID, KEY_SECRET)}
if BASE_URL:
    opts["base_url"] = BASE_URL
client = razorpay.Client(**opts)

_orders: dict = {}


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json or {}
    amount_paise = 150000
    order = client.order.create({"amount": amount_paise, "currency": "INR"})
    _orders[order["id"]] = order
    return jsonify({"order_id": order["id"]})


@app.route("/webhook/razorpay", methods=["POST"])
def webhook():
    raw_body = request.get_data(as_text=False)
    sig = request.headers.get("X-Razorpay-Signature", "")
    try:
        client.utility.verify_webhook_signature(
            raw_body.decode(), sig, WEBHOOK_SECRET
        )
    except Exception:
        return jsonify({"error": "bad sig"}), 400

    # DEFECT DP-2: no event-id dedup — Razorpay retries for 24h
    payload = request.json
    if payload.get("event") == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        _fulfill(payment["id"], payment["amount"])

    return jsonify({"status": "ok"}), 200


def _fulfill(payment_id: str, amount: int) -> None:
    app.logger.info(f"Fulfilling {payment_id}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
