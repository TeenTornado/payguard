# PayGuard — CLAUDE.md

Read this file and `docs/PROGRESS.md` + `git log -10` at the start of every session.
Update `PROGRESS.md` and commit at session end.

## Non-negotiables (enforced by code and tests)

1. **TEST MODE ONLY.** Any key not starting with `rzp_test_` is rejected at config load AND at the gateway. A unit test asserts both rejections. There is no live-mode code path.
2. **Never fake.** No fake metrics, fake verification results, or invented failures. Smallest truthful version, labeled.
3. **LLM never decides money-safety alone, never receives tools, repo content is untrusted data.**
4. **Held-out test split is frozen.** Never used for rule/prompt/threshold development. Every test-split eval appended to `eval/reports/ledger.jsonl`.
5. **Humans approve remediation.** Nothing auto-merges. FORWARD_TEST verification requires explicit human click.
6. **Every significant action audited** in append-only hash-chained `audit_events` table.
7. **`FAILURES.md` is a running log of real failures**, appended the moment they happen.
8. **A phase is done only when tests are green, work is committed, and `docs/PROGRESS.md` is updated.**

## How to run

```bash
make setup        # install uv, create venv, install deps
make up           # docker compose up (postgres, api, gateway, worker, web)
make down         # docker compose down
make migrate      # alembic upgrade head
make test         # pytest unit + integration
make lint         # ruff check
make typecheck    # mypy
make eval-dev     # eval on validation split only
make eval         # eval on test split, appends to ledger
make eval-smoke   # quick sanity check (5 samples)
make audit-verify # recompute hash chain, fail on tampering
make demo         # bring up demo mode (PAYGUARD_DEMO=1)
make chaos        # toggle gateway failure injection
make seed-examples # seed examples/ into the database
make clean        # remove build artifacts
```

## Module boundaries

- `payguard/shared/` — enums, models, config, audit. No imports from other payguard modules.
- `payguard/detector/` — discovery, static rules, LLM analysis. May import `shared`.
- `payguard/risk/` — scoring, calibration, exposure. May import `shared`.
- `payguard/gateway/` — HTTP service (standalone). May import `shared`.
- `payguard/sandbox/` — Docker runner. May import `shared`.
- `payguard/verifier/` — scenario execution. May import `shared`, `gateway`, `sandbox`.
- `payguard/agent/` — state machine orchestration. May import `shared`, `detector`, `risk`, `verifier`.
- `payguard/api/` — FastAPI routes. May import `shared`, `agent`.
- `payguard/worker/` — job queue consumer. May import `shared`, `agent`.
- `payguard/dataset/` — sample schema, generators, splits. May import `shared`.
- `payguard/eval/` — evaluation harness. May import `shared`, `detector`, `risk`.

## Commit conventions

`feat:`, `fix:`, `test:`, `docs:`, `chore:` — one concern each, small.

## Evaluation rules

- `make eval-dev` → validation split only. Safe to run anytime.
- `make eval` → test split. Appends to ledger. Run sparingly; never cherry-pick runs.
- Never skip, xfail, or delete a test to go green.
- Never lower a threshold to improve a number without an ADR + ledger entry.

## Secrets

- `.env` is gitignored. `.env.example` is committed.
- `Authorization` headers always redacted: `Basic rzp_test_****`.
- `gitleaks` pre-commit hook active.

## Reporting style

Terse. No cheerleading. What works (with the command), what is untested, numbers, open questions.

## ADR index

- ADR-001: Verifier is the arbiter of money-safety claims
- ADR-002: No LLM for deterministic checks (signature math, key prefixes, amount arithmetic)
- ADR-003: Test mode mandatory, enforced by key prefix check at config load and gateway
- ADR-004: Repository-level splits prevent label leakage
- ADR-005: Remediation requires human approval, never auto-merges
- ADR-006: Hand-rolled typed state machine over LangGraph
- ADR-007: Postgres-backed job queue (SELECT FOR UPDATE SKIP LOCKED)
- ADR-008: Gateway = EMULATE mode + recording FORWARD_TEST proxy with credential injection
- ADR-009: Docker sandbox + routing tiers (RAZORPAY_BASE_URL Tier A, transparent intercept Tier B)
- ADR-010: MEASURED vs ESTIMATED exposure, always labeled, never conflated
