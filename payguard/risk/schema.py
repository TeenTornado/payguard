"""Risk scoring schema — MEASURED vs ESTIMATED exposure labels."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


class ExposureKind(str, Enum):
    # Exact financial exposure computable from ledger / known order amount
    MEASURED = "MEASURED"
    # Exposure estimated from heuristic weights; no ledger data available
    ESTIMATED = "ESTIMATED"


@dataclass
class DefectRisk:
    defect_class: str            # DUPLICATE_PAYMENT | WEBHOOK_INTEGRITY | AMOUNT_CURRENCY
    score: float                 # 0.0–1.0; higher = more likely real defect
    exposure_kind: ExposureKind  # always labelled — never unlabelled
    exposure_usd: float | None   # populated only for MEASURED; None for ESTIMATED
    confidence: float            # aggregate confidence driving the score
    calibrated: bool             # True when ML model calibrated; False = heuristic
    evidence: list[str]          # rule IDs, LLM finding hashes, verifier verdicts
    notes: str = ""              # human-readable explanation


@dataclass
class SampleRisk:
    sample_id: str
    defects: list[DefectRisk] = field(default_factory=list)
    scorer_version: str = "heuristic-v1"  # bumped when calibrated model ships

    @property
    def highest_risk(self) -> DefectRisk | None:
        return max(self.defects, key=lambda d: d.score, default=None)
