"""WI-R1 vulnerable: webhook with no signature verification."""
from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/payment/webhook", methods=["POST"])
def payment_webhook():
    # Missing: no X-Razorpay-Signature verification
    data = request.json
    if data.get("event") == "payment.captured":
        fulfill(data["payload"]["payment"]["entity"])
    return jsonify({"status": "ok"})


def fulfill(payment):
    print(f"Fulfilling payment {payment['id']}")
