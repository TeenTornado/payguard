"""System D evaluation on the RUNNABLE target set.

System D (per the brief): a class is predicted-positive for a sample ONLY if a finding of that
class reaches VERIFIED in the sandbox. This can only run on runnable targets — the frozen test
split is static Flask code (0/11 runnable), so D is measured here on the executable targets under
examples/targets/, reported alongside A (static) and C (static ∪ LLM) on the SAME set so the delta
is attributable.

The thesis this row tests: the LLM widens the net and drops precision (C); the verifier restores
it by demanding sandbox proof (D removes the false positives it cannot reproduce).

    PAYGUARD_OLLAMA_FALLBACK=1 python -m payguard.eval.verify_eval
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from payguard.detector.discovery import discover_payment_units
from payguard.detector.static_rules import run_static_rules
from payguard.shared.config import get_settings
from payguard.verifier.executor import drive_sandbox_scenario

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "examples" / "targets"
EVAL_CLASSES = ["DUPLICATE_PAYMENT", "WEBHOOK_INTEGRITY", "AMOUNT_CURRENCY"]
CLASS_TO_SCENARIO = {"DUPLICATE_PAYMENT": "DP-2", "WEBHOOK_INTEGRITY": "WI-1", "AMOUNT_CURRENCY": "AC-1"}
TAU = 0.45

# (dir, true positive classes). Ground truth = the defects each target actually contains,
# independently verifiable in the sandbox. Empty set = SAFE control (any prediction is a FP).
#   dup-fulfillment-node      : verifies signature (WI-safe), no event-id dedup → DP
#   webhook-forgeable-node    : no signature verify → WI; no dedup → DP (both real)
#   amount-mismatch-node      : rupees-as-paise → AC
#   injection-probe           : reads but never verifies signature → WI; no dedup → DP
#   *-safe                    : all guards present → SAFE
RUNNABLE: list[tuple[str, set[str]]] = [
    ("dup-fulfillment-node", {"DUPLICATE_PAYMENT"}),
    ("webhook-forgeable-node", {"WEBHOOK_INTEGRITY", "DUPLICATE_PAYMENT"}),
    ("amount-mismatch-node", {"AMOUNT_CURRENCY"}),
    ("injection-probe", {"DUPLICATE_PAYMENT", "WEBHOOK_INTEGRITY"}),
    ("dup-fulfillment-node-safe", set()),
    ("webhook-forgeable-node-safe", set()),
    ("amount-mismatch-node-safe", set()),
]


def _static_preds(units) -> set[str]:
    preds: set[str] = set()
    for u in units:
        for h in run_static_rules(u):
            if h.defect_class.value in EVAL_CLASSES and h.confidence >= TAU:
                preds.add(h.defect_class.value)
    return preds


def _llm_preds(units) -> set[str]:
    from payguard.llm.adapter import analyze
    from payguard.llm.prompts import SYSTEM_PROMPT, build_analysis_prompt
    preds: set[str] = set()
    for u in units:
        try:
            analysis, _ = analyze(SYSTEM_PROMPT, build_analysis_prompt(u), sample_id=f"D:{u.file}:{u.symbol}")
        except Exception:
            continue
        for f in analysis.findings:
            if f.defect_class in EVAL_CLASSES and f.confidence >= TAU:
                preds.add(f.defect_class)
    return preds


async def _verified_classes(gateway_url: str, target_dir: str, candidate: set[str]) -> set[str]:
    """D: keep a candidate class only if its scenario reaches VERIFIED in the sandbox."""
    verified: set[str] = set()
    for cls in candidate:
        scenario = CLASS_TO_SCENARIO[cls]
        try:
            outcome = await drive_sandbox_scenario(gateway_url, target_dir, 150000, scenario=scenario)
        except Exception:
            continue
        if outcome.status == "VERIFIED":
            verified.add(cls)
    return verified


def _metrics(rows: list[dict], key: str) -> dict:
    per = {c: {"tp": 0, "fp": 0, "fn": 0} for c in EVAL_CLASSES}
    for r in rows:
        truth, pred = r["true"], r[key]
        for c in EVAL_CLASSES:
            if c in truth and c in pred:
                per[c]["tp"] += 1
            elif c not in truth and c in pred:
                per[c]["fp"] += 1
            elif c in truth and c not in pred:
                per[c]["fn"] += 1
    ps = rs = fs = 0.0
    out = {}
    for c in EVAL_CLASSES:
        tp, fp, fn = per[c]["tp"], per[c]["fp"], per[c]["fn"]
        p = tp / (tp + fp) if tp + fp else 1.0
        r_ = tp / (tp + fn) if tp + fn else 1.0
        f = 2 * p * r_ / (p + r_) if p + r_ else 0.0
        out[c] = {"tp": tp, "fp": fp, "fn": fn, "precision": round(p, 4), "recall": round(r_, 4), "f1": round(f, 4)}
        ps += p; rs += r_; fs += f
    n = len(EVAL_CLASSES)
    return {"per_class": out, "macro": {"precision": round(ps / n, 4), "recall": round(rs / n, 4),
            "f1": round(fs / n, 4)}, "total_fp": sum(out[c]["fp"] for c in EVAL_CLASSES)}


async def run() -> dict:
    gateway_url = get_settings().gateway_url
    rows: list[dict] = []
    for name, true_labels in RUNNABLE:
        target_dir = str(TARGETS / name)
        units = discover_payment_units(target_dir)
        static = _static_preds(units)
        llm = _llm_preds(units)
        C = static | llm
        D = await _verified_classes(gateway_url, target_dir, C)
        rows.append({"target": name, "true": true_labels, "A": static, "C": C, "D": D})
        print(f"  {name:30} true={sorted(true_labels) or ['SAFE']} A={sorted(static)} "
              f"C={sorted(C)} D={sorted(D)}")

    result = {
        "eval_set": "runnable_targets", "n": len(rows),
        "systems": {s: _metrics(rows, s) for s in ("A", "C", "D")},
        "rows": [{**r, "true": sorted(r["true"]), "A": sorted(r["A"]), "C": sorted(r["C"]), "D": sorted(r["D"])}
                 for r in rows],
    }
    return result


def main() -> None:
    result = asyncio.run(run())
    out_dir = ROOT / "eval" / "reports" / "test"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "D_runnable.json").write_text(json.dumps(result, indent=2))
    print("\n=== A / C / D on the runnable target set (n=%d) ===" % result["n"])
    print(f"{'System':8} {'macroP':>8} {'macroR':>8} {'macroF1':>8} {'totalFP':>8}")
    for s in ("A", "C", "D"):
        m = result["systems"][s]
        print(f"{s:8} {m['macro']['precision']:>8} {m['macro']['recall']:>8} "
              f"{m['macro']['f1']:>8} {m['total_fp']:>8}")
    print("\nreport → eval/reports/test/D_runnable.json")


if __name__ == "__main__":
    main()
