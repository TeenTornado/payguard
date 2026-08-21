# Demo Candidates

Samples where System B (LLM-only) produces findings that System A (static) does not.
These make good "AI found something static missed — but it needs verification" demo moments.

**Sourced from:** System B val-split run 2026-08-21 (OpenRouter → gemini-2.5-flash,
`reports/B_val_20260821T081100Z.json`)

**Do NOT tune prompts or thresholds based on these samples.** They are in the val split.
Val is for observing behaviour, not for optimization. Prompt changes require train-split validation.

---

## WI FP 1 — `gen-flask_hn_decimal-v3`

**Defect claimed:** `WEBHOOK_INTEGRITY` (confidence 0.9)
**Actual label:** SAFE (hard negative — decimal rounding variant)
**Static prediction:** No WI finding (static rules correctly pass)

**Gemini explanation (verbatim, truncated):**
> "The webhook signature verification is performed on `raw_body.decode()` which converts the
> raw bytes to a string using the default encoding. If the raw body contains non-UTF-8 bytes
> or if the encoding does not match what Razorpay used to compute the signature, the HMAC
> comparison will fail or silently succeed with wrong data."

**Why it's a false positive:** The template uses `.decode()` with no encoding argument, which
defaults to UTF-8. Razorpay always sends UTF-8 JSON bodies. The HMAC is computed over the raw
bytes object directly (before decode), not the string. This is a correct implementation.

**Demo use:** "AI raised a subtle encoding concern — let's ask the verifier if this is real."
The verifier (Phase 7) should confirm the HMAC is over raw bytes and close the finding.

---

## WI FP 2 — `gen-flask_hn_paise_named-v1`

**Defect claimed:** `WEBHOOK_INTEGRITY` (confidence inferred from B FP count)
**Actual label:** SAFE (hard negative — amount already in paise)
**Static prediction:** No WI finding

**Note:** Cache did not contain a WI finding for this sample in the stored run (hit may have
been on a different unit or confidence < τ=0.45). Listed because it appears in the 3-FP count
from `B_val_20260821T081100Z.json` (WI: tp=1, fp=3). Needs re-probe with fresh Gemini run to
confirm exact finding text.

**Demo use:** Good candidate to show "LLM confidence distribution" — if confidence is near τ,
it demonstrates why τ calibration matters.

---

## WI FP 3 — `gen-flask_safe-v3`

**Defect claimed:** `WEBHOOK_INTEGRITY` (confidence inferred from B FP count)
**Actual label:** SAFE (fully safe template — HMAC + event-id dedup)
**Static prediction:** No WI finding

**Note:** Same cache caveat as WI FP 2 above. The sample has full signature verification
using `hmac.compare_digest` and event-id dedup via `_processed_events` set. Gemini likely
fires on the in-memory dedup (resets on restart) but that is not a WI defect — it's a DP
concern and not one that applies here since it's the webhook idempotency guard, not the
order creation guard.

**Demo use:** "Static rules know this is safe; LLM sees a pattern it thinks is risky; verifier
resolves the disagreement." A three-way comparison that shows system C's union logic and why
verifier (System D) is needed.

---

## DP FP — `gen-flask_dp2_vuln-v3` (additional candidate)

**Defect claimed:** `DUPLICATE_PAYMENT` FP in System B (the single DP FP from B_val report)
**Note:** This sample is labeled DP-only. System B produced a DP FP here, which means Gemini
also flagged DP on a non-DP sample elsewhere. Cross-check against the full per-sample breakdown
in the report JSON to identify the exact sample. Likely one of the AC-only samples
(`gen-flask_ac1_vuln-v2` or `gen-flask_ac1_vuln-v3`) where Gemini fired DP incorrectly.

---

*Last updated: 2026-08-21. Re-run `make eval-dev-b` after dataset v2 to refresh findings.*
