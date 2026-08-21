"""
Pydantic schemas for LLM-structured output.

The LLM is prompted to return JSON only — no tools, no function calls.
Schema validation happens here; malformed output triggers the failure ladder.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class LLMFinding(BaseModel):
    defect_class: str = Field(
        description="One of: DUPLICATE_PAYMENT, WEBHOOK_INTEGRITY, AMOUNT_CURRENCY"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    evidence_lines: list[int] = Field(default_factory=list)
    scenario_ids: list[str] = Field(default_factory=list)

    @field_validator("defect_class")
    @classmethod
    def validate_defect_class(cls, v: str) -> str:
        allowed = {"DUPLICATE_PAYMENT", "WEBHOOK_INTEGRITY", "AMOUNT_CURRENCY"}
        if v not in allowed:
            raise ValueError(f"defect_class must be one of {allowed}, got {v!r}")
        return v


class LLMAnalysis(BaseModel):
    findings: list[LLMFinding] = Field(default_factory=list)
    analysis_notes: str = ""
