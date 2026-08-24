# PayGuard — Evaluation Limitations

Generated: see report timestamps. This document describes known constraints on evaluation validity.

## Provider Limitations

### Free-tier providers

All evaluations in this project use free-tier API quotas unless otherwise noted in the report.
Dev-split reports go to `eval/reports/dev/`; frozen test-split reports go to `eval/reports/test/`.

| Provider | Role | RPM limit | Notes |
|----------|------|-----------|-------|
| Google Gemini (direct) | Primary analyzer | 8 | Free tier; see data privacy note below |
| Groq (direct) | Primary generator | 25 | Free tier; llama-3.3-70b-versatile |
| OpenRouter | Last-resort fallback | 50 RPD | Only used when primary key is absent; max 1 retry |
| Ollama (local) | Offline fallback | unlimited | No external calls |

### Data privacy — Gemini free tier

Google's free tier for Gemini may use submitted prompts to improve models.
**Inputs are synthetic only**: generated Flask mini-shops (payguard/dataset/generator.py) and examples/
directory code. No real merchant code, customer data, or proprietary Razorpay code is ever submitted.

### Model version pinning

Every eval report records the exact model string in `provider_model`. Gemini-2.5-flash and
llama-3.3-70b are actively updated by their providers. Metric differences between runs may reflect
model updates, not rule/prompt changes. Pin model versions for reproducibility.

## Evaluation Protocol Constraints

### Dataset size (Phase 4–5)

- Total samples: ~46 (11 hand-crafted + 35 generated variants from 7 templates)
- Val/test each ~7 samples. Numbers at this scale have high variance.
- F1=1.0 on clean generated samples is expected; hard samples (Phase 10 scale-up) are needed.

### System A perfect recall on generated samples

Generated templates are textbook-clean vulnerabilities matched to static rules.
Real-world code has obfuscation, wrappers, and indirect data flows that static rules miss.
System A's F1=1.0 on val does NOT generalize to real integrations.

### LLM evaluation (Systems B, C)

- System B (LLM only): measures LLM detection without rule scaffolding.
- System C (static ∪ LLM): the intended production system. Never reported as System A numbers.
- When LLM provider is unavailable, reports print N/A — never silently fall back to System A metrics.

### Test split is frozen

`dataset/splits/test.manifest.json` is frozen at dataset creation.
Every test-split eval appends to `reports/eval_ledger.jsonl`.
Test split is never used to develop rules, prompts, or thresholds.

## Risk Scoring — Calibration Status

### Heuristic phase (current)

The risk scorer (`payguard/risk/scorer.py`) is in **heuristic mode** until the train split
accumulates ≥ 150 labeled findings. In this mode:

- Scores are computed from a weighted sum of static and LLM signals.
- Weights are defined in `config/scoring_weights.yml` and encode domain knowledge.
- All exposures are labelled **ESTIMATED** — no ledger data available.
- `SampleRisk.calibrated = False` and `scorer_version = "heuristic-v1"` in all outputs.

When ≥ 150 labeled findings exist in train, a logistic regression with isotonic calibration
replaces the heuristic. The scorer_version will bump to `calibrated-v1` and this section
will be updated.

**Do not report calibrated F1/precision/recall from heuristic-mode scores.** The heuristic
is a structural placeholder, not a measured classifier.

### Threshold configuration

Decision thresholds per defect class are in `config/scoring_weights.yml` under
`decision_thresholds`. The eval harness `--tau` flag overrides these for sweep experiments.

## Quotas

Free-tier quotas are per Google/Groq project, not per API key.
OpenRouter is 50 RPD total (unfunded), making it unsuitable for multi-system eval runs.
If quota is exhausted mid-eval, affected samples log `RATE_LIMITED` in the ledger.
Re-run after quota resets; compare partial-vs-full run totals.

**OpenRouter caveat:** `:free` model variants on OpenRouter can be delisted without notice.
Eval runs that depend on specific model versions may silently route to a different model.
Always use provider-direct keys (Gemini, Groq) for reproducible eval runs.

## Frozen test-split results — 2026-08-24 (A/B/C, n=11)

First real evaluation on the frozen test split (`dataset/splits/test.manifest.json`, 11 samples).
Analyzer: local **Ollama `qwen2.5:7b`** (no hosted key configured; `PAYGUARD_OLLAMA_FALLBACK=1`).
Reports: `eval/reports/test/{A,B,C}_test_n11_*.json`; ledger appended.

| System | Macro P | Macro R | Macro F1 | Per-class notes |
|--------|--------:|--------:|---------:|-----------------|
| A (static rules)   | 0.889 | 1.000 | 0.941 | DP 1.0 / WI 0.80 (1 FP) / AC 1.0 |
| B (LLM only)       | 0.485 | 0.778 | 0.597 | DP R=0.33 (2 FN); **WI 9 FP**, **AC 8 FP** |
| C (static ∪ LLM)   | 0.485 | 1.000 | 0.653 | DP 1.0; WI/AC precision wrecked by the LLM's FPs |

**Reading.** Static (A) is precise here; the local LLM (B) is wildly over-eager on WEBHOOK_INTEGRITY
and AMOUNT_CURRENCY (17 false positives across 11 samples), and C = A∪LLM inherits every one — C's
macro precision collapses to 0.485 while recall is perfect. This is precisely the failure mode the
grounded/retrieval-augmented analyzer targets: **cut the LLM's false positives without losing recall.**
The next phase measures C vs C+RAG on this same frozen split.

**Caveats (honest):** n=11 is small — high variance; a single FP swings per-class precision a lot.
These numbers are a real baseline, not a leaderboard claim. The dataset scale-up (≥240 samples) needs a
Groq generation key and remains separate. `qwen2.5:7b` is a weak analyzer; a stronger hosted model would
likely move B/C, but the point of C+RAG is to improve *whatever* analyzer is in use.
