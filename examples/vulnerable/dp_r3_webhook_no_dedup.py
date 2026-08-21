"""
DP-R3 / DP-2 vulnerable: webhook handler fulfills without idempotency guard.
Also WI-R1 vulnerable (no signature check) — demonstrates the hardest case.
"""
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():
    # No signature verification
    # No event-id dedup check
    payload = request.json
    event = payload.get("event")
    if event == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        payment_id = payment["id"]
        amount = payment["amount"]
        # Fulfill immediately — no guard against duplicate delivery
        fulfill_order(payment_id, amount)
    return jsonify({"status": "ok"}), 200


def fulfill_order(payment_id: str, amount: int):
    # Side effect: ship order, grant access, etc.
    print(f"Fulfilling order for payment {payment_id}, amount {amount}")
