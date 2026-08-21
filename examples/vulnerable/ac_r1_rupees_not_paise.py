"""AC-R1 vulnerable: amount in rupees passed where paise expected."""
import razorpay

client = razorpay.Client(auth=("rzp_test_key", "secret"))


def create_order(amount_inr: float):
    # BUG: Razorpay expects paise (integer). ₹1,500 must be 150000, not 1500.
    order = client.order.create({
        "amount": amount_inr,  # passed in rupees, should be amount_inr * 100
        "currency": "INR",
    })
    return order
