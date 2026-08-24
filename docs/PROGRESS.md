# PROGRESS.md

Last updated: 2026-08-24 (session 3)

## Docker sandbox + 3-class verification + AI-security (Aug 24, session 3)

Pushed to `github.com/TeenTornado/payguard` (branch `feat/console-hardening`, PR #1).

- [x] **P0 — Docker is the real sandbox path.** `make demo` boots targets in the isolated
      Docker runtime (read-only rootfs, tmpfs, cpu/mem/pids caps, cap-drop ALL, gateway-only
      network, no real creds); subprocess is a dev-only fallback with a loud WARNING.
      `docs/threat-model.md` documents the controls. Docker-runtime test proves VERIFIED+MEASURED.
- [x] **P1 — all three classes verify (detector + verifier).** WI-1 (forged webhook accepted →
      VERIFIED, MEASURED = order amount) and AC-1 (rupees-as-paise → VERIFIED, MEASURED = the
      discrepancy) join DP-2, each with a safe control (NOT_REPRODUCED) and gateway-chaos ERROR.
      Executor dispatches by finding class; tests for all three.
- [x] **P2 — "AI finding — unverified" beat.** Fixing a DP-R3 false positive (camelCase JS
      dedup) makes the safe target's finding source=LLM; the UI watermarks it and Verify →
      NOT_REPRODUCED. Seeded + scripted.
- [x] **P3 — prompt-injection defense.** injection-probe target (real defect + injection text);
      the analyzer still reports the defect and raises SC-R1 SUSPICIOUS_CONTENT; no SAFE override.
      Test + surfaced in the findings filter + threat-model.
- 114/114 tests green.

### P4 (eval) — NOT STARTED, blocked

The frozen-test eval (≥240 samples, ≥40 lineages, systems A/B/C/D, per-class + macro P/R/F1,
PR curves, calibration/ECE, static-blind recall) is the next major chunk. **Blocked on a Groq
API key** — the brief requires Groq-generated lineages (not OpenRouter), and none is configured
(`GROQ_API_KEY` empty). The harness (`payguard/eval/`) and a frozen `test.manifest.json` exist;
current corpus is 55 samples. Not attempted rather than fake numbers or tune on test. Provide a
Groq key to proceed.

---

## Console + hardening (Aug 24, session 2)

## Sandbox verification + demo polish (Aug 24, session 2)

- [x] **P0 — sandbox → VERIFIED with MEASURED.** Runnable Express targets under
      `examples/targets/` (+ safe control); `payguard/sandbox/` runner (docker/subprocess);
      DP-2 executor boots the target, delivers a signed webhook twice, probes 0→2 →
      **VERIFIED, MEASURED ₹1,500**, tier EMULATED. Streams every step to the Verification tab.
      Gateway chaos → ERROR, no MEASURED. `tests/integration/test_dp2_sandbox.py` proves all three.
- [x] **P1 — empty-field bugs.** Rule→title templates; File/lines + Exposure columns fixed
      (web field mapping); audit `ts` rendered; SCAN_STARTED emitted once; `HUMAN:<name>` actor;
      Findings page defaults to the most recent scan with a scan filter.
- [x] **P2 — LLM never "unavailable".** Always-on Ollama fallback (`qwen2.5:7b`); a scan now
      yields a `source=BOTH` finding (conf 0.95). `make llm-doctor` probes each profile.
- [x] **P3 — exposure visible.** MEASURED (solid, tier) vs ESTIMATED (dashed, assumptions),
      never labelled "saved".
- [x] **P4 — clean demo entry.** `make demo` (Docker-free) starts services + seeds ONE clean
      VERIFIED scan; `docs/demo-script.md` records the 5-min click path.
- 104/104 tests green.

## Known limitations (see docs/failure-modes.md)

- Docker daemon down here → sandbox runs as **subprocess (no isolation, dev-only)**.
- Code-viewer highlight spans the whole flagged unit (JS units are file-scoped).
- One "AI-only unverified" finding is not guaranteed (depends on the local model); the
  `source=BOTH` agreement finding is the reliable AI beat.

## Phase checklist

- [x] **Phase 1** — Skeleton, schemas, audit chain, CI (Aug 21) ✓
- [x] **Phase 2** — DUPLICATE_PAYMENT static rules + examples (Aug 21) ✓
- [x] **Phase 3** — Gateway EMULATE + DP-2 end-to-end (Aug 21) ✓
  - Gateway emulator: orders, payments, capture, refund, checkout simulator, webhooks, chaos
  - Scenarios: DP-2 (VERIFIED on vulnerable, NOT_REPRODUCED on safe, idempotent)
  - 48/48 tests green
- [ ] **Phase 4** — Eval harness v0, System A (target: Aug 25)
- [ ] **Phase 4** — Eval harness v0, System A (target: Aug 25)
- [ ] **Phase 5** — LLM adapter, Systems B+C (target: Aug 26)
- [ ] **Phase 6** — Risk scoring + calibration + exposure (target: Aug 27)
- [ ] **Phase 7** — WEBHOOK_INTEGRITY + AMOUNT_CURRENCY (target: Aug 29)
- [ ] **Phase 8** — Console UI (target: Aug 31)
- [ ] **Phase 9** — Failure matrix, chaos, security (target: Sep 1)
- [ ] **Phase 10** — Dataset scale-up + final eval (target: Sep 2)
- [ ] **Phase 11** — Demo mode (target: Sep 3)
- [ ] **Phase 12** — README, ADRs final, submission (target: Sep 3)

## Console + hardening (Aug 24)

- [x] Console vertical slice (FastAPI REST+SSE, Next.js 8-page console) wired to the real backend
- [x] Transaction convention: `get_db` owns the unit of work (commit-on-return / rollback-on-error);
      no route manages transactions. Grep-guard + read-then-write / rollback integration tests.
- [x] Chaos realism: shared cross-process sentinel `{"llm","gateway"}`; worker honors `llm`,
      gateway honors `gateway` (deterministic 503); two Settings toggles + `make chaos`.
- [x] Verifier executor with bounded gateway retries; `persist_outcome` money-safety choke point
      (MEASURED written only for VERIFIED). Worker now processes VERIFY jobs (no more eternal PENDING).
- [x] Money-safety-under-chaos proven: gateway chaos → DP-2 ERROR after bounded retries, no MEASURED.
- 101/101 tests green.

## Next steps

- Sandbox target runner so a healthy-gateway verification can reach VERIFIED-with-MEASURED in the
  browser (today: BLOCKED without a target, ERROR under gateway chaos — both honest). See
  `docs/failure-modes.md`.
- Demo mode (`make demo` → `payguard.demo.seed`) so first load is never empty.
- WI/AC verification scenarios wired through the executor (DP-2 is the reference path).
- Dataset scale-up + frozen eval (Phase 4).

## Open questions

See `docs/QUESTIONS.md`
