"""
CLI entry point for running evaluations.

Usage:
    python -m payguard.eval.run --split val
    python -m payguard.eval.run --split val --system B
    python -m payguard.eval.run --split val --system C
    python -m payguard.eval.run --split val --max-samples 5
    python -m payguard.eval.run --split test   # appends to ledger
"""
import argparse
import json
import os
import sys
from pathlib import Path

from payguard.eval.report import write_report
from payguard.eval.runner import EVAL_CLASSES, EvalResult, run_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="PayGuard evaluation runner")
    parser.add_argument("--split", choices=["train", "val", "test"], default="val")
    parser.add_argument(
        "--system", choices=["A", "B", "C", "D"], default="A",
        help="A=static, B=LLM-only, C=static+LLM, D=C+verifier"
    )
    parser.add_argument("--tau", type=float, default=0.45)
    parser.add_argument("--max-samples", type=int, default=None)
    args = parser.parse_args()

    try:
        result = run_eval(split=args.split, system=args.system, tau=args.tau,
                          max_samples=args.max_samples)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    json_path, md_path = write_report(result)

    print(f"\n=== PayGuard Eval: System {result.system} | split={result.split} | "
          f"τ={result.tau} | n={result.n_samples} ===")

    if result.system != "A":
        if result.llm_status == "UNAVAILABLE":
            print(f"LLM: UNAVAILABLE — {result.llm_unavailable_reason}")
        else:
            print(f"LLM: {result.llm_api_calls} API calls, {result.llm_cache_hits} cache hits  "
                  f"model={result.provider_model}")

    if result.llm_status == "UNAVAILABLE":
        print(f"\nMacro  N/A (LLM unavailable)")
    else:
        print(f"\nMacro  P={result.macro_precision:.4f}  R={result.macro_recall:.4f}  "
              f"F1={result.macro_f1:.4f}")
        print(f"\n{'Class':<25} {'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}  "
              f"{'P':>7} {'R':>7} {'F1':>7}")
        print("-" * 68)
        for cls in EVAL_CLASSES:
            m = result.per_class.get(cls)
            if m:
                print(f"{cls:<25} {m.tp:>4} {m.fp:>4} {m.fn:>4} {m.tn:>4}  "
                      f"{m.precision:>7.4f} {m.recall:>7.4f} {m.f1:>7.4f}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for e in result.errors[:10]:
            print(f"  {e}")

    print(f"\nJSON:  {json_path}")
    print(f"MD:    {md_path}")

    if args.split == "test":
        _append_ledger(result, json_path)


def _append_ledger(result: EvalResult, json_path: Path) -> None:
    ledger = Path(__file__).parent.parent.parent / "eval" / "reports" / "test" / "eval_ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    entry: dict = {
        "split": result.split,
        "system": result.system,
        "tau": result.tau,
        "n_samples": result.n_samples,
        "llm_status": result.llm_status,
        "provider_model": result.provider_model,
        "report": str(json_path),
    }
    if result.llm_status != "UNAVAILABLE":
        entry.update({
            "macro_f1": round(result.macro_f1, 4),
            "macro_p": round(result.macro_precision, 4),
            "macro_r": round(result.macro_recall, 4),
        })
    with open(ledger, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"Ledger: {ledger}")


if __name__ == "__main__":
    main()
