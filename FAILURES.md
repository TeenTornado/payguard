# FAILURES.md

Real failures only. Append immediately when something breaks. Never reconstruct after the fact.

## Template

```
## YYYY-MM-DD — <component>

**Symptom:** what broke and how it manifested
**Root cause:** why it happened
**Fix:** what change resolved it
**Test added:** test name / file that now catches this regression
**Lesson:** what this reveals about the system design
```

---

<!-- append failures below this line -->

## 2026-08-21 — detector/static_rules.py (DP-R1, DP-R3, DP-R2, AC-R1, AC-R3)

**Symptom:** 6 of 16 static rule unit tests failed. DP-R1 false-negative on `dp_r1_no_dedup.py`, DP-R3 false-negative on webhook with fulfillment, AC-R1 false-negative on `amount_inr` variable, AC-R3 false-negative on `request.json["amount"]`.

**Root cause 1 (DP-R1):** `_DP_R1_DEDUP` pattern matched the file's own comment text ("No lookup to check if an order with this receipt already exists"). Rules were run against the full source including comments, not just code.

**Root cause 2 (DP-R3):** (a) `_DP_R3_DEDUP` matched `payment_id` as a function parameter name, which looks like an idempotency guard but isn't — it's just the function signature. (b) `_DP_R3_FULFILLMENT` used `\bfulfill\b` which doesn't match `fulfill_order` because `_` is a word character.

**Root cause 3 (AC-R3):** Pattern only covered `request.json()["amount"]` (with parentheses) but the actual code used `request.json["amount"]` (attribute access, no call).

**Fix:** Added `_strip_comments()` function that removes Python/JS comments and docstrings before applying mitigation/dedup pattern checks. Made dedup check more specific (requires `ProcessedEvent`, `event_log`, or `(find|get)\(.*event_id` patterns). Fixed FULFILLMENT pattern to `fulfill\w*`. Added `request.json["amount"]` to AC-R3 client-input pattern.

**Test added:** All 16 static rule unit tests (test_static_rules.py) — they caught all six regressions immediately.

**Lesson:** Static analysis rules are deceptively easy to write and deceptively easy to break on real code. Comment text is indistinguishable from code to a naive regex. Every rule needs unit tests on real examples before trusting the confidence score.
