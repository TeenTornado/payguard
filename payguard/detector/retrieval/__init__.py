"""Retrieval-augmented grounding for the LLM analyzer (payguard/detector/retrieval).

Built from scratch. Two-tier knowledge base (RULE facts + labeled TRAIN examples), a hybrid
retriever (dense chromadb + lexical BM25 fused by reciprocal-rank fusion), split-safe by
construction (indexes the TRAIN split only). See ADR-011/012/013 and docs/evaluation.md.
"""
from payguard.detector.retrieval.kb import (
    Chunk,
    build_all_chunks,
    example_chunks_from_train,
    parse_rule_chunks,
)
from payguard.detector.retrieval.retriever import (
    KB_DIR,
    Retriever,
    build_index,
    load_retriever,
)

__all__ = [
    "Chunk",
    "build_all_chunks",
    "example_chunks_from_train",
    "parse_rule_chunks",
    "Retriever",
    "build_index",
    "load_retriever",
    "KB_DIR",
]
