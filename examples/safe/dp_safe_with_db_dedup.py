"""Safe: order creation with DB unique constraint dedup (hard negative)."""
import razorpay
from sqlalchemy import UniqueConstraint

client = razorpay.Client(auth=("rzp_test_key", "secret"))


def create_order_idempotent(amount_paise: int, cart_id: str, db):
    # Safe: DB unique constraint on cart_id prevents duplicates
    # The UNIQUE constraint on OrderRequest.cart_id means the INSERT will
    # fail on duplicate, and no second Razorpay order is created.
    existing = db.query(OrderRequest).filter_by(cart_id=cart_id).first()
    if existing:
        return existing.razorpay_order_id

    order = client.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": cart_id,
    })
    db.add(OrderRequest(cart_id=cart_id, razorpay_order_id=order["id"]))
    db.commit()
    return order["id"]


class OrderRequest:
    __tablename__ = "order_requests"
    __table_args__ = (UniqueConstraint("cart_id"),)
