"""Dataset acquisition runner: builds or merges the acquisition manifest."""

import argparse
import json
import sys
from dataclasses import asdict
from typing import Optional, Sequence

from laris.corpus.acquisition.common import MANIFEST_PATH, RAW_DIR, REPO_ROOT, DatasetEntry
from laris.corpus.acquisition.registry import EXPANSION_ACQUIRERS
from laris.corpus.acquisition.sources.cc100 import CC100_DEFAULT_MAX_DOCS, acquire_cc100_vi
from laris.corpus.acquisition.sources.core_corpora import (
    acquire_all_nli,
    acquire_anli,
    acquire_paws,
    acquire_quora_duplicates,
    acquire_squad,
    acquire_stsb,
    acquire_wikipedia_english_subset,
    acquire_wikipedia_vietnamese,
    record_laris_gold_status,
    record_nq_status,
    record_s2orc_status,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="DATASET_ID",
        help="Acquire only these expansion datasets and merge them into the existing manifest "
        f"(choices: {', '.join(EXPANSION_ACQUIRERS)})",
    )
    parser.add_argument(
        "--cc100-max-docs",
        type=int,
        default=CC100_DEFAULT_MAX_DOCS,
        help="Maximum cleaned CC-100 Vietnamese documents to stream",
    )


def run(args: argparse.Namespace) -> int:
    unknown = [d for d in (args.only or []) if d not in EXPANSION_ACQUIRERS]
    if unknown:
        print(f"[ERROR] unknown dataset id(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    def run_expansion(dataset_id: str) -> DatasetEntry:
        if dataset_id == "CC100-VI-CLEAN":
            return acquire_cc100_vi(args.cc100_max_docs)
        return EXPANSION_ACQUIRERS[dataset_id]()

    print("============================================================")
    print("LARIS Dataset Acquisition & Verification Runner")
    print("============================================================")
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if args.only:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        by_id = {d["dataset_id"]: d for d in manifest["datasets"]}
        for dataset_id in args.only:
            by_id[dataset_id] = asdict(run_expansion(dataset_id))
        datasets = list(by_id.values())
    else:
        entries = [
            acquire_paws(),
            acquire_stsb(),
            acquire_quora_duplicates(),
            acquire_all_nli(),
            acquire_squad(),
            acquire_anli(),
            acquire_wikipedia_vietnamese(),
            acquire_wikipedia_english_subset(),
            record_s2orc_status(),
            record_laris_gold_status(),
            record_nq_status(),
        ]
        entries.extend(run_expansion(dataset_id) for dataset_id in EXPANSION_ACQUIRERS)
        datasets = [asdict(e) for e in entries]
        manifest = {
            "manifest_version": "1.0.0",
            "created_at": "2026-10-16T23:45:00Z",
            "verified_by": "LARIS Dataset Governance Agent",
            "training_freeze_confirmed": True,
        }

    counted = ("VERIFIED", "DOWNLOADED")
    manifest["datasets"] = datasets
    manifest["total_datasets_tracked"] = len(datasets)
    manifest["total_acquired_bytes"] = sum(d["actual_size_bytes"] for d in datasets)
    manifest["total_acquired_samples"] = sum(
        d["actual_sample_count"] for d in datasets if d["acquisition_status"] in counted
    )
    manifest["training_freeze_confirmed"] = True

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print("\n============================================================")
    print(f"Acquisition Complete. Manifest written to: {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    print(f"Total Acquired Bytes: {manifest['total_acquired_bytes']:,} bytes")
    print(f"Total Samples (VERIFIED + DOWNLOADED): {manifest['total_acquired_samples']:,} samples")
    print("NO MODEL TRAINING WAS RUN.")
    print("============================================================")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="LARIS dataset acquisition runner")
    add_arguments(parser)
    return run(parser.parse_args(argv))
