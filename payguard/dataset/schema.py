"""Dataset sample schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SampleSource(str, Enum):
    MANUAL = "MANUAL"
    SEEDED_VARIANT = "SEEDED_VARIANT"
    LLM_GENERATED = "LLM_GENERATED"
    PUBLIC = "PUBLIC"


@dataclass
class DefectLabel:
    defect_class: str          # DefectClass enum value
    lines: list[tuple[int, int]]  # [(start, end), ...]
    scenario_ids: list[str]


@dataclass
class Sample:
    sample_id: str
    repo_id: str               # lineage key for repo-level splitting
    language: str              # python | javascript | typescript
    framework: str             # flask | fastapi | express | nextjs
    source: SampleSource
    labels: list[DefectLabel]  # empty => SAFE
    hard_negative: bool
    difficulty: int            # 1–5
    runnable: bool
    manifest_path: str | None
    notes: str
    license: str
    # True if at least one static rule can directly detect the defect.
    # False for "static-blind" positives (wrong-field dedup, cross-module amount
    # conversion, etc.) that require LLM to find — used to measure LLM-only recall.
    static_detectable: bool = True
    generator_model: str | None = None
    generation_prompt_id: str | None = None
    seed: str | None = None
    file_path: str | None = None  # path to the sample code file

    @property
    def is_safe(self) -> bool:
        return len(self.labels) == 0

    def defect_classes(self) -> set[str]:
        return {lbl.defect_class for lbl in self.labels}
