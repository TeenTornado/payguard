"""
Repo-level train/val/test split.

Split is by repo_id (not by sample) with a fixed seed to prevent label leakage.
The test manifest is frozen on creation and validated before any eval run.

ADR-004: repo-level splits prevent leakage.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import NamedTuple

from payguard.dataset.schema import Sample

SPLITS_DIR = Path(__file__).parent.parent.parent / "dataset" / "splits"
TEST_MANIFEST_PATH = SPLITS_DIR / "test.manifest.json"

TRAIN_FRAC = 0.60
VAL_FRAC = 0.20
TEST_FRAC = 0.20
SPLIT_SEED = 42


class SplitResult(NamedTuple):
    train: list[Sample]
    val: list[Sample]
    test: list[Sample]


def _content_hash(sample: Sample) -> str:
    if sample.file_path and Path(sample.file_path).exists():
        content = Path(sample.file_path).read_bytes()
    else:
        content = sample.sample_id.encode()
    return hashlib.sha256(content).hexdigest()[:16]


def split_samples(samples: list[Sample], force_examples_to_train: bool = True) -> SplitResult:
    """
    Split samples by repo_id into train/val/test (60/20/20).
    Examples (examples/ directory) always go to train.
    Fixed seed guarantees deterministic splits.
    """
    # Separate examples (always train)
    if force_examples_to_train:
        train_examples = [s for s in samples if s.sample_id.startswith("ex-")]
        other = [s for s in samples if not s.sample_id.startswith("ex-")]
    else:
        train_examples = []
        other = samples

    # Group by repo_id
    repo_ids = sorted(set(s.repo_id for s in other))
    rng = random.Random(SPLIT_SEED)
    rng.shuffle(repo_ids)

    n = len(repo_ids)
    n_train = int(n * TRAIN_FRAC)
    n_val = int(n * VAL_FRAC)

    train_repos = set(repo_ids[:n_train])
    val_repos = set(repo_ids[n_train:n_train + n_val])
    test_repos = set(repo_ids[n_train + n_val:])

    train = train_examples + [s for s in other if s.repo_id in train_repos]
    val = [s for s in other if s.repo_id in val_repos]
    test = [s for s in other if s.repo_id in test_repos]

    return SplitResult(train=train, val=val, test=test)


def freeze_test_manifest(test_samples: list[Sample]) -> None:
    """Write (or overwrite) the frozen test manifest. Only done once at dataset creation."""
    SPLITS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "version": "1",
        "samples": [
            {
                "sample_id": s.sample_id,
                "repo_id": s.repo_id,
                "content_hash": _content_hash(s),
                "labels": [lbl.defect_class for lbl in s.labels],
            }
            for s in test_samples
        ],
    }
    TEST_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def validate_test_manifest(test_samples: list[Sample]) -> tuple[bool, str]:
    """
    Validate that test samples match the frozen manifest.
    Returns (ok, error_message). Called by make eval before running.
    """
    if not TEST_MANIFEST_PATH.exists():
        return False, "Test manifest not found. Run `make dataset` first."

    manifest = json.loads(TEST_MANIFEST_PATH.read_text())
    manifest_by_id = {e["sample_id"]: e for e in manifest["samples"]}

    current_ids = {s.sample_id for s in test_samples}
    manifest_ids = set(manifest_by_id.keys())

    if current_ids != manifest_ids:
        added = current_ids - manifest_ids
        removed = manifest_ids - current_ids
        return False, f"Test set changed! Added: {added}, Removed: {removed}"

    for s in test_samples:
        entry = manifest_by_id[s.sample_id]
        current_hash = _content_hash(s)
        if current_hash != entry["content_hash"]:
            return False, (
                f"Content of test sample {s.sample_id} changed "
                f"(stored hash={entry['content_hash'][:8]}, current={current_hash[:8]}). "
                "The test split is frozen — modify train/val samples instead."
            )

    return True, ""
