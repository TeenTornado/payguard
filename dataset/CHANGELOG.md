# Dataset Changelog

Append-only. Every re-freeze of the test manifest must be recorded here.

---

## v1 — 2026-08-21 (initial)

**Samples:** 46 total (11 hand-crafted examples + 35 generated SEEDED_VARIANT from 7 Flask templates × 5 variants each)
**Split:** train=28, val=7, test=11 (seed=42, repo-level)
**Test manifest:** frozen at `dataset/splits/test.manifest.json`
**Notes:** All samples are `static_detectable=True` (generated templates are textbook vulnerabilities matched to static rules). No static-blind positives or hard negatives beyond the original examples/.

---

## v2 — 2026-08-21

**Samples:** 66 total
- 35 SEEDED_VARIANT (unchanged from v1)
- 11 original hand-crafted examples (unchanged from v1)
- 10 static-blind positives (MANUAL, `static_detectable=False`):
  sb-dp-wrong-field, sb-dp-dedup-resets, sb-dp-race-condition, sb-dp-callchain, sb-dp-key-collision,
  sb-wi-helper-sig, sb-wi-wrong-body, sb-wi-event-id-missing,
  sb-ac-double-conversion, sb-ac-module-boundary
- 10 hard negatives (MANUAL, `hard_negative=True`, `labels=[]`):
  hn-dp-db-unique, hn-dp-imported-util, hn-dp-redis-dedup, hn-dp-celery-dedup,
  hn-wi-raw-body-middleware, hn-wi-compare-digest, hn-wi-env-webhook-secret,
  hn-ac-amount-paise-variable, hn-ac-decimal-math, hn-ac-server-computed

**Split:** train=44, val=11, test=11 (seed=42, repo-level)
**Test manifest:** re-frozen at `dataset/splits/test.manifest.json`
**Reason for re-freeze:** Added static-blind positives and hard negatives. Test manifest must be re-frozen before any test-split evaluation on v2 samples.

**IMPORTANT:** No test-split evaluation has been run on v2 samples. The test split
is frozen; all eval-dev runs against val split only. The v1 val-split numbers
(eval/reports/dev/) are from v1 samples only and are not directly comparable to v2 numbers.

---
