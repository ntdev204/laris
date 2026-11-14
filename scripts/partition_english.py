#!/usr/bin/env python3
"""Partition the English stage-1 sources into data/processed and update the split manifest (T177).

Reads data/raw and data/processed (Wikipedia and SQuAD v1, for deduplication and leakage), writes
data/processed/<dir>/{train,val,test}.parquet and merges the entries into task_splits_manifest.json, dropping every
withdrawn Vietnamese entry. It reads and writes files only; nothing trains or fits.

Retrieval pairs (T178) are partitioned in one pass over all retrieval sources so that duplicates are dropped across
them; use --only with every retrieval id to repeat it.

Usage: python scripts/partition_english.py [--only ID ...] [--max-docs N]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.research.corpus.splits.partitioners import english as E  # noqa: E402
from laris.research.corpus.splits.partitioners import retrieval as R  # noqa: E402

WITHDRAWN = {"WIKIPEDIA-VI", "CC100-VI-CLEAN", "VINLI", "VISTS", "UIT-VIQUAD-V2"}


def dirname(dataset_id: str) -> str:
    return dataset_id.lower().replace("-", "_")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=E.DEFAULT_CONFIG)
    parser.add_argument("--raw", type=Path, default=REPO_ROOT / "data/raw")
    parser.add_argument("--processed", type=Path, default=REPO_ROOT / "data/processed")
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--max-docs", type=int, default=None, help="trial runs only")
    args = parser.parse_args(argv)
    config = E.load_partition_config(args.config)
    wanted = {i.upper() for i in args.only} if args.only else None
    manifest_path = args.processed / "task_splits_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {}

    def want(dataset_id: str) -> bool:
        return wanted is None or dataset_id in wanted

    seen: Set[int] = set()
    if any(want(s["id"]) for s in config["mlm"]):
        for name in config["dedupe_against"]:
            seen |= E.wikipedia_digest_set(args.processed, name)
        print(f"[dedupe] {len(seen):,} documents from {config['dedupe_against']}", flush=True)
    for spec in config["mlm"]:
        if want(spec["id"]):
            result, stats = E.partition_mlm_source(
                spec,
                args.raw / dirname(spec["id"]),
                args.processed / dirname(spec["id"]),
                config,
                seen,
                args.max_docs,
            )
            results.append(result.to_dict())
            report[spec["id"]] = {"counts": result.counts, **stats}
            print(f"[mlm] {spec['id']}: {result.counts} {stats}", flush=True)
    for kind in ("nli", "paraphrase"):
        for spec in config[kind]:
            if want(spec["id"]):
                result = E.partition_pairs(
                    spec,
                    kind,
                    args.raw / dirname(spec["id"]),
                    args.processed / dirname(spec["id"]),
                    config,
                )
                results.append(result.to_dict())
                report[spec["id"]] = {"counts": result.counts}
                print(f"[{kind}] {spec['id']}: {result.counts}", flush=True)
    if any(want(s["id"]) for s in config["qa"]):
        titles, contexts = E.squad_v1_heldout_keys(args.processed)
        for spec in config["qa"]:
            if want(spec["id"]):
                result, stats = E.partition_qa_source(
                    spec,
                    args.raw / dirname(spec["id"]),
                    args.processed / dirname(spec["id"]),
                    config,
                    titles,
                    contexts,
                )
                results.append(result.to_dict())
                report[spec["id"]] = {"counts": result.counts, **stats}
                print(f"[qa] {spec['id']}: {result.counts} {stats}", flush=True)

    if any(want(s["id"]) for s in config["retrieval"]):
        blocklist = R.build_blocklist(args.processed, args.raw, config)
        print(
            f"[retrieval] blocklist: {sum(len(v) for v in blocklist.exact.values()):,} texts, "
            f"{sum(len(v) for v in blocklist.shingles.values()):,} shingles",
            flush=True,
        )
        seen_pairs: Set[int] = set()
        for spec in config["retrieval"]:
            if want(spec["id"]):
                result, stats = R.partition_retrieval_source(
                    spec,
                    args.raw / dirname(spec["id"]),
                    args.processed / dirname(spec["id"]),
                    config,
                    blocklist,
                    seen_pairs,
                    args.max_docs,
                )
                results.append(result.to_dict())
                report[spec["id"]] = {"counts": result.counts, **stats}
                print(f"[retrieval] {spec['id']}: {result.counts} {stats}", flush=True)

    fresh = {r["dataset_id"] for r in results}
    kept = [
        r
        for r in manifest["partitioned_datasets"]
        if r["dataset_id"] not in fresh and r["dataset_id"] not in WITHDRAWN
    ]
    manifest["partitioned_datasets"] = kept + results
    manifest["skipped_datasets"] = [
        s for s in manifest.get("skipped_datasets", []) if s["dataset_id"] not in WITHDRAWN
    ]
    manifest["total_datasets_partitioned"] = len(manifest["partitioned_datasets"])
    manifest["english_partition"] = {
        "config": str(args.config.relative_to(REPO_ROOT))
        if args.config.is_relative_to(REPO_ROOT)
        else str(args.config),
        "seed": config["seed"],
        "sources": report,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"manifest updated: {len(manifest['partitioned_datasets'])} partitioned datasets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
