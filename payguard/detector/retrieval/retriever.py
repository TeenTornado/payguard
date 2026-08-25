"""Hybrid retriever: dense (chromadb + ONNX all-MiniLM-L6-v2) + lexical (BM25), fused by
reciprocal-rank fusion, filtered by defect class, hard-negatives up-weighted.

Deterministic: the ONNX MiniLM embedder is fixed (no sampling), BM25 and RRF are pure
functions, k0 and the hard-negative bonus are constants. `build_index` persists the chroma
collection + a chunks manifest under dataset/kb_index/ so the index is committable and
reproducible via `make kb-index`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from payguard.detector.retrieval.kb import Chunk, build_all_chunks

_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = _ROOT / "dataset" / "kb_index"
CHROMA_DIR = KB_DIR / "chroma"
CHUNKS_MANIFEST = KB_DIR / "chunks.jsonl"

COLLECTION = "payguard_kb"
RRF_K0 = 60          # standard reciprocal-rank-fusion constant
HARD_NEG_BONUS = 0.5 / RRF_K0  # small fused-score boost so hard negatives surface
DEFAULT_TOP_K = 4
_CANDIDATES = 24     # per-ranker candidate pool before fusion

_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]


def _embedding_function():
    # ONNX all-MiniLM-L6-v2 — local, deterministic, no torch. This is chroma's default.
    from chromadb.utils import embedding_functions
    return embedding_functions.ONNXMiniLM_L6_V2()


def _client():
    import chromadb
    from chromadb.config import Settings
    return chromadb.PersistentClient(path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False))


def build_index(chunks: list[Chunk] | None = None) -> dict:
    """(Re)build the KB index from RULE facts + TRAIN examples. Returns a summary."""
    if chunks is None:
        chunks = build_all_chunks()

    KB_DIR.mkdir(parents=True, exist_ok=True)
    client = _client()
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = client.create_collection(COLLECTION, embedding_function=_embedding_function(),
                                   metadata={"hnsw:space": "cosine"})
    # Add in a fixed order for reproducibility.
    chunks = sorted(chunks, key=lambda c: c.id)
    col.add(ids=[c.id for c in chunks],
            documents=[c.text for c in chunks],
            metadatas=[c.metadata() for c in chunks])

    with CHUNKS_MANIFEST.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps({"id": c.id, "text": c.text, **c.metadata()}) + "\n")

    tiers: dict[str, int] = {}
    for c in chunks:
        tiers[c.tier] = tiers.get(c.tier, 0) + 1
    return {"n_chunks": len(chunks), "tiers": tiers,
            "sample_ids": sorted({c.sample_id for c in chunks if c.sample_id})}


@dataclass
class _Row:
    id: str
    text: str
    meta: dict


class Retriever:
    def __init__(self, rows: list[_Row], collection):
        self._rows = rows
        self._by_id = {r.id: r for r in rows}
        self._collection = collection
        from rank_bm25 import BM25Okapi
        self._bm25 = BM25Okapi([_tokenize(r.text) for r in rows])

    # ── ranking ──────────────────────────────────────────────────────────────
    def _dense_ranked(self, query: str, defect_class: str) -> list[str]:
        res = self._collection.query(query_texts=[query], n_results=_CANDIDATES,
                                     where={"defect_class": defect_class})
        return list((res.get("ids") or [[]])[0])

    def _lexical_ranked(self, query: str, defect_class: str) -> list[str]:
        scores = self._bm25.get_scores(_tokenize(query))
        scored = [(self._rows[i].id, scores[i]) for i in range(len(self._rows))
                  if self._rows[i].meta.get("defect_class") == defect_class]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return [cid for cid, _ in scored[:_CANDIDATES]]

    def query(self, unit_text: str, defect_class: str, k: int = DEFAULT_TOP_K) -> list[dict]:
        """Retrieve top-k grounding chunks for a code unit + defect class (RRF of dense+lexical)."""
        dense = self._dense_ranked(unit_text, defect_class)
        lexical = self._lexical_ranked(unit_text, defect_class)

        fused: dict[str, float] = {}
        for ranking in (dense, lexical):
            for rank, cid in enumerate(ranking):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K0 + rank)
        for cid in list(fused):
            if self._by_id[cid].meta.get("hard_negative"):
                fused[cid] += HARD_NEG_BONUS

        ranked = sorted(fused.items(), key=lambda x: (-x[1], x[0]))
        top = ranked[:k]
        # Guarantee a citable RULE: if none of the top-k is RULE tier, promote the best-scoring
        # RULE candidate into the last slot (the model must cite the rule it violates).
        if not any(self._by_id[cid].meta.get("tier") == "RULE" for cid, _ in top):
            best_rule = next(((cid, s) for cid, s in ranked
                              if self._by_id[cid].meta.get("tier") == "RULE"), None)
            if best_rule and k > 0:
                top = top[: k - 1] + [best_rule]

        out = []
        for cid, score in top:
            r = self._by_id[cid]
            out.append({"id": cid, "score": round(score, 6), "text": r.text, **r.meta})
        return out


def _rows_from_manifest() -> list[_Row]:
    rows: list[_Row] = []
    for line in CHUNKS_MANIFEST.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        text = d.pop("text")
        cid = d.pop("id")
        rows.append(_Row(id=cid, text=text, meta=d))
    return rows


def load_retriever() -> Retriever:
    """Load the retriever. chunks.jsonl is the committed source of truth; the chroma vector
    cache is rebuilt from it deterministically if missing (so only the small manifest is
    committed, not the churning binary index)."""
    if not CHUNKS_MANIFEST.exists():
        raise FileNotFoundError(f"KB index not built — run `make kb-index` (missing {CHUNKS_MANIFEST})")
    rows = _rows_from_manifest()
    client = _client()
    ef = _embedding_function()
    try:
        col = client.get_collection(COLLECTION, embedding_function=ef)
        if col.count() != len(rows):
            raise ValueError("stale chroma cache")
    except Exception:
        try:
            client.delete_collection(COLLECTION)
        except Exception:
            pass
        col = client.create_collection(COLLECTION, embedding_function=ef,
                                       metadata={"hnsw:space": "cosine"})
        col.add(ids=[r.id for r in rows],
                documents=[r.text for r in rows],
                metadatas=[r.meta for r in rows])
    return Retriever(rows, col)
