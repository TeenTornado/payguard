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

---

## 2026-08-24 — payguard/api/app.py (SQLAlchemy 2.0 autobegin vs db.begin())

**Symptom:** Every write route that read first — `POST /findings/{id}/remediation/propose`,
`/dismiss`, `/escalate`, `/verify`, remediation approve/reject — returned 500. Direct DB
scripts doing the same inserts worked. Reproduced in isolation:
`InvalidRequestError: A transaction is already begun on this Session.`

**Root cause:** `get_db` yielded a session that did not manage its own transaction, so each
handler wrapped its writes in `async with db.begin()`. But the handler's first read (e.g.
`_get_finding_or_404`) triggers SQLAlchemy 2.0 **autobegin** — a transaction is already open
by the time `db.begin()` runs, and `begin()` on an already-begun session raises. Handlers
that wrote *without* reading first (`create_scan`) were unaffected, which masked the pattern.
An interim "fix" sprinkled `await db.commit()` into each route — correct-ish, but it spread
transaction control across 8 handlers and left one route still using `db.begin()`.

**Fix:** Made `get_db` own the unit of work — commit on clean return, rollback on exception
— and removed all `begin()`/`commit()`/`rollback()` from route handlers. Transaction control
now lives in exactly one place.

**Test added:** `tests/unit/test_transaction_convention.py` (grep-guard: fails if any
`db.begin(`/`db.commit(`/`db.rollback(` reappears in the API module);
`tests/integration/test_transaction_convention.py::test_read_then_write_commits` (guards the
autobegin regression) and `::test_write_that_raises_rolls_back` (asserts no orphan row / no
half-written audit event on failure).

**Lesson:** With SQLAlchemy 2.0, a read is a transaction start. Session transaction lifecycle
belongs in the dependency, never in handlers — otherwise "read then write" is a landmine and
per-route `commit()` calls are a smell that the boundary is in the wrong place.

---

## 2026-08-24 — cross-process chaos flag (API can't toggle the worker)

**Symptom:** Flipping chaos in the API (an in-memory `_settings_override["chaos_enabled"]`)
had no effect on scans. The worker kept calling the LLM; a "chaos" scan still reported
`llm_status=OK`. The toggle looked like it worked (the API echoed it back) but nothing
downstream changed.

**Root cause:** The API, worker, and gateway are **separate OS processes**. An in-memory flag
in the API process is invisible to the others. An interim fix used a boolean sentinel file
(`/tmp/.payguard_chaos`, touched/unlinked) which worked for LLM chaos but couldn't express
the gateway-failure fault the demo's API-failure beat needs.

**Fix:** Introduced `payguard/shared/chaos.py` — a JSON sentinel `{"llm": bool, "gateway":
bool}` read on demand by all three processes. The worker honors `llm` (skip analysis →
`llm_status=FAILED`); the gateway honors `gateway` (deterministic 503 on `/v1/*`); the
verifier's bounded retries turn that 503 into a terminal ERROR with no MEASURED amount.

**Test added:** `tests/unit/test_chaos_sentinel.py` (round-trip, partial update, corrupt-file
fail-safe); `tests/integration/test_money_safety_chaos.py` (gateway chaos → DP-2 ERROR after
bounded retries, no MEASURED exposure; VERIFIED promotes MEASURED; a smuggled measured amount
on a non-VERIFIED outcome is scrubbed).

**Lesson:** Shared state between processes needs a shared medium — memory in one process is
not it. The sentinel is a single global switch for the host (no per-user/tenant scope); that
limitation is documented in `docs/failure-modes.md` so it isn't mistaken for production-grade
config.

---

## 2026-08-24 — verifier shipped BLOCKED (targets were static code, not runnable apps)

**Symptom:** Clicking Verify on any finding ended `BLOCKED / TARGET_UNAVAILABLE`. The
verifier had a sandbox code path but nothing ever reached VERIFIED — no finding ever got a
MEASURED amount in the browser.

**Root cause:** `examples/vulnerable/` (and the rest of `examples/`) are **static code the
detector reads** — `.py`/`.js` snippets, not booting services. The verifier needs a **running
app** to drive: create an order, deliver a webhook, probe the side-effect count. There was no
runnable target, so DP-2 had nothing to hit and correctly fell through to BLOCKED. The two
concepts had been conflated: "code we analyze" ≠ "app we execute".

**Fix:** Split them. Added `examples/targets/dup-fulfillment-node/` (a real Express app with a
`payguard.yml` manifest: runtime, start, health, webhook + state-probe endpoints, env_map) and
a `-safe` control. Built `payguard/sandbox/` to boot a target (docker when the daemon is up,
subprocess otherwise) and route its Razorpay calls to the EMULATE gateway. The verifier now
boots the target, delivers the same signed event twice, and measures fulfilled_count 0→2 →
VERIFIED with MEASURED ₹1,500.

**Test added:** `tests/integration/test_dp2_sandbox.py` — VERIFIED+measured on the vulnerable
target, NOT_REPRODUCED on the safe control, ERROR (no MEASURED) under gateway chaos.

**Lesson:** A verifier's inputs are *runnable artifacts*, not source. If the demo corpus is
static snippets, the verifier can only ever be BLOCKED — ship at least one bootable target per
scenario, declared by a manifest, from day one.

---

## 2026-08-24 — audit ts + finding file/lines rendered "—" (stale field names in the web layer)

**Symptom:** The Audit log's timestamp column and the Findings table's File and Exposure
columns all showed "—", even though the data was in the DB and in the API JSON.

**Root cause:** The web layer read field names the API doesn't emit. AuditLogTable read
`ev.timestamp` (API sends `ts`); FindingsTable read `file_path` / `line_number` /
`exposure_kind` / `exposure_paise` (API sends `file` / `start_line` / `exposure_measured_paise`
/ `exposure_estimated_paise`). The values were never dropped server-side — the mismatch was at
the JSON→UI mapping boundary, and TypeScript didn't catch it because the response was read as
loosely-typed data.

**Fix:** Render `ev.ts`; map API finding fields to the UI shape inside `listFindings` (one
place); add finding `title` via `title_for()`; correct the `AuditEvent`/`VerificationResult`
TS types so future drift is a compile error.

**Test added:** None (pure serialization/mapping). Guarded going forward by the corrected TS
types + `tsc --noEmit` in the web build.

**Lesson:** When the API and UI are separate codebases, field-name drift renders as blank cells,
not errors. Keep one mapping function per resource and type the raw response so `tsc` catches the
next rename.

---

## 2026-08-24 — Gemini free-tier flakiness → made Ollama the always-on analyzer fallback

**Symptom (carried from 2026-08-21):** the Gemini OpenAI-compat profile returns empty content
under load (thinking-token exhaustion at low `max_tokens`), and the `AQ.Ab8…` token only
exposes `gemini-3.6-flash`. Net effect this session: with no hosted key in the process env,
`build_analyzer_provider()` returned None and the console showed **llm: unavailable**, so every
finding was static-only — the AI-judgment and "AI finding — unverified" beats were invisible.

**Root cause:** the analyzer hierarchy ended at OpenRouter → None. There was no offline,
keyless fallback, so a missing/flaky hosted key degraded straight to "unavailable".

**Fix:** Added a local **Ollama** fallback (`qwen2.5:7b`, no key) as the last tier of
`build_analyzer_provider()`. `llm doctor` confirms it responds with valid JSON (~7s/call). A
scan of the target now runs static+LLM and yields a **source=BOTH** finding (conf 0.95). If
Ollama isn't running the scan degrades to static-only — never a silent gap. Gemini is left as an
optional hosted primary (`max_tokens=8192`; `gemini-2.5-flash-lite` documented as the
thinking-free option) but is no longer required for the demo.

**Test added:** None (runtime provider wiring). `make llm-doctor` surfaces per-profile health.

**Lesson:** An "AI" product must never show "unavailable" just because a hosted free-tier key is
absent or throttled. Keep a keyless local model as the floor of the provider hierarchy.

---

## 2026-08-24 — Docker sandbox wouldn't boot (`--tmpfs /app/.cache` vs read-only `/app`)

**Symptom:** Making Docker the default sandbox runtime, every target returned
`BLOCKED / TARGET_BOOT_FAILED`. Running the container by hand:
`error mounting "tmpfs" to rootfs at "/app/.cache": … read-only file system`.

**Root cause:** the target is mounted read-only at `/app` (`-v <target>:/app:ro`), and the
runner also asked for `--tmpfs /app/.cache`. Docker can't create the `.cache` mountpoint
*inside* a read-only bind mount, so container init aborted before node ever started. A
second bug: the target bound `127.0.0.1` inside the container, so the published port never
routed even once the tmpfs issue was fixed.

**Fix:** dropped the `/app/.cache` tmpfs (node needs no writable cache; `--tmpfs /tmp` is
separate and fine); bound the targets to `0.0.0.0` (still reachable as 127.0.0.1 on the
host, and now routable via the published port in the container).

**Test added:** `test_dp2_verified_in_docker_runtime` (skips if the daemon is down) —
VERIFIED+MEASURED through the real Docker runtime.

**Lesson:** tmpfs mountpoints must live *outside* a read-only bind, and a containerized
server must bind `0.0.0.0`, not loopback, for `-p` publishing to work. Test the container
by hand (`docker run … node app.js`) before wiring it into the runner.

---

## 2026-08-24 — AC-R1 missed JS charge handlers (`\b/v1/orders\b` never matches a URL)

**Symptom:** The AC-1 target (rupees-as-paise) produced no static finding, so "scan → AC
finding → verify" had nothing to click.

**Root cause:** `_AC_R1_CREATE = \b(orders?\.create|/v1/orders)\b`. In a URL literal
(`fetch("…/v1/orders")`) the `/` is preceded by a quote or `}` — both non-word — so the
leading `\b` never matched. The rule had only ever been exercised on the Python
`order.create` form.

**Fix:** drop the leading boundary for the URL alternative (`\borders?\.create\b|/v1/orders\b`).
16 static rule tests still green; AC-1 targets now flagged, safe control still clean.

**Lesson:** `\b` around a token that starts with punctuation (`/v1/…`) is a no-op or worse.
Test detection rules against every language/idiom the corpus contains, not just the one they
were written for.

---

## 2026-08-24 — grounded eval hung forever (no LLM HTTP timeout)

**Symptom:** The first `--system C+RAG` run on the test split sat at 0% CPU for minutes with an
empty output and zero cache writes — it never completed a single grounded call.

**Root cause:** `OpenAICompatProvider` created the OpenAI client with no timeout. A grounded call
to the local Ollama server stalled (large ~8.7 KB prompt on a 7B model under memory pressure), and
with no client timeout the request blocked indefinitely; the eval process slept forever waiting on
it.

**Fix:** Bounded the client timeout (`PAYGUARD_LLM_TIMEOUT`, default 180s) so a stuck local model
fails the call instead of hanging the eval/worker. Also shrank the grounded prompt (k=2 refs/class,
shorter excerpts: 8.7 KB → 6 KB, 40s → 18s/call) so the run completes reliably.

**Test added:** none (runtime/infra). The timeout is the guard; `make eval` now finishes.

**Lesson:** Any blocking network call to a model — especially a local one that can wedge — needs a
timeout. "It worked in a one-shot test" hides tail latency that a batch run exposes.

---

## 2026-08-24 — grounded analyzer did not beat baseline (measured, kept behind a flag)

**Symptom:** Not a bug — a negative result, recorded per the rule that only an *unmeasured* outcome
is unacceptable. On the frozen test split (n=11, Ollama qwen2.5:7b), C+RAG equalled C exactly:
false positives 17 → 17, macro precision 0.485 → 0.485, F1 0.653 → 0.653.

**Root cause:** The retriever surfaced the right evidence (a citable rule + hard-negative
SAFE_PATTERNs per class — visible in the AI tab), but the 7B analyzer did not change a single
verdict because of it; it kept over-flagging WI/AC even with a matching SAFE_PATTERN in front of it.
A direct probe confirmed the grounded model still flagged the *safe* dedup target at 0.9.

**Fix:** Kept the grounded analyzer OFF by default (`PAYGUARD_ANALYZER=grounded`, opt-in). Documented
the delta and the likely reason (a weak local model won't down-weight its prior on a retrieved
counter-example) in docs/evaluation.md.

**Test added:** `tests/unit/test_kb_leakage.py` guards the corpus; the verdict is reproducible via
`make eval` (A/B/C/C+RAG) + `payguard.eval.compare`.

**Lesson:** Grounding is not free precision — it needs a model strong enough to attend to
references, and a corpus where the baseline makes *retrievable* mistakes. Measure before making it
the default; a sound premise can still lose on a given model/corpus.
