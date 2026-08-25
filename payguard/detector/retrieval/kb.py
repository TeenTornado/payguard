"""Knowledge-base chunks: the two tiers of grounding evidence.

- RULE tier: authoritative Razorpay facts parsed from docs/reference/razorpay-facts.md.
- EXAMPLE tier: labeled snippets from the dataset's TRAIN split ONLY (never val/test), each a
  SAFE_PATTERN or UNSAFE_PATTERN tagged with its defect class and sample_id.

Every chunk carries metadata {tier, defect_class, kind, source, sample_id?, hard_negative}.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from payguard.shared.enums import DefectClass

_ROOT = Path(__file__).resolve().parents[3]
RAZORPAY_FACTS = _ROOT / "docs" / "reference" / "razorpay-facts.md"

_ALL_CLASSES = [
    DefectClass.DUPLICATE_PAYMENT.value,
    DefectClass.WEBHOOK_INTEGRITY.value,
    DefectClass.AMOUNT_CURRENCY.value,
]

# id/name tokens → defect class, for attributing SAFE samples to the class they're safe *for*.
_CLASS_TOKENS = {
    "dp": DefectClass.DUPLICATE_PAYMENT.value,
    "dup": DefectClass.DUPLICATE_PAYMENT.value,
    "wi": DefectClass.WEBHOOK_INTEGRITY.value,
    "webhook": DefectClass.WEBHOOK_INTEGRITY.value,
    "ac": DefectClass.AMOUNT_CURRENCY.value,
    "amount": DefectClass.AMOUNT_CURRENCY.value,
    "paise": DefectClass.AMOUNT_CURRENCY.value,
}

_EXAMPLE_MAX_CHARS = 1600


@dataclass
class Chunk:
    id: str
    text: str
    defect_class: str
    kind: str  # RULE | SAFE_PATTERN | UNSAFE_PATTERN
    tier: str  # RULE | EXAMPLE
    source: str
    sample_id: str | None = None
    hard_negative: bool = False
    title: str = ""

    def metadata(self) -> dict:
        return {
            "tier": self.tier,
            "defect_class": self.defect_class,
            "kind": self.kind,
            "source": self.source,
            "sample_id": self.sample_id or "",
            "hard_negative": bool(self.hard_negative),
            "title": self.title,
        }


# ─── RULE tier ────────────────────────────────────────────────────────────────

_RULE_HEADER = re.compile(r"^###\s+RULE\s+([A-Z0-9-]+)\s+—\s+(.*)$")
_CLASS_LINE = re.compile(r"^class:\s*([A-Z_]+)\s*$")


def parse_rule_chunks(facts_path: Path | str = RAZORPAY_FACTS) -> list[Chunk]:
    """Parse `### RULE <ID> — <title>` blocks (each with a `class:` line) into chunks."""
    text = Path(facts_path).read_text(encoding="utf-8")
    chunks: list[Chunk] = []
    cur_id = cur_title = cur_class = None
    body: list[str] = []

    def flush() -> None:
        if cur_id and cur_class:
            chunks.append(Chunk(
                id=f"rule:{cur_id}",
                text=f"{cur_title}\n{' '.join(body).strip()}",
                defect_class=cur_class,
                kind="RULE",
                tier="RULE",
                source="razorpay-facts.md",
                title=cur_title or "",
            ))

    for line in text.splitlines():
        m = _RULE_HEADER.match(line)
        if m:
            flush()
            cur_id, cur_title = m.group(1), m.group(2).strip()
            cur_class, body = None, []
            continue
        if cur_id is not None:
            cm = _CLASS_LINE.match(line.strip())
            if cm:
                cur_class = cm.group(1)
            elif line.strip():
                body.append(line.strip())
    flush()
    return chunks


# ─── EXAMPLE tier (TRAIN split only) ──────────────────────────────────────────


def _infer_safe_classes(sample_id: str) -> list[str]:
    sid = sample_id.lower()
    hits = [cls for tok, cls in _CLASS_TOKENS.items() if re.search(rf"[-_]{tok}\d|[-_]{tok}[-_]|^{tok}[-_]", sid)]
    return sorted(set(hits)) or list(_ALL_CLASSES)


def _sample_code(sample) -> str:
    path = getattr(sample, "file_path", None)
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")[:_EXAMPLE_MAX_CHARS]
    except Exception:
        return ""


def example_chunks_from_train(train_samples=None) -> list[Chunk]:
    """Build EXAMPLE chunks from the TRAIN split only. Never indexes val/test."""
    if train_samples is None:
        from payguard.dataset.catalog import load_all_samples
        from payguard.dataset.splitter import split_samples
        train_samples = split_samples(load_all_samples()).train

    chunks: list[Chunk] = []
    for s in train_samples:
        code = _sample_code(s)
        if not code.strip():
            continue
        hard = bool(getattr(s, "hard_negative", False)) or s.sample_id.lower().startswith(("hn-", "sb-"))
        labels = list(getattr(s, "labels", []) or [])
        if labels:  # UNSAFE_PATTERN — one chunk per labeled class
            for lbl in labels:
                dc = lbl.defect_class
                chunks.append(Chunk(
                    id=f"ex:{s.sample_id}:{dc}",
                    text=f"UNSAFE {dc} example:\n{code}",
                    defect_class=dc, kind="UNSAFE_PATTERN", tier="EXAMPLE",
                    source="train-example", sample_id=s.sample_id, hard_negative=hard,
                ))
        else:  # SAFE_PATTERN — attribute to the class(es) it is safe for
            for dc in _infer_safe_classes(s.sample_id):
                chunks.append(Chunk(
                    id=f"ex:{s.sample_id}:{dc}:safe",
                    text=f"SAFE {dc} example (correct handling):\n{code}",
                    defect_class=dc, kind="SAFE_PATTERN", tier="EXAMPLE",
                    source="train-example", sample_id=s.sample_id, hard_negative=hard,
                ))
    return chunks


def build_all_chunks(train_samples=None) -> list[Chunk]:
    return parse_rule_chunks() + example_chunks_from_train(train_samples)
