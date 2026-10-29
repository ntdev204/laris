"""`laris data partition`: physical, leakage-safe dataset partitioning (zero training)."""

import argparse
import sys
from pathlib import Path

from laris.corpus.splits import execute_physical_partitioning


def add_arguments(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument(
        "--include-unreviewed-licenses",
        action="store_true",
        help="Also partition datasets whose license is still NEEDS_LICENSE_REVIEW",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100000,
        help="Streaming PyArrow batch size (default: 100,000 optimized for 32GB RAM)",
    )
    parser.add_argument(
        "--num-workers",
        type=int,
        default=None,
        help="Number of parallel worker processes (default: CPU cores count, up to 14/20)",
    )


def run(args: argparse.Namespace) -> int:
    print("=" * 60)
    print("LARIS PHYSICAL DATASET PARTITIONING ENGINE (SERVER OPTIMIZED)")
    print(f"Raw Source Directory:       {args.raw_dir}")
    print(f"Processed Output Directory: {args.output_dir}")
    print(f"Selected Datasets:          {args.datasets or 'ALL'}")
    print(f"Streaming Batch Size:       {args.batch_size}")
    print(f"Parallel Worker Limit:      {args.num_workers or 'AUTO (ALL AVAILABLE CORES)'}")
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
            batch_size=args.batch_size,
            num_workers=args.num_workers,
            include_unreviewed_licenses=args.include_unreviewed_licenses,
        )
        print("\n[SUCCESS] Physical partitioning completed successfully.")
        print(f"Total Datasets Partitioned: {report['total_datasets_partitioned']}")
        for skipped in report["skipped_datasets"]:
            print(f" ! skipped {skipped['dataset_id']}: license {skipped['reason']}")
        for ds in report["partitioned_datasets"]:
            print(f" - {ds['dataset_id']}: counts={ds['counts']}")
        return 0
    except Exception as exc:
        print(f"\n[ERROR] Partitioning failed: {exc}", file=sys.stderr)
        return 1

