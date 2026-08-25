# Failure modes & known limitations

Design-time limitations we accept deliberately, so they aren't mistaken for bugs or for
production-grade behaviour. Post-incident write-ups live in `FAILURES.md`; this file is the
standing list of "known, bounded, on purpose."

## Chaos sentinel is a single global switch (`payguard/shared/chaos.py`)

The chaos state lives in one JSON file (default `/tmp/.payguard_chaos.json`, overridable via
`PAYGUARD_CHAOS_FILE`) shared by the API, worker, and gateway processes.

**Limitation.** It is **host-global**: one switch for every scan, every verification, every
operator on that machine. There is no per-user, per-tenant, per-scan, or per-request scope. It
is a demo/operability fault-injection control, not application configuration.

**Consequences.**
- Two operators sharing a host cannot have independent chaos states.
- Chaos toggled mid-run affects work already in flight (a scan that hasn't reached the SEMANTIC
  stage, a verification that hasn't made its gateway call yet).
- The file is world-readable in `/tmp` — acceptable because it carries no secret, only two
  booleans. (Bandit `S108` is suppressed at that line with a comment.)

**If this ever needs to be real:** move chaos into per-scope config (DB row keyed by tenant, or
an env-scoped feature flag service) and read it where the scope is known (request context for
the API, job payload for the worker). Do not grow the file into a config store.

## Gateway chaos is deterministic, not probabilistic

When the sentinel's `gateway` switch is on, the gateway returns a deterministic 503 on every
`/v1/*` call (payment + verification). This is intentional: the verifier's bounded-retry →
ERROR path must be reproducible in tests and demos. The legacy `/_test/chaos` toggle still
injects *random* 5xx/latency for older harnesses, but the sentinel path is the one the product
uses. `/_test/*` and `/healthz` are never chaos-gated so state stays inspectable.

## Audit-chain writes are not concurrency-safe under load

`append_audit_event` reads the current tail hash and inserts the next row inside the caller's
transaction, but takes no lock on the tail. Two concurrent transactions can read the same
`prev_hash` and fork the chain. In the current single-worker + low-QPS console this cannot
happen in practice (the worker is serial; API writes are human-paced). A multi-writer
deployment would need `SELECT ... FOR UPDATE` on the tail row, or a dedicated single-writer
audit process. Tracked here so the append-only guarantee isn't assumed to be race-free.

## Verification needs a sandbox target to reach VERIFIED

The verifier drives the gateway, but a DP-2/WI/AC scenario also needs the target merchant app
running so its webhook/charge endpoint can be exercised. Without a sandbox target wired in
(`target_url` on the verify request), a healthy-gateway verification ends **BLOCKED**
(`TARGET_UNAVAILABLE`) — honest, not faked. Under gateway chaos it ends **ERROR** before the
target is ever needed. The sandbox runner that stands up the target automatically is a separate
pending item; until then, VERIFIED-with-MEASURED requires an explicitly supplied target.
