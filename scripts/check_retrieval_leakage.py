#!/usr/bin/env python3
"""Leakage scan of the partitioned retrieval pairs (T178).

Re-reads every train/val/test file of the retrieval sources and counts rows that still contain
held-out text (SQuAD v1 validation/test questions and paragraphs, STS-B validation/test sentences,
SciFact claims, titles and abstracts), plus queries that sit in more than one split. Exits 1 unless
the held-out counts and the within-source split overlaps are zero. Reads files and writes one
report; nothing trains.

Usage:
    python scripts/check_retrieval_leakage.py \
        [--out reports/verification/T178-retrieval-leakage.json]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.research.corpus.splits.partitioners import english as E  # noqa: E402
from laris.research.corpus.splits.partitioners import retrieval as R  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=E.DEFAULT_CONFIG)
    parser.add_argument("--raw", type=Path, default=REPO_ROOT / "data/raw")
    parser.add_argument("--processed", type=Path, default=REPO_ROOT / "data/processed")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "reports/verification/T178-retrieval-leakage.json"
    )
    args = parser.parse_args(argv)
    config = E.load_partition_config(args.config)
    blocklist = R.build_blocklist(args.processed, args.raw, config)
    sources: Dict[str, Any] = {}
    files: Dict[str, List[Path]] = {}
    for spec in config["retrieval"]:
        directory = args.processed / spec["id"].lower().replace("-", "_")
        paths = [directory / f"{s}.parquet" for s in ("train", "val", "test")]
        paths = [p for p in paths if p.is_file()]
        if not paths:
            print(f"[ERROR] no partitioned files for {spec['id']} in {directory}")
            return 1
        files[spec["id"]] = paths
        hits: Dict[str, int] = {}
        rows = 0
        for path in paths:
            for batch in pq.ParquetFile(path).iter_batches(batch_size=20000):
                for query, positive in zip(
                    batch.column("query").to_pylist(), batch.column("positive").to_pylist()
                ):
                    rows += 1
                    nq, npos = R.normalise(query), R.normalise(positive)
                    reason = (
                        blocklist.exact_hit(nq)
                        or blocklist.exact_hit(npos)
                        or blocklist.overlap_hit(npos)
                        or (blocklist.overlap_hit(nq) if spec.get("symmetric") else None)
                    )
                    if reason:
                        hits[reason] = hits.get(reason, 0) + 1
        sources[spec["id"]] = {"rows": rows, "held_out_hits": hits}
        print(f"{spec['id']}: {rows:,} rows, held-out hits {hits or 0}", flush=True)
    isolation = R.scan_split_isolation(files)
    held_out_total = sum(sum(s["held_out_hits"].values()) for s in sources.values())
    clean = held_out_total == 0 and isolation["queries_in_two_splits_within_source"] == 0
    report = {
        "task": "T178",
        "blocked": {k: len(v) for k, v in blocklist.exact.items()},
        "sources": sources,
        "split_isolation": isolation,
        "held_out_hits_total": held_out_total,
        "clean": clean,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("split_isolation", "held_out_hits_total", "clean")}))
    return 0 if clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
