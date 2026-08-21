"""DP-R2 vulnerable: retry loop wraps order creation without idempotency."""
import razorpay

client = razorpay.Client(auth=("rzp_test_key", "secret"))


def create_order_with_retry(amount_paise: int, receipt: str, max_attempts: int = 3):
    for attempt in range(max_attempts):
        try:
            order = client.order.create({
                "amount": amount_paise,
                "currency": "INR",
                "receipt": receipt,
            })
            return order
        except Exception:
            if attempt == max_attempts - 1:
                raise
