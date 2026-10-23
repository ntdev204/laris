#!/usr/bin/env python3
"""CLI utility for physical dataset partitioning into leakage-safe Parquet files.

Adheres to DOC-SPEC-MOD-001, ADR-001, ADR-003, and Issue #232.
Non-destructive: strictly preserves original raw files under data/raw/.
"""

import argparse
import sys
from pathlib import Path

from laris.corpus.task_splits import execute_physical_partitioning


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LARIS Physical Dataset Partitioning CLI (Zero Training)"
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("data/raw"),
        help="Path to raw dataset directory (default: data/raw)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Path to destination processed directory (default: data/processed)",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=None,
        help="Path to output task splits manifest JSON",
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=None,
        help="Specific datasets to partition (e.g., WIKIPEDIA-VI QUORA-DUPLICATES SQUAD)",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Optional ceiling on processed records per dataset (for smoke tests / debugging)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 60)
    print("LARIS PHYSICAL DATASET PARTITIONING ENGINE")
    print(f"Raw Source Directory:       {args.raw_dir}")
    print(f"Processed Output Directory: {args.output_dir}")
    print(f"Selected Datasets:          {args.datasets or 'ALL'}")
    if args.max_records:
        print(f"Record Bounded Limit:       {args.max_records}")
    print("=" * 60)

    try:
        report = execute_physical_partitioning(
            raw_root=args.raw_dir,
            processed_root=args.output_dir,
            manifest_output_path=args.manifest_path,
            datasets=args.datasets,
            max_records=args.max_records,
        )
        print("\n[SUCCESS] Physical partitioning completed successfully.")
        print(f"Total Datasets Partitioned: {report['total_datasets_partitioned']}")
        for ds in report["partitioned_datasets"]:
            print(f" - {ds['dataset_id']}: counts={ds['counts']}")
        return 0
    except Exception as exc:
        print(f"\n[ERROR] Partitioning failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
