"""AC-R3 vulnerable: client-supplied amount flows to order creation."""
import razorpay
from flask import Flask, request, jsonify

app = Flask(__name__)
client = razorpay.Client(auth=("rzp_test_key", "secret"))


@app.route("/create-order", methods=["POST"])
def create_order():
    # BUG: amount comes from client. Attacker sends amount=1 and pays ₹0.01.
    amount = request.json["amount"]
    order = client.order.create({
        "amount": amount,
        "currency": "INR",
    })
    return jsonify(order)
