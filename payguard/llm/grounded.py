"""Grounding helper: retrieve KB references for a code unit, keyed by defect class.

The retriever is loaded once (its chroma cache is rebuilt from the committed chunks.jsonl if
absent). Retrieval is scoped ONLY to grounding the analyzer — it never touches detection,
verification, or scoring.
"""
from __future__ import annotations

import os
from functools import lru_cache

from payguard.shared.enums import DefectClass


def analyzer_mode() -> str:
    """'grounded' or 'baseline' (default). Set PAYGUARD_ANALYZER=grounded to enable RAG."""
    return os.environ.get("PAYGUARD_ANALYZER", "baseline").strip().lower()


def is_grounded() -> bool:
    return analyzer_mode() == "grounded"

GROUNDED_CLASSES = [
    DefectClass.DUPLICATE_PAYMENT.value,
    DefectClass.WEBHOOK_INTEGRITY.value,
    DefectClass.AMOUNT_CURRENCY.value,
]


@lru_cache(maxsize=1)
def _retriever():
    from payguard.detector.retrieval import load_retriever
    return load_retriever()


def retrieve_for_unit(unit_source: str, k: int = 2) -> dict[str, list[dict]]:
    """Top-k KB chunks per defect class for one code unit. k is small to keep the grounded
    prompt affordable for a local model (a rule + a labeled example per class)."""
    r = _retriever()
    return {dc: r.query(unit_source, dc, k) for dc in GROUNDED_CLASSES}
