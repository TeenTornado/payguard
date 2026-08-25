"""Human-readable finding titles.

A title is derived from the strongest static rule that fired, falling back to a
defect-class phrasing when a finding is LLM-only. Pure function of data already on the
finding (rule ids + defect class), so it can be computed at serialization time without a
schema change.
"""
from __future__ import annotations

from payguard.shared.enums import DefectClass

# rule id → title
_RULE_TITLES: dict[str, str] = {
    "DP-R1": "Payment captured without a duplicate-charge guard",
    "DP-R2": "Charge retried in a loop without idempotency",
    "DP-R3": "Webhook fulfills the order without an idempotency guard",
    "DP-R4": "Order fulfilled before payment is confirmed captured",
    "WI-R1": "Webhook handler skips signature verification",
    "WI-R2": "Webhook signature compared with a non-constant-time check",
    "WI-R3": "Webhook trusts amount/status from the payload, not the API",
    "WI-R4": "Webhook processed without verifying the event is unique",
    "AC-R1": "Order amount sent in rupees, not paise",
    "AC-R2": "Amount computed with floating-point rupees",
    "AC-R3": "Order amount taken from client input, not the server",
    "AC-R4": "Currency assumed INR without checking the order",
    "SC-R1": "Suspicious payment-handling pattern",
}

# defect class → fallback title (LLM-only findings, or unknown rule)
_CLASS_TITLES: dict[str, str] = {
    DefectClass.DUPLICATE_PAYMENT.value: "Possible duplicate payment / double fulfillment",
    DefectClass.WEBHOOK_INTEGRITY.value: "Possible webhook integrity weakness",
    DefectClass.AMOUNT_CURRENCY.value: "Possible amount / currency handling error",
    DefectClass.SUSPICIOUS_CONTENT.value: "Suspicious payment-handling content",
}


def title_for(rule_ids: list[str] | None, defect_class: str) -> str:
    """Best human title for a finding. Prefers the specific rule, then the class."""
    for rid in rule_ids or []:
        if rid in _RULE_TITLES:
            return _RULE_TITLES[rid]
    return _CLASS_TITLES.get(defect_class, defect_class.replace("_", " ").title())
