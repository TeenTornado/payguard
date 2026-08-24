# PayGuard — 5-minute demo script

**Setup (once):** Postgres running locally, then:

```bash
make demo          # migrates, starts gateway/api/worker/web (subprocess sandbox), seeds one VERIFIED scan
```

Open **http://localhost:3000**. The seed leaves one clean scan of the dup-fulfillment
target whose CRITICAL finding is already **VERIFIED with MEASURED ₹1,500** — the money
moment is one click away. No Razorpay keys are needed; everything runs on the EMULATE
gateway. (Docker daemon up? `make demo-docker` runs the isolated container sandbox instead.)

---

## The click path (~5 min)

1. **Overview.** System strip shows `api ok · db ok · gateway ok · llm ok · worker idle`.
   LLM is `ok` because the analyzer falls through to local Ollama — not "unavailable".

2. **Start a fresh scan** (optional, to show the pipeline live). New scan →
   `examples/targets/dup-fulfillment-node` → watch INGEST → … → DONE. Two findings appear.

3. **Open the CRITICAL DUPLICATE_PAYMENT finding.** It has:
   - a **title** — "Webhook fulfills the order without an idempotency guard",
   - a **file:line** — `app.js`, with the evidence rendered in the code viewer,
   - **source = BOTH** (static rule DP-R3 *and* the AI analyzer agree, confidence 0.95),
   - **AI reasoning** on the AI tab (labelled unverified until the verifier runs).

4. **Click Verify.** The Verification tab streams the sandbox run:
   `boot → health → create ₹1,500 order → probe fulfilled_count = 0 → deliver signed
   payment.captured #1 → deliver the SAME event #2 → probe fulfilled_count = 2 → verdict`.
   Verdict card: **VERIFIED**, **MEASURED ₹1,500**, tier EMULATED.

5. **Exposure tab.** Now shows **MEASURED ₹1,500** ("observed by driving the running
   target… not an estimate"). Other findings show **ESTIMATED** (dashed) with assumptions —
   never labelled "saved".

6. **Propose a fix, then reject it.** Fix tab → Propose → a diff appears → Reject. Nothing
   auto-merges; the human decision is recorded.

7. **Flip Gateway chaos ON** (Settings → Gateway failure) and **Verify again.** The stream
   retries the gateway and ends **ERROR** (`GATEWAY_UNAVAILABLE`, 3 attempts) — **no MEASURED
   amount is written.** This is the API-failure beat. Flip it back OFF.

8. **Audit log.** Real timestamps, a hash chain (click *Verify chain* → OK), and a
   `VERIFIER / VERIFICATION_COMPLETED` row. Human actions read `HUMAN:demo`.

9. **Safe control (optional).** Scan `examples/targets/dup-fulfillment-node-safe` and Verify
   its DUPLICATE_PAYMENT finding → **NOT_REPRODUCED** (the handler dedups on the event id),
   no MEASURED amount. Proves the verifier doesn't cry wolf.

---

## What is real vs. limited

- **Real:** the target boots as a live process; the gateway signs and delivers real
  webhooks; the ₹1,500 is a counted duplicate fulfillment (state probe 0→2), not a guess.
- **Limited (documented in `docs/failure-modes.md`):** with the Docker daemon down the
  sandbox runs as a **subprocess (no isolation, dev-only)**; the chaos switch is a single
  host-global flag. Both are honest fallbacks, not fakes.
