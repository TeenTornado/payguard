"""
Unit tests for Phase 6 risk scorer (feature extraction + heuristic scoring).
No LLM calls — all inputs are constructed directly.
"""
from __future__ import annotations

import pytest

from payguard.risk.features import FeatureVector, extract_features
from payguard.risk.schema import ExposureKind, SampleRisk
from payguard.risk.scorer import score_sample, threshold_for


# ─── Feature extraction ───────────────────────────────────────────────────────

class TestFeatureExtraction:
    def test_no_signals_all_false(self):
        fv = extract_features("DUPLICATE_PAYMENT", static_hits=[], llm_findings=[])
        assert not fv.static_hit
        assert not fv.llm_hit
        assert not fv.both_agree

    def test_static_only(self):
        from unittest.mock import MagicMock
        from payguard.shared.enums import DefectClass

        hit = MagicMock()
        hit.defect_class = DefectClass.DUPLICATE_PAYMENT
        hit.confidence = 0.9
        hit.rule_id = "DP-R1"

        fv = extract_features("DUPLICATE_PAYMENT", static_hits=[hit], llm_findings=[])
        assert fv.static_hit
        assert fv.static_max_confidence == 0.9
        assert fv.static_n_rules == 1
        assert not fv.llm_hit
        assert not fv.both_agree

    def test_llm_only_with_evidence(self):
        from payguard.llm.schema import LLMFinding

        f = LLMFinding(
            defect_class="WEBHOOK_INTEGRITY",
            confidence=0.85,
            explanation="no sig check",
            evidence_lines=[10, 11],
        )
        fv = extract_features("WEBHOOK_INTEGRITY", static_hits=[], llm_findings=[f])
        assert fv.llm_hit
        assert fv.llm_max_confidence == 0.85
        assert fv.llm_n_findings == 1
        assert fv.llm_has_evidence_lines
        assert not fv.static_hit
        assert not fv.both_agree

    def test_both_agree(self):
        from unittest.mock import MagicMock
        from payguard.shared.enums import DefectClass
        from payguard.llm.schema import LLMFinding

        hit = MagicMock()
        hit.defect_class = DefectClass.DUPLICATE_PAYMENT
        hit.confidence = 0.7
        hit.rule_id = "DP-R1"

        f = LLMFinding(
            defect_class="DUPLICATE_PAYMENT",
            confidence=0.8,
            explanation="no dedup",
        )
        fv = extract_features("DUPLICATE_PAYMENT", static_hits=[hit], llm_findings=[f])
        assert fv.both_agree

    def test_different_class_not_counted(self):
        from unittest.mock import MagicMock
        from payguard.shared.enums import DefectClass

        hit = MagicMock()
        hit.defect_class = DefectClass.WEBHOOK_INTEGRITY
        hit.confidence = 0.9
        hit.rule_id = "WI-R1"

        fv = extract_features("DUPLICATE_PAYMENT", static_hits=[hit], llm_findings=[])
        assert not fv.static_hit  # wrong class


# ─── Scorer ───────────────────────────────────────────────────────────────────

class TestHeuristicScorer:
    def test_no_signals_no_defects(self):
        fv = FeatureVector(defect_class="DUPLICATE_PAYMENT")
        result = score_sample("s-1", [fv])
        assert result.defects == []

    def test_static_only_score_positive(self):
        fv = FeatureVector(
            defect_class="DUPLICATE_PAYMENT",
            static_hit=True,
            static_max_confidence=0.9,
            static_n_rules=1,
        )
        result = score_sample("s-1", [fv])
        assert len(result.defects) == 1
        d = result.defects[0]
        assert d.score > 0.5  # static alone should exceed 0.5
        assert d.exposure_kind == ExposureKind.ESTIMATED
        assert not d.calibrated

    def test_llm_only_score_lower_than_static(self):
        fv_static = FeatureVector(
            defect_class="DUPLICATE_PAYMENT",
            static_hit=True,
            static_max_confidence=0.9,
        )
        fv_llm = FeatureVector(
            defect_class="DUPLICATE_PAYMENT",
            llm_hit=True,
            llm_max_confidence=0.9,
        )
        static_result = score_sample("s-1", [fv_static])
        llm_result = score_sample("s-2", [fv_llm])
        assert static_result.defects[0].score > llm_result.defects[0].score

    def test_both_agree_higher_than_either_alone(self):
        fv_both = FeatureVector(
            defect_class="WEBHOOK_INTEGRITY",
            static_hit=True, static_max_confidence=0.7, static_n_rules=1,
            llm_hit=True, llm_max_confidence=0.8, llm_n_findings=1,
            both_agree=True,
        )
        fv_static_only = FeatureVector(
            defect_class="WEBHOOK_INTEGRITY",
            static_hit=True, static_max_confidence=0.7, static_n_rules=1,
        )
        both_result = score_sample("s-1", [fv_both])
        static_result = score_sample("s-2", [fv_static_only])
        assert both_result.defects[0].score > static_result.defects[0].score

    def test_score_capped_at_one(self):
        fv = FeatureVector(
            defect_class="AMOUNT_CURRENCY",
            static_hit=True, static_max_confidence=1.0, static_n_rules=3,
            llm_hit=True, llm_max_confidence=1.0, llm_n_findings=5,
            llm_has_evidence_lines=True, both_agree=True,
        )
        result = score_sample("s-1", [fv])
        assert result.defects[0].score <= 1.0

    def test_scorer_version_heuristic(self):
        fv = FeatureVector(defect_class="DUPLICATE_PAYMENT", static_hit=True,
                           static_max_confidence=0.9)
        result = score_sample("s-1", [fv], train_n_labeled=0)
        assert result.scorer_version == "heuristic-v1"

    def test_exposure_always_estimated_in_heuristic(self):
        fv = FeatureVector(defect_class="DUPLICATE_PAYMENT", static_hit=True,
                           static_max_confidence=0.9)
        result = score_sample("s-1", [fv])
        assert result.defects[0].exposure_kind == ExposureKind.ESTIMATED
        assert result.defects[0].exposure_usd is None

    def test_evidence_list_populated(self):
        fv = FeatureVector(
            defect_class="DUPLICATE_PAYMENT",
            static_hit=True, static_n_rules=2,
            llm_hit=True, llm_n_findings=1,
            both_agree=True,
        )
        result = score_sample("s-1", [fv])
        evidence = result.defects[0].evidence
        assert any("static" in e for e in evidence)
        assert any("llm" in e for e in evidence)

    def test_highest_risk_property(self):
        fv1 = FeatureVector(defect_class="DUPLICATE_PAYMENT", static_hit=True,
                            static_max_confidence=0.9)
        fv2 = FeatureVector(defect_class="AMOUNT_CURRENCY", llm_hit=True,
                            llm_max_confidence=0.5)
        result = score_sample("s-1", [fv1, fv2])
        assert result.highest_risk is not None
        assert result.highest_risk.defect_class == "DUPLICATE_PAYMENT"


class TestThresholdConfig:
    def test_default_threshold_for_known_class(self):
        # Should return a float in [0, 1]
        tau = threshold_for("DUPLICATE_PAYMENT")
        assert 0.0 <= tau <= 1.0

    def test_unknown_class_returns_default(self):
        tau = threshold_for("NONEXISTENT_CLASS")
        assert tau == 0.45  # hardcoded fallback
