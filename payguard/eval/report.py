"""
Evaluation report generation.

Report directories:
  eval/reports/dev/  — `make eval-dev` (val split, exploratory; never cite in README)
  eval/reports/test/ — `make eval` (frozen test split; the official numbers)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from payguard.eval.runner import EVAL_CLASSES, EvalResult

_REPO_ROOT = Path(__file__).parent.parent.parent
# Legacy reports/ dir kept for backward compat; new writes go to eval/reports/
REPORTS_DIR = _REPO_ROOT / "reports"


def _reports_dir(result: EvalResult) -> Path:
    """Return the correct subdirectory based on split."""
    if result.split == "test":
        return _REPO_ROOT / "eval" / "reports" / "test"
    return _REPO_ROOT / "eval" / "reports" / "dev"


def write_report(result: EvalResult, prefix: str = "") -> tuple[Path, Path]:
    out_dir = _reports_dir(result)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = f"{prefix}{result.system}_{result.split}_n{result.n_samples}_{ts}"

    json_path = out_dir / f"{slug}.json"
    md_path = out_dir / f"{slug}.md"

    data = result.to_dict()
    data["generated_at"] = ts
    data["report_dir"] = str(out_dir.relative_to(_REPO_ROOT))
    json_path.write_text(json.dumps(data, indent=2))
    md_path.write_text(_render_md(result, ts))

    return json_path, md_path


def _na(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"{val:.4f}"


def _render_md(result: EvalResult, ts: str) -> str:
    system_desc = {
        "A": "static rules only",
        "B": "LLM only",
        "C": "static ∪ LLM (ensemble)",
        "D": "C + dynamic verifier",
    }.get(result.system, result.system)

    lines = [
        f"# PayGuard Evaluation Report",
        f"",
        f"**System**: {result.system} ({system_desc})  "
        f"**Split**: {result.split}  **τ**: {result.tau}  "
        f"**Samples**: {result.n_samples}  **Generated**: {ts}",
        f"",
    ]

    if result.system != "A":
        if result.llm_status == "UNAVAILABLE":
            lines += [
                f"**LLM status**: UNAVAILABLE — {result.llm_unavailable_reason}",
                f"",
                f"> Results are N/A because the LLM provider is not configured.",
                f"> Set PAYGUARD_LLM_API_KEY and re-run to obtain real B/C metrics.",
                f"",
            ]
            lines += [f"---", f"*{system_desc}.*"]
            return "\n".join(lines) + "\n"
        else:
            lines += [
                f"**LLM**: {result.llm_api_calls} API calls, "
                f"{result.llm_cache_hits} cache hits  "
                f"model={result.provider_model} ({result.provider_name})",
                f"",
            ]

    lines += [
        f"## Macro Averages (3 eval classes)",
        f"",
        f"| Precision | Recall | F1 |",
        f"|-----------|--------|----|",
        f"| {_na(round(result.macro_precision, 4) if result.llm_status != 'UNAVAILABLE' else None)} "
        f"| {_na(round(result.macro_recall, 4) if result.llm_status != 'UNAVAILABLE' else None)} "
        f"| {_na(round(result.macro_f1, 4) if result.llm_status != 'UNAVAILABLE' else None)} |",
        f"",
        f"## Per-Class Metrics",
        f"",
        f"| Class | TP | FP | FN | TN | Precision | Recall | F1 |",
        f"|-------|----|----|----|-----|-----------|--------|----|",
    ]

    for cls in EVAL_CLASSES:
        m = result.per_class.get(cls)
        if m and result.llm_status != "UNAVAILABLE":
            lines.append(
                f"| {cls} | {m.tp} | {m.fp} | {m.fn} | {m.tn} "
                f"| {m.precision:.4f} | {m.recall:.4f} | {m.f1:.4f} |"
            )
        else:
            lines.append(f"| {cls} | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")

    if result.errors:
        lines += [f"", f"## Errors ({len(result.errors)})", f""]
        for e in result.errors[:20]:
            lines.append(f"- `{e}`")

    lines += [
        f"",
        f"---",
        f"*A=static rules, B=LLM only, C=static∪LLM, D=C+verifier. "
        f"LLM never decides money-safety alone (ADR-001).*",
    ]
    return "\n".join(lines) + "\n"
