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

## 2026-08-21 — eval/runner.py (System B/C label inversion)

**Symptom:** Implementation had B=static∪LLM and C=LLM-only, which is the opposite of the brief. Caught in code review before any results were published.

**Root cause:** Brief describes B=LLM-only and C=static∪LLM. When writing the runner we used the intuitive "C is more complex" ordering without re-reading the spec. No test asserted the system→logic mapping.

**Fix:** Swapped B and C logic in `evaluate_system()`. Added `TestSystemNaming` in `tests/unit/test_llm_adapter.py` which asserts B returns UNAVAILABLE without key (confirms no static fallback) and A always has llm_status=OK.

**Test added:** `TestSystemNaming.test_system_a_uses_static_only`, `test_system_b_unavailable_without_key`, `test_system_c_unavailable_without_key`

**Lesson:** Enum-like string literals ("A", "B", "C") need a mapping test that anchors them to behavior before any eval run. Free-tier quota pressure to "run quickly" makes verification shortcuts tempting and dangerous.

---

## 2026-08-21 — payguard/llm/providers.py (Gemini OpenAI-compat empty content)

**Symptom:** System B/C returned PARSE_ERROR on all val samples when using Gemini direct (key `AQ.Ab8...`). Two failure modes observed:
1. `gemini-2.5-flash` → 404 NotFoundError ("model not available to new users")
2. `gemini-3.6-flash` → 200 OK but `choices[0].message.content = ""` (empty string)

**Root cause:** `max_tokens=1024` was hardcoded in `_complete_once`. Gemini's analysis JSON for a multi-function file with explanations easily exceeds 1024 output tokens. The response was silently truncated mid-JSON → empty string after stripping. Additionally, `NotFoundError` originally fell through to `except Exception` in `complete()` and was silently discarded, masking the 404 entirely.

Secondary root cause: The `AQ.Ab8...` credential is not a standard `AIza...` API key — it may be an OAuth access token or refresh token. It authenticates successfully to the Gemini OpenAI-compat endpoint but only for specific models.

**Fix:** (1) `max_tokens` is now a constructor param on `OpenAICompatProvider`, defaulting to 8192. (2) Added explicit `logger.warning` when content is empty with `finish_reason` and `reasoning_tokens` logged for diagnosis. (3) `NotFoundError` and `AuthenticationError` now raise `ProviderError` immediately (non-retriable). (4) Switched model to `gemini-3.6-flash` which works with the `AQ.Ab8...` credential. Verified: returns `{"ok":true}` at `max_tokens=8192`.

**Test added:** `TestOpenAICompatProvider.test_json_mode_fallback_on_bad_request` (pre-existing); root cause tested implicitly through full adapter test suite.

**Lesson:** Always log `finish_reason` and content length on every completion. `max_tokens=1024` is dangerous for structured JSON output where the schema itself is large — set it to 8192 for all analysis calls. Treat empty content as an error, not a valid "no findings" response.

---

## 2026-08-21 — dataset/generator.py (OpenRouter daily quota wall)

**Symptom:** `make eval-dev` System B completed 28 API calls successfully. Next eval run (same day) began hitting 429 errors with "You have exceeded your daily request limit" from OpenRouter. All further B/C runs for the day were blocked.

**Root cause:** OpenRouter free tier (unfunded account) has a hard 50 RPD (requests per day) limit. 28 calls for one System B run + overhead from retries consumed most of the daily budget. On a day with multiple eval iterations, the quota wall is hit within 2–3 runs.

Additional: OpenRouter serves `:free` model variants which can be delisted without notice, making the `google/gemini-2.5-flash` route unreliable for production eval.

**Fix:** (1) OpenRouter demoted to last-resort fallback in `build_analyzer_provider()` and `build_generator_provider()`. Primary analyzer = Gemini direct; primary generator = Groq direct. (2) OpenRouter `max_retries` set to 1 (previously 5) — 429 retries consume RPD quota. (3) `PAYGUARD_FALLBACK_*` env vars control the fallback; only activated when primary key is absent.

**Test added:** None — quota limits are runtime infrastructure, not code. Documented in `docs/evaluation.md` limitations.

**Lesson:** Free-tier LLM routing proxies are attractive for demo convenience but unreliable for repeatable evals. Use provider-direct keys (Gemini, Groq) for all development runs. Document RPD limits in `docs/evaluation.md` and cache everything in `dataset/llm_cache/`.

## 2026-08-21 — detector/static_rules.py (DP-R1, DP-R3, DP-R2, AC-R1, AC-R3)

**Symptom:** 6 of 16 static rule unit tests failed. DP-R1 false-negative on `dp_r1_no_dedup.py`, DP-R3 false-negative on webhook with fulfillment, AC-R1 false-negative on `amount_inr` variable, AC-R3 false-negative on `request.json["amount"]`.

**Root cause 1 (DP-R1):** `_DP_R1_DEDUP` pattern matched the file's own comment text ("No lookup to check if an order with this receipt already exists"). Rules were run against the full source including comments, not just code.

**Root cause 2 (DP-R3):** (a) `_DP_R3_DEDUP` matched `payment_id` as a function parameter name, which looks like an idempotency guard but isn't — it's just the function signature. (b) `_DP_R3_FULFILLMENT` used `\bfulfill\b` which doesn't match `fulfill_order` because `_` is a word character.

**Root cause 3 (AC-R3):** Pattern only covered `request.json()["amount"]` (with parentheses) but the actual code used `request.json["amount"]` (attribute access, no call).

**Fix:** Added `_strip_comments()` function that removes Python/JS comments and docstrings before applying mitigation/dedup pattern checks. Made dedup check more specific (requires `ProcessedEvent`, `event_log`, or `(find|get)\(.*event_id` patterns). Fixed FULFILLMENT pattern to `fulfill\w*`. Added `request.json["amount"]` to AC-R3 client-input pattern.

**Test added:** All 16 static rule unit tests (test_static_rules.py) — they caught all six regressions immediately.

**Lesson:** Static analysis rules are deceptively easy to write and deceptively easy to break on real code. Comment text is indistinguishable from code to a naive regex. Every rule needs unit tests on real examples before trusting the confidence score.

---

## 2026-08-21 — Gemini direct key type / model availability

**Symptom:** After fixing `max_tokens=8192` and switching to Gemini direct, System B
(Gemini direct `gemini-3.6-flash`) produced macro F1=0.3333 on val. The previous OpenRouter
run with `google/gemini-2.5-flash` produced macro F1=0.6863. Probing all Gemini model variants
with the `AQ.Ab8...` key shows only `gemini-3.6-flash` accepts the credential — all others return 404.

**Root cause:** The `AQ.Ab8...` credential is NOT a standard Gemini API key (those start with
`AIza...` from Google AI Studio). The `AQ.Ab8...` prefix indicates an OAuth 2.0 access token
with restricted model access — only `gemini-3.6-flash` is available. This model is weaker for
code analysis than `gemini-2.5-flash`.

Probe results with `AQ.Ab8...` key: gemini-2.5-flash/lite/002/preview → 404;
gemini-2.0-flash/lite → 404; gemini-3.6-flash → 200 OK (only accessible model).

**Impact:** System B F1 drops 0.6863 → 0.3333. System C F1 improves 0.7797 → ~0.9 because
System A's perfect static recall covers B's misses AND gemini-3.6-flash produces fewer WI FPs
than gemini-2.5-flash. The C improvement is a model-change artifact, not a real robustness gain.

**Fix:** Infrastructure correct (Gemini direct primary configured). To access gemini-2.5-flash
directly, a proper `AIza...` API key from Google AI Studio is required:
https://aistudio.google.com/app/apikey

**Test added:** `llm doctor` CLI now surfaces model/finish_reason/tokens on each probe, making
this class of failure immediately visible at setup time.

**Lesson:** Validate credential type before assuming model access. `AQ.Ab8...` ≠ `AIza...`.
Free-tier tokens may expose a different (smaller) model subset than documented.
