"""
CLI entry point for dataset management.

Usage:
    python -m payguard.dataset generate   # generate seeded samples
    python -m payguard.dataset split      # split and freeze test manifest
    python -m payguard.dataset stats      # print split statistics
"""
import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "generate":
        from payguard.dataset.generator import generate_samples
        count = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        samples = generate_samples(count_per_template=count)
        print(f"Generated {len(samples)} samples in dataset/raw/")

    elif cmd == "split":
        from payguard.dataset.catalog import load_all_samples
        from payguard.dataset.splitter import freeze_test_manifest, split_samples
        all_samples = load_all_samples()
        splits = split_samples(all_samples)
        freeze_test_manifest(splits.test)
        print(f"Split complete — train={len(splits.train)}, val={len(splits.val)}, test={len(splits.test)}")
        print(f"Test manifest frozen at dataset/splits/test.manifest.json")

    elif cmd == "stats":
        from payguard.dataset.catalog import load_all_samples
        from payguard.dataset.splitter import split_samples
        all_samples = load_all_samples()
        splits = split_samples(all_samples)
        print(f"Total samples: {len(all_samples)}")
        print(f"  train: {len(splits.train)}")
        print(f"  val:   {len(splits.val)}")
        print(f"  test:  {len(splits.test)}")
        safe = sum(1 for s in all_samples if s.is_safe)
        print(f"  safe:  {safe}, vuln: {len(all_samples) - safe}")

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
