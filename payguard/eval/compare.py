"""Side-by-side comparison of eval systems on the frozen test split (C vs C+RAG focus).

Loads the latest report per system from eval/reports/test/, computes per-class and macro
precision/recall/F1, total false-positive count, and an FP-cost (FP count x unit cost from
config/costs.yml, default 1). Emits a dict (for the Evaluation page) and a printed table.
"""
from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
TEST_DIR = _ROOT / "eval" / "reports" / "test"
COSTS = _ROOT / "config" / "costs.yml"

EVAL_CLASSES = ["DUPLICATE_PAYMENT", "WEBHOOK_INTEGRITY", "AMOUNT_CURRENCY"]


def _fp_cost_weight() -> float:
    try:
        import yaml
        return float(yaml.safe_load(COSTS.read_text()).get("false_positive_cost", 1.0))
    except Exception:
        return 1.0


def latest_report(system: str) -> dict | None:
    # Filenames start with e.g. "C_test_" and "C+RAG_test_"; match the exact system token.
    prefix = f"{system}_test_"
    files = sorted((f for f in TEST_DIR.glob("*.json") if f.name.startswith(prefix)),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text(encoding="utf-8"))


def _total_fp(report: dict) -> int:
    return sum(int(pc.get("fp", 0)) for pc in (report.get("per_class") or {}).values())


def _prf(d: dict) -> dict:
    # Reports store precision/recall/f1; expose them as p/r/f1 for the UI.
    return {"p": d.get("precision"), "r": d.get("recall"), "f1": d.get("f1")}


def summarize(report: dict) -> dict:
    pc = report.get("per_class") or {}
    return {
        "system": report.get("system"),
        "n_samples": report.get("n_samples"),
        "provider_model": report.get("provider_model"),
        "macro": _prf(report.get("macro") or {}),
        "total_fp": _total_fp(report),
        "per_class": {c: {"tp": pc.get(c, {}).get("tp"), "fp": pc.get(c, {}).get("fp"),
                          "fn": pc.get(c, {}).get("fn"), **_prf(pc.get(c, {}))}
                      for c in EVAL_CLASSES},
    }


def runnable_avd() -> dict | None:
    """System A/C/D on the runnable target set (from verify_eval) — the verifier's precision
    restoration. Separate from the frozen Flask test split (which has no runnable samples)."""
    p = TEST_DIR / "D_runnable.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    sysd = d.get("systems", {})
    return {
        "n": d.get("n"),
        "systems": {s: {"macro": _prf(sysd.get(s, {}).get("macro", {})),
                        "total_fp": sysd.get(s, {}).get("total_fp")}
                    for s in ("A", "C", "D") if s in sysd},
    }


def compare(systems: list[str] | None = None) -> dict:
    systems = systems or ["A", "B", "C", "C+RAG"]
    reports = {s: latest_report(s) for s in systems}
    summaries = {s: summarize(r) for s, r in reports.items() if r}

    delta = None
    if "C" in summaries and "C+RAG" in summaries:
        c, rag = summaries["C"], summaries["C+RAG"]
        w = _fp_cost_weight()
        delta = {
            "fp_before": c["total_fp"], "fp_after": rag["total_fp"],
            "fp_cost_before": c["total_fp"] * w, "fp_cost_after": rag["total_fp"] * w,
            "precision_before": c["macro"].get("p"), "precision_after": rag["macro"].get("p"),
            "recall_before": c["macro"].get("r"), "recall_after": rag["macro"].get("r"),
            "f1_before": c["macro"].get("f1"), "f1_after": rag["macro"].get("f1"),
            "fp_cost_weight": w,
        }
    return {"summaries": summaries, "c_vs_crag": delta, "runnable_avd": runnable_avd()}


def _fmt(x, nd=3):
    return f"{x:.{nd}f}" if isinstance(x, (int, float)) else "—"


def print_table(cmp: dict) -> None:
    print("\n=== Frozen test split: system comparison ===")
    print(f"{'System':8} {'model':16} {'macroP':>7} {'macroR':>7} {'macroF1':>8} {'totalFP':>8}")
    for s, sm in cmp["summaries"].items():
        m = sm["macro"]
        print(f"{s:8} {str(sm['provider_model'])[:16]:16} "
              f"{_fmt(m.get('p')):>7} {_fmt(m.get('r')):>7} {_fmt(m.get('f1')):>8} {sm['total_fp']:>8}")
    rav = cmp.get("runnable_avd")
    if rav:
        print(f"\n=== Runnable targets (n={rav['n']}): the verifier restores precision (A/C/D) ===")
        print(f"{'System':8} {'macroP':>8} {'macroR':>8} {'macroF1':>8} {'totalFP':>8}")
        for s in ("A", "C", "D"):
            if s in rav["systems"]:
                m = rav["systems"][s]["macro"]
                print(f"{s:8} {_fmt(m.get('p')):>8} {_fmt(m.get('r')):>8} {_fmt(m.get('f1')):>8} "
                      f"{rav['systems'][s]['total_fp']:>8}")

    d = cmp.get("c_vs_crag")
    if d:
        print("\n--- C vs C+RAG ---")
        print(f"  false positives: {d['fp_before']} -> {d['fp_after']}")
        print(f"  FP-cost (w={d['fp_cost_weight']}): {d['fp_cost_before']} -> {d['fp_cost_after']}")
        print(f"  macro precision: {_fmt(d['precision_before'])} -> {_fmt(d['precision_after'])}")
        print(f"  macro recall:    {_fmt(d['recall_before'])} -> {_fmt(d['recall_after'])}")
        print(f"  macro F1:        {_fmt(d['f1_before'])} -> {_fmt(d['f1_after'])}")


def main() -> None:
    print_table(compare())


if __name__ == "__main__":
    main()
