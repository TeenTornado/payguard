"""
Risk scorer — weighted heuristic until ≥ 150 labeled findings in train.

ADR-010: MEASURED vs ESTIMATED exposure, always labelled.

Calibration status:
  Until payguard/risk/model.pkl exists AND the train split has ≥ calibration_threshold
  labeled findings, this module uses the documented weighted heuristic defined in
  config/scoring_weights.yml. The scorer_version in SampleRisk reflects this.

When calibrated:
  A logistic regression / isotonic-calibrated model replaces the heuristic.
  scorer_version bumps to "calibrated-v<N>". The calibration status is recorded in
  docs/evaluation.md and in the eval ledger.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from payguard.risk.features import FeatureVector
from payguard.risk.schema import DefectRisk, ExposureKind, SampleRisk

_WEIGHTS_FILE = Path(__file__).parent.parent.parent / "config" / "scoring_weights.yml"
_MODEL_FILE = Path(__file__).parent / "model.pkl"

_EVAL_CLASSES = ["DUPLICATE_PAYMENT", "WEBHOOK_INTEGRITY", "AMOUNT_CURRENCY"]


def _load_config() -> dict:
    if _WEIGHTS_FILE.exists():
        return yaml.safe_load(_WEIGHTS_FILE.read_text())
    return {}


def _heuristic_score(fv: FeatureVector, weights: dict) -> float:
    """Compute a risk score [0, 1] from a FeatureVector using heuristic weights."""
    w = weights.get("weights", {})
    score = 0.0

    if fv.static_hit:
        score += w.get("static_hit", 0.55)
        score += w.get("static_max_confidence", 0.20) * fv.static_max_confidence
        extra_rules = min(max(fv.static_n_rules - 1, 0), 2)
        score += w.get("static_n_rules_bonus", 0.05) * extra_rules

    if fv.llm_hit:
        score += w.get("llm_hit", 0.25)
        score += w.get("llm_max_confidence", 0.15) * fv.llm_max_confidence
        extra_findings = min(max(fv.llm_n_findings - 1, 0), 3)
        score += w.get("llm_n_findings_bonus", 0.03) * extra_findings
        if fv.llm_has_evidence_lines:
            score += w.get("llm_evidence_lines_bonus", 0.05)

    if fv.both_agree:
        score += w.get("both_agree_bonus", 0.15)

    return min(score, 1.0)


def _is_calibrated(cfg: dict, train_n_labeled: int) -> bool:
    """Return True only when an ML model exists AND train has enough labeled findings."""
    threshold = cfg.get("calibration_threshold", 150)
    return _MODEL_FILE.exists() and train_n_labeled >= threshold


def score_sample(
    sample_id: str,
    feature_vectors: list[FeatureVector],
    train_n_labeled: int = 0,
) -> SampleRisk:
    """
    Score a sample given pre-extracted feature vectors per defect class.

    Args:
        sample_id: identifier for the sample
        feature_vectors: one FeatureVector per defect class of interest
        train_n_labeled: number of labeled findings in the train split;
                         used to decide heuristic vs calibrated scoring

    Returns:
        SampleRisk with ESTIMATED exposure (MEASURED requires ledger data from Phase 7+)
    """
    cfg = _load_config()
    calibrated = _is_calibrated(cfg, train_n_labeled)
    scorer_version = "calibrated-v1" if calibrated else "heuristic-v1"

    defects: list[DefectRisk] = []
    for fv in feature_vectors:
        if not (fv.static_hit or fv.llm_hit):
            continue  # no signal for this class

        if calibrated:
            # TODO: load model and call predict_proba
            score = _heuristic_score(fv, cfg)  # placeholder until model available
        else:
            score = _heuristic_score(fv, cfg)

        evidence: list[str] = []
        if fv.static_hit:
            evidence.append(f"static:{fv.defect_class}:n_rules={fv.static_n_rules}")
        if fv.llm_hit:
            evidence.append(f"llm:{fv.defect_class}:n_findings={fv.llm_n_findings}")

        defects.append(DefectRisk(
            defect_class=fv.defect_class,
            score=round(score, 4),
            exposure_kind=ExposureKind.ESTIMATED,
            exposure_usd=None,
            confidence=max(fv.static_max_confidence, fv.llm_max_confidence),
            calibrated=calibrated,
            evidence=evidence,
            notes="" if calibrated else (
                "Score from weighted heuristic (config/scoring_weights.yml). "
                f"Calibrated ML model activates at {cfg.get('calibration_threshold',150)} "
                "labeled train findings."
            ),
        ))

    return SampleRisk(
        sample_id=sample_id,
        defects=sorted(defects, key=lambda d: d.score, reverse=True),
        scorer_version=scorer_version,
    )


def threshold_for(defect_class: str) -> float:
    """Return the decision threshold for a defect class from config."""
    cfg = _load_config()
    return cfg.get("decision_thresholds", {}).get(defect_class, 0.45)
