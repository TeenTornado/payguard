"""Safe: webhook with full signature verification and event-id dedup."""
import razorpay
from flask import Flask, request, jsonify, abort

app = Flask(__name__)
client = razorpay.Client(auth=("rzp_test_key", "secret"))
WEBHOOK_SECRET = "webhook_secret_here"


@app.route("/webhook/razorpay", methods=["POST"])
def razorpay_webhook():
    raw_body = request.get_data(as_text=False)
    signature = request.headers.get("X-Razorpay-Signature", "")
    event_id = request.headers.get("X-Razorpay-Event-Id", "")

    # Safe: signature verified over raw bytes
    try:
        client.utility.verify_webhook_signature(raw_body.decode(), signature, WEBHOOK_SECRET)
    except Exception:
        abort(400, "Invalid signature")

    # Safe: event-id dedup check
    if ProcessedEvent.exists(event_id):
        return jsonify({"status": "already_processed"}), 200

    payload = request.json
    event = payload.get("event")
    if event == "payment.captured":
        payment = payload["payload"]["payment"]["entity"]
        ProcessedEvent.create(event_id)
        fulfill_order(payment["id"], payment["amount"])

    return jsonify({"status": "ok"}), 200


def fulfill_order(payment_id: str, amount: int):
    print(f"Fulfilling {payment_id}")


class ProcessedEvent:
    @staticmethod
    def exists(event_id: str) -> bool:
        return False  # stub

    @staticmethod
    def create(event_id: str) -> None:
        pass  # stub
