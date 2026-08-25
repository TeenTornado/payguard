"""Leakage guard (non-negotiable): the grounding KB indexes the TRAIN split ONLY.

Indexing any val or test sample would let the analyzer retrieve a near-copy of the very
snippet being judged during eval — contaminating the C-vs-C+RAG comparison. This test asserts
that NONE of the val/test sample_ids appear in the built index's chunk metadata. CI-enforced.

Skipped only if the KB deps aren't installed; the index itself is built on the fly from the
TRAIN split so the test needs no committed artifact.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("chromadb", reason="RAG deps not installed")
pytest.importorskip("rank_bm25", reason="RAG deps not installed")

from payguard.dataset.catalog import load_all_samples  # noqa: E402
from payguard.dataset.splitter import split_samples  # noqa: E402
from payguard.detector.retrieval.kb import build_all_chunks  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TEST_MANIFEST = ROOT / "dataset" / "splits" / "test.manifest.json"


def _held_out_ids() -> set[str]:
    sp = split_samples(load_all_samples())
    ids = {s.sample_id for s in sp.val} | {s.sample_id for s in sp.test}
    # Also union the frozen test manifest, in case it was curated independently of the splitter.
    if TEST_MANIFEST.exists():
        man = json.loads(TEST_MANIFEST.read_text(encoding="utf-8"))
        ids |= {s["sample_id"] for s in man.get("samples", [])}
    return ids


def test_kb_indexes_train_split_only():
    held_out = _held_out_ids()
    indexed = {c.sample_id for c in build_all_chunks() if c.sample_id}
    leaked = indexed & held_out
    assert not leaked, f"KB leaked {len(leaked)} val/test samples into the index: {sorted(leaked)[:10]}"


def test_kb_has_both_tiers():
    chunks = build_all_chunks()
    tiers = {c.tier for c in chunks}
    assert "RULE" in tiers and "EXAMPLE" in tiers
    # Hard negatives must be represented (they're the retrieval-worthy safe patterns).
    assert any(c.hard_negative for c in chunks), "no hard-negative examples indexed"
