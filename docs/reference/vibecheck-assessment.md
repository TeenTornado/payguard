# VibeCheck Assessment

Source: `~/Downloads/Downloads/archive 9/` — read-only reference, not modified.

## Architecture Summary

VibeCheck is a general-purpose AI-powered vulnerability analyzer for web application code (SQL injection, XSS, command injection, insecure crypto, etc.). It is a student project (SRM Institute, Team 8) with four layers:

1. **Frontend** — Next.js 14 + Monaco Editor. File System Access API for local project upload or GitHub ZIP import. Cursor-like AI chat sidebar. Diff view for applied fixes.
2. **API Gateway** — Next.js API routes proxying to Flask backend and Gemini AI.
3. **Scanner Engine** — Flask + Python: Semgrep with 70+ custom YAML rules, a regex scanner for 20 vulnerability types, and a Random Forest CVSS predictor trained on 180k CVE records.
4. **AI Layer** — Gemini 2.0 Pro/Flash (primary), DeepSeek R1 via OpenRouter (fallback). Used for explanation, fix generation, and chat. No tool calls; LLM is advisory only.

**Evaluation:** ablation on a 995-sample dataset across 10 vulnerability categories. Best system (VibeCheck mode): precision 0.756, recall 0.871, F1 0.809. Dataset is category-balanced, hand-labeled, stored under `dataset/` as Python files with injected defects.

**Orchestration:** no state machine. A single Flask `/scan` endpoint runs Semgrep + regex synchronously; results returned inline. No job queue, no persistence, no audit log.

## Architectural Weaknesses to Avoid

- No persistence layer — scan state lives only in browser memory; a page reload loses everything.
- No job queue — verification is synchronous; no retry, no resume.
- No audit trail — no record of who ran what or what the LLM said.
- LLM receives raw code and returns free text; no schema validation, no nonce boundary, no enum-constrained output.
- Semgrep rules are generic (PHP, JS, Python, Java, C/C++) — not semantically tuned to a protocol (Razorpay amounts, HMAC, idempotency).
- Evaluation dataset is sample-balanced per category but splits are not documented as frozen; test split discipline unclear.
- CVSS ML model (`cvss_model.pkl`) is a black box with no calibration report.
- No sandbox — code is never executed to prove a finding.

## Reuse Decision Table

| Component | Decision | Reason |
|---|---|---|
| Semgrep + custom YAML rule pattern | ADAPT | Rule structure (id, pattern, message, severity, metadata) is well-formed; PayGuard needs Python/JS AST rules, not PHP/generic ones — write from scratch using same structure |
| 10-category vulnerability taxonomy | DISCARD | PayGuard has three specific Razorpay defect classes; general OWASP taxonomy is irrelevant |
| CVSS Random Forest predictor | DISCARD | Predicts generic CVE severity; PayGuard needs calibrated logistic regression over payment-specific features |
| Dataset construction approach (seeded buggy variants) | ADAPT | Template + seeded variant pattern is sound; re-implement for Razorpay mini-apps with `payguard.yml` manifests |
| Ablation study structure (naive vs enriched, per-category metrics) | REUSE | Report structure (systems A/B/C/D, precision/recall/F1, per-class breakdown) is exactly what PayGuard needs |
| Monaco Editor + Cursor-like sidebar UI | DISCARD | PayGuard is an internal risk console, not an IDE |
| Gemini AI integration (free-text, no schema) | DISCARD | PayGuard uses schema-constrained LLM calls (Pydantic, JSON schema, enum-validated output) |
| LLM-as-explainer role (advisory, not decision-maker) | REUSE | Role assignment matches PayGuard's design: LLM generates hypotheses, deterministic verifier is arbiter |
| Flask backend structure | DISCARD | PayGuard uses FastAPI + Pydantic v2 |
| Confidence intervals / McNemar test scripts | ADAPT | Statistical test approach useful for eval report; re-implement cleanly in PayGuard's eval harness |
