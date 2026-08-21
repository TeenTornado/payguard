import os
import razorpay
from flask import Flask, jsonify, request

app = Flask(__name__)
KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_DUMMY")
KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "dummy")
BASE_URL = os.environ.get("RAZORPAY_BASE_URL", "")

opts = {"auth": (KEY_ID, KEY_SECRET)}
if BASE_URL:
    opts["base_url"] = BASE_URL
client = razorpay.Client(**opts)
_fulfilled: list = []


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/create-order", methods=["POST"])
def create_order():
    amount_paise = 150000
    order = client.order.create({"amount": amount_paise, "currency": "INR"})
    return jsonify({"order_id": order["id"]})


@app.route("/webhook/razorpay", methods=["POST"])
def webhook():
    # DEFECT WI-1: no signature check at all
    payload = request.json
    if payload.get("event") == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        _fulfilled.append(payment["id"])
        _fulfill(payment["id"], payment["amount"])
    return jsonify({"status": "ok"}), 200


def _fulfill(payment_id: str, amount: int) -> None:
    app.logger.info(f"Fulfilling {payment_id}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
