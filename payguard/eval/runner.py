"""
Evaluation runner.

Systems (correct per brief):
  A — static rules only
  B — LLM only
  C — static rules OR LLM (union) — primary ensemble
  D — C + dynamic verifier (Phase 7)

Unit of evaluation: (sample, defect_class) binary.
Positive if ≥1 finding of that class with confidence ≥ τ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from payguard.dataset.catalog import load_all_samples
from payguard.dataset.schema import Sample
from payguard.dataset.splitter import SplitResult, split_samples, validate_test_manifest
from payguard.detector.discovery import (
    PaymentUnit,
    UnitKind,
    _infer_kind,
    _is_payment_relevant,
    discover_payment_units,
)
from payguard.detector.static_rules import run_static_rules
from payguard.shared.enums import DefectClass

EVAL_CLASSES = [
    DefectClass.DUPLICATE_PAYMENT.value,
    DefectClass.WEBHOOK_INTEGRITY.value,
    DefectClass.AMOUNT_CURRENCY.value,
]

System = Literal["A", "B", "C", "D"]


# ─── Metrics ──────────────────────────────────────────────────────────────────

@dataclass
class ClassMetrics:
    defect_class: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "defect_class": self.defect_class,
            "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass
class EvalResult:
    system: str
    split: str
    tau: float
    per_class: dict[str, ClassMetrics] = field(default_factory=dict)
    n_samples: int = 0
    errors: list[str] = field(default_factory=list)
    llm_cache_hits: int = 0
    llm_api_calls: int = 0
    llm_status: str = "OK"          # OK | UNAVAILABLE | PARTIAL
    llm_unavailable_reason: str = ""
    provider_model: str = ""        # model used for LLM (for reports)
    provider_name: str = ""         # provider name (for reports)

    @property
    def llm_available(self) -> bool:
        return self.llm_status != "UNAVAILABLE"

    @property
    def macro_precision(self) -> float:
        active = [m for m in self.per_class.values()
                  if m.defect_class in EVAL_CLASSES and (m.tp + m.fn) > 0]
        if not active:
            active = [m for m in self.per_class.values() if m.defect_class in EVAL_CLASSES]
        return sum(m.precision for m in active) / len(active) if active else 0.0

    @property
    def macro_recall(self) -> float:
        active = [m for m in self.per_class.values()
                  if m.defect_class in EVAL_CLASSES and (m.tp + m.fn) > 0]
        if not active:
            active = [m for m in self.per_class.values() if m.defect_class in EVAL_CLASSES]
        return sum(m.recall for m in active) / len(active) if active else 0.0

    @property
    def macro_f1(self) -> float:
        p, r = self.macro_precision, self.macro_recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    def to_dict(self) -> dict:
        d: dict = {
            "system": self.system,
            "split": self.split,
            "tau": self.tau,
            "n_samples": self.n_samples,
            "llm_status": self.llm_status,
            "llm_unavailable_reason": self.llm_unavailable_reason,
            "provider_model": self.provider_model,
            "provider_name": self.provider_name,
            "llm_cache_hits": self.llm_cache_hits,
            "llm_api_calls": self.llm_api_calls,
            "errors": self.errors,
        }
        if self.llm_status == "UNAVAILABLE":
            d["macro"] = {"precision": None, "recall": None, "f1": None,
                          "note": f"N/A ({self.llm_unavailable_reason})"}
            d["per_class"] = {}
        else:
            d["macro"] = {
                "precision": round(self.macro_precision, 4),
                "recall": round(self.macro_recall, 4),
                "f1": round(self.macro_f1, 4),
            }
            d["per_class"] = {k: v.to_dict() for k, v in self.per_class.items()}
        return d


# ─── Unit helpers ─────────────────────────────────────────────────────────────

def _load_units(sample: Sample) -> list[PaymentUnit]:
    if not sample.file_path or not Path(sample.file_path).exists():
        return []
    fp = Path(sample.file_path)
    units = discover_payment_units(fp.parent if fp.is_file() else fp)
    if not units and fp.is_file():
        src = fp.read_text(errors="replace")
        if _is_payment_relevant(src):
            u = PaymentUnit(
                file=str(fp), symbol=fp.stem,
                start_line=1, end_line=len(src.splitlines()),
                kind=UnitKind.OTHER, source=src,
            )
            u.kind = _infer_kind(src, u.symbol)
            units = [u]
    return units


# ─── System A ─────────────────────────────────────────────────────────────────

def _static_predictions(units: list[PaymentUnit], tau: float) -> dict[str, bool]:
    preds: dict[str, bool] = {c: False for c in EVAL_CLASSES}
    for unit in units:
        for hit in run_static_rules(unit):
            if hit.confidence >= tau and hit.defect_class.value in EVAL_CLASSES:
                preds[hit.defect_class.value] = True
    return preds


# ─── System B / C (LLM) ───────────────────────────────────────────────────────

def _llm_predictions(
    units: list[PaymentUnit],
    tau: float,
    sample_id: str,
    provider,
) -> tuple[dict[str, bool], int, int]:
    """Returns (predictions, n_cache_hits, n_api_calls)."""
    from payguard.llm.adapter import analyze
    from payguard.llm.prompts import SYSTEM_PROMPT, build_analysis_prompt

    preds: dict[str, bool] = {c: False for c in EVAL_CLASSES}
    cache_hits = api_calls = 0

    for unit in units:
        user_prompt = build_analysis_prompt(unit)
        analysis, hit = analyze(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            provider=provider,
            sample_id=sample_id,
        )
        if hit:
            cache_hits += 1
        else:
            api_calls += 1

        for finding in analysis.findings:
            if finding.confidence >= tau and finding.defect_class in EVAL_CLASSES:
                preds[finding.defect_class] = True

    return preds, cache_hits, api_calls


# ─── Evaluate a sample set ────────────────────────────────────────────────────

def evaluate_system(
    samples: list[Sample],
    split_name: str,
    system: System = "A",
    tau: float = 0.45,
    llm_provider=None,
) -> EvalResult:
    result = EvalResult(system=system, split=split_name, tau=tau)
    result.n_samples = len(samples)
    for cls in EVAL_CLASSES:
        result.per_class[cls] = ClassMetrics(defect_class=cls)

    # Resolve provider for systems that need LLM
    provider = None
    if system in ("B", "C", "D"):
        if llm_provider is not None:
            provider = llm_provider
        else:
            from payguard.llm.providers import build_analyzer_provider
            provider = build_analyzer_provider()

        if provider is None:
            result.llm_status = "UNAVAILABLE"
            result.llm_unavailable_reason = "PAYGUARD_LLM_API_KEY not set"
            # For system B/C unavailable: A still runs for C — but brief says return N/A
            # If system=B: return N/A entirely
            # If system=C: we COULD fall back to A, but brief says N/A — don't emit false A numbers
            return result
        else:
            result.provider_name = provider.provider
            result.provider_model = provider.model

    for sample in samples:
        try:
            units = _load_units(sample)
            true_classes = sample.defect_classes()

            if system == "A":
                preds = _static_predictions(units, tau)
            elif system == "B":
                # B = LLM only
                preds, ch, ac = _llm_predictions(units, tau, sample.sample_id, provider)
                result.llm_cache_hits += ch
                result.llm_api_calls += ac
            elif system in ("C", "D"):
                # C = static ∪ LLM
                static_preds = _static_predictions(units, tau)
                llm_preds, ch, ac = _llm_predictions(units, tau, sample.sample_id, provider)
                result.llm_cache_hits += ch
                result.llm_api_calls += ac
                preds = {c: (static_preds.get(c, False) or llm_preds.get(c, False))
                         for c in EVAL_CLASSES}
            else:
                raise ValueError(f"Unknown system: {system}")

            for cls in EVAL_CLASSES:
                m = result.per_class[cls]
                predicted = preds.get(cls, False)
                actual = cls in true_classes
                if predicted and actual:
                    m.tp += 1
                elif predicted and not actual:
                    m.fp += 1
                elif not predicted and actual:
                    m.fn += 1
                else:
                    m.tn += 1
        except Exception as e:
            result.errors.append(f"{sample.sample_id}: {e}")

    return result


# Keep backward-compat alias
def evaluate_system_a(samples: list[Sample], split_name: str, tau: float = 0.45) -> EvalResult:
    return evaluate_system(samples, split_name, system="A", tau=tau)


# ─── Top-level entry ──────────────────────────────────────────────────────────

def run_eval(
    split: str = "val",
    system: System = "A",
    tau: float = 0.45,
    max_samples: int | None = None,
    llm_provider=None,
) -> EvalResult:
    all_samples = load_all_samples()
    splits = split_samples(all_samples)

    if split == "train":
        samples = splits.train
    elif split == "val":
        samples = splits.val
    elif split == "test":
        ok, msg = validate_test_manifest(splits.test)
        if not ok:
            raise RuntimeError(f"Test manifest validation failed: {msg}")
        samples = splits.test
    else:
        raise ValueError(f"Unknown split: {split}")

    if max_samples:
        samples = samples[:max_samples]

    return evaluate_system(samples, split_name=split, system=system, tau=tau, llm_provider=llm_provider)
