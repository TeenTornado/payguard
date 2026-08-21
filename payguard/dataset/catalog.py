"""
Dataset catalog: maps sample_ids to Sample objects.
Samples are hand-crafted code files under dataset/raw/ and examples/.
The generator (generator.py) produces seeded variants programmatically.
"""
from __future__ import annotations

import json
from pathlib import Path

from payguard.dataset.schema import DefectLabel, Sample, SampleSource

DATASET_ROOT = Path(__file__).parent.parent.parent / "dataset"
EXAMPLES_ROOT = Path(__file__).parent.parent.parent / "examples"


def _label(defect_class: str, lines: list[tuple[int, int]] | None = None,
           scenario_ids: list[str] | None = None) -> DefectLabel:
    return DefectLabel(
        defect_class=defect_class,
        lines=lines or [(1, 999)],
        scenario_ids=scenario_ids or [],
    )


# Hand-crafted samples from examples/ directory.
# These always go into the TRAIN pool (never test).
EXAMPLES_CATALOG: list[Sample] = [
    Sample(
        sample_id="ex-vuln-dp-r1",
        repo_id="examples-vulnerable-dp",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[_label("DUPLICATE_PAYMENT", scenario_ids=["DP-1"])],
        hard_negative=False,
        difficulty=2,
        runnable=False,
        manifest_path=None,
        notes="DP-R1: order creation without dedup",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "vulnerable" / "dp_r1_no_dedup.py"),
    ),
    Sample(
        sample_id="ex-vuln-dp-r2",
        repo_id="examples-vulnerable-dp",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[_label("DUPLICATE_PAYMENT", scenario_ids=["DP-1", "DP-3"])],
        hard_negative=False,
        difficulty=2,
        runnable=False,
        manifest_path=None,
        notes="DP-R2: retry loop around order creation",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "vulnerable" / "dp_r2_retry_loop.py"),
    ),
    Sample(
        sample_id="ex-vuln-dp-r3",
        repo_id="examples-vulnerable-webhook",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[
            _label("DUPLICATE_PAYMENT", scenario_ids=["DP-2"]),
            _label("WEBHOOK_INTEGRITY", scenario_ids=["WI-1", "WI-3"]),
        ],
        hard_negative=False,
        difficulty=3,
        runnable=False,
        manifest_path=None,
        notes="DP-R3 + WI-R1: webhook with no dedup and no sig check",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "vulnerable" / "dp_r3_webhook_no_dedup.py"),
    ),
    Sample(
        sample_id="ex-vuln-wi-r1",
        repo_id="examples-vulnerable-webhook",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[
            _label("WEBHOOK_INTEGRITY", scenario_ids=["WI-1"]),
            _label("DUPLICATE_PAYMENT", scenario_ids=["DP-2"]),
        ],
        hard_negative=False,
        difficulty=2,
        runnable=False,
        manifest_path=None,
        notes="WI-R1: no signature verification",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "vulnerable" / "wi_r1_no_signature.py"),
    ),
    Sample(
        sample_id="ex-vuln-ac-r1",
        repo_id="examples-vulnerable-amount",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[_label("AMOUNT_CURRENCY", scenario_ids=["AC-1"])],
        hard_negative=False,
        difficulty=2,
        runnable=False,
        manifest_path=None,
        notes="AC-R1: rupees passed as paise",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "vulnerable" / "ac_r1_rupees_not_paise.py"),
    ),
    Sample(
        sample_id="ex-vuln-ac-r3",
        repo_id="examples-vulnerable-amount",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[_label("AMOUNT_CURRENCY", scenario_ids=["AC-3"])],
        hard_negative=False,
        difficulty=2,
        runnable=False,
        manifest_path=None,
        notes="AC-R3: client-supplied amount",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "vulnerable" / "ac_r3_client_amount.py"),
    ),
    # Safe examples
    Sample(
        sample_id="ex-safe-dp-dedup",
        repo_id="examples-safe-dp",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[],
        hard_negative=True,
        difficulty=3,
        runnable=False,
        manifest_path=None,
        notes="Hard negative: dedup via DB unique constraint (LLM may miss this)",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "safe" / "dp_safe_with_db_dedup.py"),
    ),
    Sample(
        sample_id="ex-safe-wi-sig",
        repo_id="examples-safe-webhook",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[],
        hard_negative=False,
        difficulty=2,
        runnable=False,
        manifest_path=None,
        notes="Safe: full signature + event-id dedup",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "safe" / "wi_safe_signature_check.py"),
    ),
    Sample(
        sample_id="ex-safe-ac-paise",
        repo_id="examples-safe-amount",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[],
        hard_negative=True,
        difficulty=3,
        runnable=False,
        manifest_path=None,
        notes="Hard negative: variable named amount_paise already in correct unit",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "safe" / "ac_safe_paise_amount.py"),
    ),
    Sample(
        sample_id="ex-safe-ac-server",
        repo_id="examples-safe-amount",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[],
        hard_negative=False,
        difficulty=2,
        runnable=False,
        manifest_path=None,
        notes="Safe: amount computed server-side",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "safe" / "ac_safe_server_amount.py"),
    ),
    Sample(
        sample_id="ex-safe-wi-middleware",
        repo_id="examples-safe-webhook",
        language="python",
        framework="flask",
        source=SampleSource.MANUAL,
        labels=[],
        hard_negative=True,
        difficulty=4,
        runnable=False,
        manifest_path=None,
        notes="Hard negative: sig + dedup in middleware (rule must look at callees)",
        license="MIT",
        file_path=str(EXAMPLES_ROOT / "safe" / "wi_safe_dedup_via_middleware.py"),
    ),
]


def load_all_samples() -> list[Sample]:
    """Load all samples: hand-crafted examples + generated raw samples."""
    samples = list(EXAMPLES_CATALOG)

    raw_dir = DATASET_ROOT / "raw"
    if raw_dir.exists():
        for manifest_file in sorted(raw_dir.glob("**/sample.json")):
            try:
                with open(manifest_file) as f:
                    data = json.load(f)
                labels = [
                    DefectLabel(
                        defect_class=lbl["defect_class"],
                        lines=[(l[0], l[1]) for l in lbl.get("lines", [[1, 999]])],
                        scenario_ids=lbl.get("scenario_ids", []),
                    )
                    for lbl in data.get("labels", [])
                ]
                sample = Sample(
                    sample_id=data["sample_id"],
                    repo_id=data["repo_id"],
                    language=data["language"],
                    framework=data["framework"],
                    source=SampleSource(data.get("source", "MANUAL")),
                    labels=labels,
                    hard_negative=data.get("hard_negative", False),
                    difficulty=data.get("difficulty", 2),
                    runnable=data.get("runnable", False),
                    manifest_path=data.get("manifest_path"),
                    notes=data.get("notes", ""),
                    license=data.get("license", "MIT"),
                    static_detectable=data.get("static_detectable", True),
                    generator_model=data.get("generator_model"),
                    generation_prompt_id=data.get("generation_prompt_id"),
                    seed=data.get("seed"),
                    file_path=str(manifest_file.parent / data.get("file", "app.py")),
                )
                samples.append(sample)
            except Exception:
                pass

    return samples
