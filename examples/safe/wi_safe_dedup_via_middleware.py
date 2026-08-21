"""
Safe: signature verification and dedup done in shared middleware (hard negative).
A static rule that only looks at this handler will miss the middleware guards.
"""
from flask import Flask, request, jsonify
from myapp.middleware import require_razorpay_signature, idempotent_event

app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
@require_razorpay_signature  # middleware verifies X-Razorpay-Signature
@idempotent_event             # middleware deduplicates by X-Razorpay-Event-Id
def webhook():
    payload = request.json
    if payload.get("event") == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        fulfill_order(payment["id"], payment["amount"])
    return jsonify({"status": "ok"}), 200


def fulfill_order(payment_id: str, amount: int):
    print(f"Fulfilling {payment_id}")
