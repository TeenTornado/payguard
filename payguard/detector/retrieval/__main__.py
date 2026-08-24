"""`make kb-index` — (re)build the grounding index reproducibly from RULE facts + TRAIN examples."""
from __future__ import annotations

from payguard.detector.retrieval.retriever import build_index


def main() -> None:
    summary = build_index()
    print(f"KB index built: {summary['n_chunks']} chunks  tiers={summary['tiers']}")
    print(f"  train sample_ids indexed: {len(summary['sample_ids'])}")
    print("  index → dataset/kb_index/ (chroma + chunks.jsonl); commit for reproducibility")


if __name__ == "__main__":
    main()
