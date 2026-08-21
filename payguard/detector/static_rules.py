"""
Static detection rules for payment defects.
Each rule: ID, defect_class, confidence_prior, evidence extractor.
Every rule has unit tests on examples/.

Rule IDs:
  DP-R1: order creation without dedup
  DP-R2: retry/loop wrapping order/capture/refund
  DP-R3: webhook handler with fulfillment but no idempotency guard
  DP-R4: refund handler lacks existing-refund check
  WI-R1: no signature verification in webhook handler
  WI-R2: HMAC over parsed (not raw) body
  WI-R3: no event-id/payment-id persistence before side effect
  WI-R4: payload amount/status trusted without order fetch
  AC-R1: amount without paise conversion / double conversion
  AC-R2: float arithmetic on money variables
  AC-R3: client-supplied amount flows to order creation
  AC-R4: currency literal mismatch
  SC-R1: suspicious instruction text (prompt injection advisory)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from payguard.detector.discovery import PaymentUnit, UnitKind
from payguard.shared.enums import DefectClass, Severity


@dataclass
class RuleHit:
    rule_id: str
    defect_class: DefectClass
    severity: Severity
    confidence: float
    evidence_lines: list[str]
    explanation: str
    scenario_ids: list[str] = field(default_factory=list)


# ─── Helpers ──────────────────────────────────────────────────────────────────

_PY_COMMENT = re.compile(r"#.*$", re.M)
_JS_LINE_COMMENT = re.compile(r"//.*$", re.M)
_JS_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_DOCSTRING = re.compile(r'""".*?"""|\'\'\'.*?\'\'\'', re.S)


def _strip_comments(source: str) -> str:
    """Remove Python/JS comments and docstrings so patterns only match code."""
    s = _DOCSTRING.sub("", source)
    s = _PY_COMMENT.sub("", s)
    s = _JS_LINE_COMMENT.sub("", s)
    s = _JS_BLOCK_COMMENT.sub("", s)
    return s


def _lines_matching(source: str, pattern: re.Pattern) -> list[str]:
    return [ln.strip() for ln in source.splitlines() if pattern.search(ln)]


def _has_pattern(source: str, pattern: re.Pattern, strip_comments: bool = False) -> bool:
    src = _strip_comments(source) if strip_comments else source
    return bool(pattern.search(src))


# ─── DUPLICATE_PAYMENT rules ─────────────────────────────────────────────────

# DP-R1: order created without dedup lookup
_DP_R1_CREATE = re.compile(r"\b(orders?\.(create|place)|/v1/orders)\b", re.I)
_DP_R1_DEDUP = re.compile(
    r"\b(find|get|fetch|lookup|exists|check|query|select|filter)\b.*"
    r"(order|receipt|idempoten|cart|transaction)",
    re.I,
)
_DP_R1_UNIQUE_CONSTRAINT = re.compile(
    r"\b(unique|UNIQUE|UniqueConstraint|unique_together)\b", re.I
)


def check_dp_r1(unit: PaymentUnit) -> RuleHit | None:
    """Order creation without a preceding dedup lookup in the same unit."""
    src = unit.source
    if not _has_pattern(src, _DP_R1_CREATE, strip_comments=True):
        return None
    if _has_pattern(src, _DP_R1_DEDUP, strip_comments=True):
        return None
    if _has_pattern(src, _DP_R1_UNIQUE_CONSTRAINT, strip_comments=True):
        return None
    evidence = _lines_matching(src, _DP_R1_CREATE)
    return RuleHit(
        rule_id="DP-R1",
        defect_class=DefectClass.DUPLICATE_PAYMENT,
        severity=Severity.HIGH,
        confidence=0.55,
        evidence_lines=evidence[:5],
        explanation=(
            "Order creation detected without a preceding deduplication lookup. "
            "If the client retries (network error, browser back-button), a second "
            "order is created for the same cart, leading to duplicate charges."
        ),
        scenario_ids=["DP-1"],
    )


# DP-R2: retry loop wrapping order/capture/refund
_DP_R2_LOOP = re.compile(r"\b(for|while|retry|backoff|attempts?)\b", re.I)
_DP_R2_TARGET = re.compile(r"\b(orders?\.(create|place)|payments?\.(capture)|refund)\b", re.I)


def check_dp_r2(unit: PaymentUnit) -> RuleHit | None:
    """Retry loop wraps order/capture/refund without idempotency key."""
    src = unit.source
    if not (_has_pattern(src, _DP_R2_LOOP, strip_comments=True) and
            _has_pattern(src, _DP_R2_TARGET, strip_comments=True)):
        return None
    _idempotency = re.compile(r"\b(idempoten|unique_key|X-Payout-Idempotency)\b", re.I)
    if _has_pattern(src, _idempotency, strip_comments=True):
        return None
    evidence = _lines_matching(src, _DP_R2_TARGET)
    return RuleHit(
        rule_id="DP-R2",
        defect_class=DefectClass.DUPLICATE_PAYMENT,
        severity=Severity.HIGH,
        confidence=0.60,
        evidence_lines=evidence[:5],
        explanation=(
            "A retry loop wraps an order/capture/refund call without an idempotency "
            "guard. Each retry iteration may create a duplicate order or trigger a "
            "duplicate capture/refund."
        ),
        scenario_ids=["DP-1", "DP-3"],
    )


# DP-R3: webhook handler invokes fulfillment with no idempotency guard
_DP_R3_FULFILLMENT = re.compile(
    r"\b(fulfill\w*|credit\w*|ship\w*|dispatch|"
    r"grant_access|activate_subscription|deliver\w*|"
    r"send_order|confirm_order|process_order|complete_order)\b",
    re.I,
)
_DP_R3_DEDUP = re.compile(
    r"\b(already.*processed|already.*handled|already.*seen|"
    r"mark.*processed|set.*processed|event_log|processed_events|"
    r"ProcessedEvent|EventLog|idempoten|"
    r"(find|get|fetch|lookup|exists|filter|query)\s*\(.*event_id|"
    r"(find|get|fetch|lookup|exists|filter|query)\s*\(.*payment_id)\b",
    re.I,
)


def check_dp_r3(unit: PaymentUnit) -> RuleHit | None:
    """Webhook handler fulfills without idempotency guard."""
    if unit.kind != UnitKind.WEBHOOK:
        return None
    src = unit.source
    if not _has_pattern(src, _DP_R3_FULFILLMENT, strip_comments=True):
        return None
    if _has_pattern(src, _DP_R3_DEDUP, strip_comments=True):
        return None
    evidence = _lines_matching(src, _DP_R3_FULFILLMENT)
    return RuleHit(
        rule_id="DP-R3",
        defect_class=DefectClass.DUPLICATE_PAYMENT,
        severity=Severity.CRITICAL,
        confidence=0.70,
        evidence_lines=evidence[:5],
        explanation=(
            "Webhook handler performs a fulfillment/credit action without first "
            "checking whether this event has already been processed. Razorpay "
            "delivers webhooks at-least-once (retries for 24h), so any retry "
            "will trigger duplicate fulfillment."
        ),
        scenario_ids=["DP-2"],
    )


# DP-R4: refund handler lacks existing-refund check
_DP_R4_REFUND = re.compile(r"\b(refund|rfnd)\b.*\b(create|post|issue|process)\b", re.I)
_DP_R4_CHECK = re.compile(
    r"\b(already.*refund|refund.*exist|find.*refund|get.*refund|check.*refund|"
    r"refund.*processed|rfnd_)\b",
    re.I,
)


def check_dp_r4(unit: PaymentUnit) -> RuleHit | None:
    """Refund handler lacks existing-refund check."""
    src = unit.source
    if not _has_pattern(src, _DP_R4_REFUND):
        return None
    if _has_pattern(src, _DP_R4_CHECK):
        return None
    evidence = _lines_matching(src, _DP_R4_REFUND)
    return RuleHit(
        rule_id="DP-R4",
        defect_class=DefectClass.DUPLICATE_PAYMENT,
        severity=Severity.HIGH,
        confidence=0.55,
        evidence_lines=evidence[:5],
        explanation=(
            "Refund handler issues a refund without checking whether one has already "
            "been processed for this payment. A duplicate trigger (retry, double-click, "
            "replay) will cause a second refund."
        ),
        scenario_ids=["DP-3"],
    )


# ─── WEBHOOK_INTEGRITY rules ──────────────────────────────────────────────────

# WI-R1: no signature verification
_WI_R1_VERIFY = re.compile(
    r"\b(verify_webhook_signature|validateWebhookSignature|"
    r"hmac.*sha256|createHmac|compute.*signature|verify.*signature)\b",
    re.I,
)
_WI_R1_HEADER = re.compile(r"X-Razorpay-Signature", re.I)


def check_wi_r1(unit: PaymentUnit) -> RuleHit | None:
    """Webhook route with no signature verification."""
    if unit.kind != UnitKind.WEBHOOK:
        return None
    src = unit.source
    if _has_pattern(src, _WI_R1_VERIFY):
        return None
    return RuleHit(
        rule_id="WI-R1",
        defect_class=DefectClass.WEBHOOK_INTEGRITY,
        severity=Severity.CRITICAL,
        confidence=0.80,
        evidence_lines=[],
        explanation=(
            "Webhook handler does not verify the X-Razorpay-Signature header. "
            "Any external party can POST a forged payment.captured event and "
            "trigger fulfillment without making a real payment."
        ),
        scenario_ids=["WI-1"],
    )


# WI-R2: HMAC over parsed/re-serialized body
_WI_R2_PARSE = re.compile(
    r"(JSON\.parse|json\.loads|JSON\.stringify|json\.dumps).*"
    r"(hmac|signature|verify)",
    re.I | re.S,
)
_WI_R2_PARSED_BODY = re.compile(
    r"\b(body|payload|data)\s*=\s*(JSON\.parse|json\.loads|request\.json\(\)|"
    r"await req\.json\(\))",
    re.I,
)
_WI_R2_HMAC_OF_VAR = re.compile(
    r"(hmac|signature|createHmac)\s*[\(,]\s*(body|payload|data|parsed)\b",
    re.I,
)


def check_wi_r2(unit: PaymentUnit) -> RuleHit | None:
    """HMAC computed over parsed (re-serialized) body, not raw bytes."""
    if unit.kind != UnitKind.WEBHOOK:
        return None
    src = unit.source
    # Need both: a parse of body AND HMAC of the parsed result
    if not (_has_pattern(src, _WI_R2_PARSED_BODY) and _has_pattern(src, _WI_R2_HMAC_OF_VAR)):
        return None
    evidence = _lines_matching(src, _WI_R2_PARSED_BODY) + _lines_matching(src, _WI_R2_HMAC_OF_VAR)
    return RuleHit(
        rule_id="WI-R2",
        defect_class=DefectClass.WEBHOOK_INTEGRITY,
        severity=Severity.HIGH,
        confidence=0.65,
        evidence_lines=evidence[:5],
        explanation=(
            "HMAC appears to be computed over a parsed/re-serialized body object, "
            "not the raw bytes. JSON re-serialization changes whitespace and key "
            "order, causing legitimate Razorpay webhooks to fail signature verification."
        ),
        scenario_ids=["WI-2"],
    )


# WI-R3: no event-id/payment-id dedup store before side effect
def check_wi_r3(unit: PaymentUnit) -> RuleHit | None:
    """No persistent dedup store keyed by event-id / payment-id."""
    if unit.kind != UnitKind.WEBHOOK:
        return None
    src = unit.source
    if not _has_pattern(src, _DP_R3_FULFILLMENT):
        return None
    # Check for event_id / payment_id based persistence
    _event_id_store = re.compile(
        r"\b(event_id|X-Razorpay-Event-Id|payment_id|pay_|"
        r"processed_events|event_log|idempoten)\b",
        re.I,
    )
    if _has_pattern(src, _event_id_store):
        return None
    return RuleHit(
        rule_id="WI-R3",
        defect_class=DefectClass.WEBHOOK_INTEGRITY,
        severity=Severity.HIGH,
        confidence=0.65,
        evidence_lines=[],
        explanation=(
            "Webhook handler has no persistence keyed by X-Razorpay-Event-Id or "
            "payment_id before executing the side effect. Razorpay retries webhooks "
            "for up to 24h at-least-once; any retry causes duplicate side effects."
        ),
        scenario_ids=["WI-3"],
    )


# WI-R4: payload amount/status trusted without fetching the order
_WI_R4_PAYLOAD_AMOUNT = re.compile(
    r"payload.*amount|event.*amount|data.*amount|body.*amount", re.I
)
_WI_R4_ORDER_FETCH = re.compile(
    r"\b(orders?\.fetch|payments?\.fetch|/v1/orders?/|/v1/payments?/)\b", re.I
)


def check_wi_r4(unit: PaymentUnit) -> RuleHit | None:
    """Fulfillment uses payload amount/status without cross-checking the order."""
    if unit.kind != UnitKind.WEBHOOK:
        return None
    src = unit.source
    if not _has_pattern(src, _WI_R4_PAYLOAD_AMOUNT):
        return None
    if _has_pattern(src, _WI_R4_ORDER_FETCH):
        return None
    evidence = _lines_matching(src, _WI_R4_PAYLOAD_AMOUNT)
    return RuleHit(
        rule_id="WI-R4",
        defect_class=DefectClass.WEBHOOK_INTEGRITY,
        severity=Severity.MEDIUM,
        confidence=0.50,
        evidence_lines=evidence[:3],
        explanation=(
            "Fulfillment uses the amount/status from the webhook payload without "
            "cross-checking against the server-side order. If WI-1 holds, an attacker "
            "can manipulate the amount; even without WI-1, Razorpay docs recommend "
            "fetching the payment/order to confirm status."
        ),
        scenario_ids=["WI-4"],
    )


# ─── AMOUNT_CURRENCY rules ────────────────────────────────────────────────────

# AC-R1: amount without paise conversion / double conversion
_AC_R1_RUPEE_VAR = re.compile(
    r"\b(amount_inr|rupees?|inr_amount|price_inr|cost_inr|value_inr)\b", re.I
)
_AC_R1_CREATE = re.compile(r"\b(orders?\.create|/v1/orders)\b", re.I)
_AC_R1_PAISE_CONV = re.compile(r"\*\s*100\b|\bpaise\b|\bto_paise\b|\bint\s*\(\s*.*\*\s*100")
_AC_R1_DOUBLE_CONV = re.compile(r"\*\s*100\s*\*\s*100|\*100\s*\*100")


def check_ac_r1(unit: PaymentUnit) -> RuleHit | None:
    """Amount in rupees passed to order creation (missing *100) or *100 applied twice."""
    src = unit.source
    if not _has_pattern(src, _AC_R1_CREATE, strip_comments=True):
        return None

    if _has_pattern(src, _AC_R1_DOUBLE_CONV, strip_comments=True):
        evidence = _lines_matching(src, _AC_R1_DOUBLE_CONV)
        return RuleHit(
            rule_id="AC-R1",
            defect_class=DefectClass.AMOUNT_CURRENCY,
            severity=Severity.CRITICAL,
            confidence=0.85,
            evidence_lines=evidence[:3],
            explanation=(
                "Amount multiplied by 100 twice (*100*100). Razorpay expects paise "
                "(integer); applying the ×100 conversion twice inflates the amount "
                "by 100×."
            ),
            scenario_ids=["AC-1"],
        )

    if _has_pattern(src, _AC_R1_RUPEE_VAR, strip_comments=True) and not _has_pattern(src, _AC_R1_PAISE_CONV, strip_comments=True):
        evidence = _lines_matching(src, _AC_R1_RUPEE_VAR)
        return RuleHit(
            rule_id="AC-R1",
            defect_class=DefectClass.AMOUNT_CURRENCY,
            severity=Severity.CRITICAL,
            confidence=0.75,
            evidence_lines=evidence[:3],
            explanation=(
                "Variable named for rupees (e.g. amount_inr) is passed to order "
                "creation without a ×100 paise conversion. Razorpay expects integers "
                "in paise; ₹1,500 must be sent as 150000."
            ),
            scenario_ids=["AC-1"],
        )

    return None


# AC-R2: float arithmetic on money variables
_AC_R2_FLOAT_OP = re.compile(
    r"(\d+\.\d+\s*[+\-*/]|\s*[+\-*/]\s*\d+\.\d+)", re.I
)
_AC_R2_MONEY_VAR = re.compile(
    r"\b(amount|price|total|cost|value|fee|tax|gst)\b", re.I
)
_AC_R2_DECIMAL = re.compile(r"\b(Decimal|decimal\.Decimal|toFixed\(|Math\.round)\b")


def check_ac_r2(unit: PaymentUnit) -> RuleHit | None:
    """Float arithmetic on money-named variables."""
    src = unit.source
    if not (_has_pattern(src, _AC_R2_FLOAT_OP) and _has_pattern(src, _AC_R2_MONEY_VAR)):
        return None
    if _has_pattern(src, _AC_R2_DECIMAL):
        return None
    evidence = _lines_matching(src, _AC_R2_FLOAT_OP)
    # Filter to lines that also mention money variables
    evidence = [ln for ln in evidence if _AC_R2_MONEY_VAR.search(ln)]
    if not evidence:
        return None
    return RuleHit(
        rule_id="AC-R2",
        defect_class=DefectClass.AMOUNT_CURRENCY,
        severity=Severity.HIGH,
        confidence=0.60,
        evidence_lines=evidence[:3],
        explanation=(
            "Float arithmetic on a money-named variable (e.g. amount * 1.18 for GST). "
            "Floating-point representation errors (0.1 + 0.2 ≠ 0.3) produce non-integer "
            "paise amounts that Razorpay rejects. Use integer arithmetic or Decimal."
        ),
        scenario_ids=["AC-2"],
    )


# AC-R3: client-supplied amount flows to order creation
_AC_R3_CLIENT_INPUT = re.compile(
    r"(req\.body\.(amount|price|total)|"
    r"request\.json\(\)\[.amount.\]|"
    r"request\.json\[.amount.\]|"
    r"request\.form\.get\(.amount.\)|"
    r"params\[.amount.\]|query\[.amount.\]|"
    r"body\[.amount.\]|"
    r"req\.body\[.amount.\]|"
    r"req\.query\.(amount|price|total))",
    re.I,
)
_AC_R3_SERVER_COMPUTE = re.compile(
    r"\b(compute_total|calculate_amount|get_order_amount|db\.(get|find)|"
    r"Product\.(get|find)|Cart\.(get|find)|ORDER_AMOUNT)\b",
    re.I,
)


def check_ac_r3(unit: PaymentUnit) -> RuleHit | None:
    """Amount read from client request body without server-side recomputation."""
    src = unit.source
    if not _has_pattern(src, _AC_R3_CLIENT_INPUT, strip_comments=True):
        return None
    if _has_pattern(src, _AC_R3_SERVER_COMPUTE, strip_comments=True):
        return None
    evidence = _lines_matching(src, _AC_R3_CLIENT_INPUT)
    return RuleHit(
        rule_id="AC-R3",
        defect_class=DefectClass.AMOUNT_CURRENCY,
        severity=Severity.CRITICAL,
        confidence=0.75,
        evidence_lines=evidence[:3],
        explanation=(
            "Amount is read from the client request body and passed directly to "
            "order creation without server-side recomputation from product/cart data. "
            "A client can tamper the amount to ₹1 and checkout for free."
        ),
        scenario_ids=["AC-3"],
    )


# AC-R4: hardcoded/mismatched currency
_AC_R4_CURRENCY = re.compile(r"""['"]currency['"]\s*:\s*['"](\w+)['"]""", re.I)
_SUPPORTED_CURRENCIES = {"INR", "USD", "EUR", "GBP", "SGD", "AED", "MYR"}


def check_ac_r4(unit: PaymentUnit) -> RuleHit | None:
    """Currency literal that looks incorrect."""
    src = unit.source
    matches = _AC_R4_CURRENCY.findall(src)
    bad = [m for m in matches if m.upper() not in _SUPPORTED_CURRENCIES]
    if not bad:
        return None
    return RuleHit(
        rule_id="AC-R4",
        defect_class=DefectClass.AMOUNT_CURRENCY,
        severity=Severity.LOW,
        confidence=0.40,
        evidence_lines=[f"currency: '{m}'" for m in bad[:3]],
        explanation=(
            f"Unrecognized currency code(s): {bad}. Razorpay supports a limited "
            "currency list; an invalid code causes order creation to fail."
        ),
        scenario_ids=[],
    )


# ─── SUSPICIOUS_CONTENT rule ─────────────────────────────────────────────────

_SC_R1_INJECTION = re.compile(
    r"(ignore\s+(previous|prior|above|all)\s+instructions?|"
    r"disregard\s+(your|the)\s+instructions?|"
    r"you\s+are\s+now\s+a|"
    r"send\s+(the|all|this)\s+(data|info|credentials?|keys?|secrets?)\s+to\b)",
    re.I,
)


def check_sc_r1(unit: PaymentUnit) -> RuleHit | None:
    """Prompt-injection advisory in comments or strings."""
    src = unit.source
    if not _has_pattern(src, _SC_R1_INJECTION):
        return None
    evidence = _lines_matching(src, _SC_R1_INJECTION)
    return RuleHit(
        rule_id="SC-R1",
        defect_class=DefectClass.SUSPICIOUS_CONTENT,
        severity=Severity.MEDIUM,
        confidence=0.90,
        evidence_lines=evidence[:3],
        explanation=(
            "Code contains text resembling a prompt-injection instruction. "
            "This is an advisory finding; it does not affect PayGuard's analysis "
            "behavior. Review the source for intentional or accidental injection text."
        ),
        scenario_ids=[],
    )


# ─── Rule registry ───────────────────────────────────────────────────────────

ALL_RULES = [
    check_dp_r1,
    check_dp_r2,
    check_dp_r3,
    check_dp_r4,
    check_wi_r1,
    check_wi_r2,
    check_wi_r3,
    check_wi_r4,
    check_ac_r1,
    check_ac_r2,
    check_ac_r3,
    check_ac_r4,
    check_sc_r1,
]


def run_static_rules(unit: PaymentUnit) -> list[RuleHit]:
    """Run all rules against a PaymentUnit. Returns all hits."""
    hits = []
    for rule_fn in ALL_RULES:
        try:
            hit = rule_fn(unit)
            if hit is not None:
                hits.append(hit)
        except Exception:
            pass  # rule bugs must not crash the pipeline
    return hits
