"""DP-R1 vulnerable: order created without dedup check."""
import razorpay

client = razorpay.Client(auth=("rzp_test_key", "secret"))


def create_order(amount_paise: int, receipt: str):
    # No lookup to check if an order with this receipt already exists
    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
    })
    return order
