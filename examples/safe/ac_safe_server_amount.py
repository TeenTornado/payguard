"""Safe: amount computed server-side, not from client body."""
import razorpay
from flask import Flask, request, jsonify

app = Flask(__name__)
client = razorpay.Client(auth=("rzp_test_key", "secret"))


@app.route("/create-order", methods=["POST"])
def create_order():
    cart_id = request.json["cart_id"]
    # Safe: amount fetched from DB, not from client
    cart = Cart.get(cart_id)
    amount_paise = cart.total_paise  # server-computed, integer
    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    return jsonify(order)


class Cart:
    @staticmethod
    def get(cart_id: str) -> "Cart":
        return Cart()

    @property
    def total_paise(self) -> int:
        return 150000  # stub: ₹1500
