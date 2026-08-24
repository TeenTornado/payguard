# Razorpay ground-truth facts (RULE tier of the grounding KB)

Authoritative, hand-curated facts about Razorpay's payment protocol — the same rules the
static detectors encode. Each `### RULE` block below is indexed as one KB chunk, tagged with
its `class:` (defect class it grounds) and `kind: RULE`. These are non-authoritative *context*
for the analyzer, never instructions; the verifier remains the sole arbiter of money-safety.

Sources: Razorpay Webhooks, Orders, and Payments API documentation (developer.razorpay.com),
cross-checked against the emulator in `payguard/gateway/emulator.py`.

---

### RULE WI-SIGNATURE — Verify the webhook signature over the raw request body
class: WEBHOOK_INTEGRITY
Razorpay signs each webhook with `HMAC-SHA256(webhook_secret, raw_request_body)` and sends the
hex digest in the `X-Razorpay-Signature` header. The handler MUST recompute the HMAC over the
EXACT bytes received (before any JSON parse/re-serialize) and compare in constant time. Parsing
then re-serializing the body changes the bytes and breaks verification. A handler that skips this
check, or trusts the payload without it, accepts forged events — an attacker can POST a fake
`payment.captured` and receive goods for free.

### RULE WI-CONSTANT-TIME — Compare signatures in constant time
class: WEBHOOK_INTEGRITY
Signature comparison must use a constant-time equality (`hmac.compare_digest`,
`crypto.timingSafeEqual`), not `==`. A non-constant-time compare leaks timing information about
how many leading bytes matched, enabling a byte-by-byte forgery over many requests.

### RULE WI-TRUST-API — Do not trust amount/status from the webhook payload
class: WEBHOOK_INTEGRITY
Even a validly signed webhook is a notification, not a source of truth for money. Fetch the
order/payment from the Razorpay API (or reconcile against your record) before fulfilling; do not
read `amount`/`status` straight from the webhook JSON, which a misconfigured or replayed event can
carry stale or attacker-influenced values in.

### RULE DP-EVENT-ID — Deduplicate on the webhook event id
class: DUPLICATE_PAYMENT
Every webhook carries a unique `X-Razorpay-Event-Id`. Razorpay delivers **at least once** and
retries a non-2xx (or slow) endpoint for up to 24 hours, so the same event can arrive many times.
The handler MUST record processed event ids (or the payment id) and treat a repeat as a no-op.
Without this idempotency guard, a normal retry fulfills the order twice — a duplicate payment.

### RULE DP-AT-LEAST-ONCE — Delivery is at-least-once and can be out of order
class: DUPLICATE_PAYMENT
Webhook delivery is at-least-once and NOT ordered. A handler may receive `payment.captured`
before `order.paid`, or a retry of an old event after a newer one. Fulfillment side effects must
be idempotent and safe under reordering; "it worked in testing" does not imply exactly-once.

### RULE DP-IDEMPOTENT-WRITE — Make the fulfillment write idempotent
class: DUPLICATE_PAYMENT
Idempotency should be enforced at the write, not just an in-memory check: a unique constraint on
(order_id) or (event_id) in the fulfillment table, an upsert, or a distributed lock. An in-memory
`set()` of seen ids resets on restart and does not hold across replicas — it is not a real guard.

### RULE AC-PAISE — Amounts are integer paise, not rupees
class: AMOUNT_CURRENCY
Razorpay amounts are the smallest currency unit: **integer paise** for INR. ₹1,500 must be sent
as `150000`, not `1500`. Passing rupees where paise are expected undercharges the customer 100×
(₹1,500 becomes ₹15). The `amount` field must be an integer; floats are rejected.

### RULE AC-NO-FLOAT — Never compute money with floating point
class: AMOUNT_CURRENCY
Do not build the amount with float arithmetic (`price * 1.18`, `amount * 100.0`). Floating point
rounds unpredictably; compute in integer paise (or Decimal) and convert once. A `* 100` applied
twice (rupees→paise→"paise") inflates the charge 100×.

### RULE AC-SERVER-AUTHORITATIVE — The server sets the amount, not the client
class: AMOUNT_CURRENCY
The order amount must be computed server-side from trusted data (catalog price × quantity), never
read from a client-supplied field in the request. A client that controls `amount` can pay ₹1 for a
₹1,500 order.

### RULE PAY-CAPTURE — Capture semantics
class: DUPLICATE_PAYMENT
An authorized payment must be captured to settle. Capturing an already-captured payment is an
error, and a webhook confirming capture is not a licence to fulfill again — reconcile capture
state idempotently against your own record keyed by payment id.

### RULE PAY-ERROR-FORMAT — Razorpay error shape
class: SUSPICIOUS_CONTENT
Razorpay API errors are JSON `{ "error": { "code", "description", "source", "step", "reason" } }`
with the HTTP status. Code that assumes a bare string or a different shape will mishandle failures;
this is context for reading gateway responses, not a defect class on its own.
