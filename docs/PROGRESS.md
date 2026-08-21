# PROGRESS.md

Last updated: 2026-08-21

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

## Next steps (current session)

- Write payguard/shared/ (enums, config, audit)
- Write SQLAlchemy models + Alembic migration
- Write audit-verify make target + unit test
- Write ADR-001..005
- Write CI workflow

## Open questions

See `docs/QUESTIONS.md`
