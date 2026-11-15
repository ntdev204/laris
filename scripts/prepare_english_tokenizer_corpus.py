#!/usr/bin/env python3
"""Prepare the English tokenizer fit corpus from TRAIN splits only (T177).

Writes one normalised passage per line up to a word budget per source
(configs/data/english_partition.yaml, block ``tokenizer_fit``) and a report with per-source word
counts and SHA-256 of every input shard. It never reads validation or test files and never fits a
tokenizer: the fit is an owner run.
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pyarrow.parquet as pq

MAX_LINE_BYTES = 4000  # below the SentencePiece max_sentence_length of 4096 bytes
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.research.corpus.splits.partitioners.english import load_partition_config  # noqa: E402
from laris.shared.language.tokenization.trainer import normalize_scientific_text  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def split_utf8(line: str, limit: int) -> List[str]:
    """Splits a line at whitespace into pieces of at most ``limit`` UTF-8 bytes.

    SentencePiece silently skips sentences longer than ``max_sentence_length`` bytes (4096 by
    default), and formula-heavy or non-ASCII text exceeds that with 4,000 characters; splitting
    keeps those documents in the fit.
    """
    if len(line.encode("utf-8")) <= limit:
        return [line]
    pieces: List[str] = []
    current: List[str] = []
    size = 0
    for word in line.split(" "):
        width = len(word.encode("utf-8")) + 1
        if current and size + width > limit:
            pieces.append(" ".join(current))
            current, size = [], 0
        current.append(word)
        size += width
    if current:
        pieces.append(" ".join(current))
    return pieces


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--processed", type=Path, default=REPO_ROOT / "data/processed")
    parser.add_argument(
        "--scale", type=float, default=1.0, help="multiply every word budget (trials)"
    )
    args = parser.parse_args(argv)
    block = load_partition_config()["tokenizer_fit"]
    manifest = json.loads(
        (args.processed / "task_splits_manifest.json").read_text(encoding="utf-8")
    )
    by_dir = {
        Path(r["files"]["train"]).parent.name: r
        for r in manifest["partitioned_datasets"]
        if "train" in r["files"]
    }
    out_path, report_path = REPO_ROOT / block["output"], REPO_ROOT / block["report"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(block["seed"])
    report: Dict[str, Any] = {"seed": block["seed"], "split": "train", "sources": {}}
    with open(out_path, "w", encoding="utf-8") as out:
        for name, budget in block["words"].items():
            entry = by_dir[name]
            path = REPO_ROOT / entry["files"]["train"]
            if "val" in path.name or "test" in path.name:
                raise ValueError(f"evaluation shard refused: {path}")
            digest = sha256(path)
            if digest != entry["sha256"]["train"]:
                raise ValueError(f"{path} changed since partitioning")
            pf = pq.ParquetFile(path)
            groups = list(range(pf.num_row_groups))
            rng.shuffle(groups)
            words = lines = 0
            limit = int(budget * args.scale)
            for group in groups:
                for text in pf.read_row_group(group, columns=["text"]).column("text").to_pylist():
                    line = " ".join(normalize_scientific_text(text or "").split())
                    for piece in split_utf8(line, MAX_LINE_BYTES) if line else []:
                        out.write(piece + "\n")
                        words += len(piece.split())
                        lines += 1
                    if words >= limit:
                        break
                if words >= limit:
                    break
            report["sources"][name] = {"words": words, "lines": lines, "shard_sha256": digest}
            print(f"{name}: {words:,} words, {lines:,} lines", flush=True)
    report["corpus_sha256"] = sha256(out_path)
    report["total_words"] = sum(s["words"] for s in report["sources"].values())
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"corpus {out_path} ({out_path.stat().st_size / 1e9:.2f} GB), "
        f"{report['total_words']:,} words"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
