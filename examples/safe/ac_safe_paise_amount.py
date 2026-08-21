"""Safe: amount already in paise (hard negative — variable named amount_paise)."""
import razorpay

client = razorpay.Client(auth=("rzp_test_key", "secret"))


def create_order(amount_paise: int, receipt: str):
    """amount_paise is already in the correct unit. No *100 needed."""
    assert isinstance(amount_paise, int), "amount must be integer paise"
    assert amount_paise >= 100, "minimum order is 100 paise"
    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": receipt,
    })
    return order
