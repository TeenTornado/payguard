"""
Feature extraction for risk scoring.

Extracts a numeric feature vector from:
  - Static rule hits (payguard.detector.static_rules.StaticHit)
  - LLM findings (payguard.llm.schema.LLMFinding)

Features are intentionally simple and interpretable — each maps directly to a
heuristic weight in config/scoring_weights.yml.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from payguard.detector.static_rules import StaticHit
    from payguard.llm.schema import LLMFinding


@dataclass
class FeatureVector:
    """Features for one (sample, defect_class) pair."""
    defect_class: str

    # Static signals
    static_hit: bool = False           # any static rule fired for this class
    static_max_confidence: float = 0.0 # highest static rule confidence
    static_n_rules: int = 0            # number of distinct static rules triggered

    # LLM signals
    llm_hit: bool = False              # any LLM finding for this class (above no threshold)
    llm_max_confidence: float = 0.0    # highest LLM finding confidence
    llm_n_findings: int = 0            # number of LLM findings for this class
    llm_has_evidence_lines: bool = False  # at least one finding names specific lines

    # Agreement signal
    both_agree: bool = False           # static and LLM both fired for this class


def extract_features(
    defect_class: str,
    static_hits: "list[StaticHit]",
    llm_findings: "list[LLMFinding]",
) -> FeatureVector:
    """Extract a FeatureVector for one defect_class from hits + findings."""
    fv = FeatureVector(defect_class=defect_class)

    class_static = [h for h in static_hits if h.defect_class.value == defect_class]
    if class_static:
        fv.static_hit = True
        fv.static_max_confidence = max(h.confidence for h in class_static)
        fv.static_n_rules = len({h.rule_id for h in class_static})

    class_llm = [f for f in llm_findings if f.defect_class == defect_class]
    if class_llm:
        fv.llm_hit = True
        fv.llm_max_confidence = max(f.confidence for f in class_llm)
        fv.llm_n_findings = len(class_llm)
        fv.llm_has_evidence_lines = any(f.evidence_lines for f in class_llm)

    fv.both_agree = fv.static_hit and fv.llm_hit

    return fv
