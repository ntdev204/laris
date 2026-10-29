"""`laris data check`: verify processed data and tooling before any training step."""

import argparse
import importlib.util
import json
from pathlib import Path
from typing import List

import pyarrow.parquet as pq

from laris.language.training.dataloader import TASK_DATASET_DIRS

SPLITS = ("train", "val", "test")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data/processed"), help="Processed data directory"
    )
    parser.add_argument(
        "--verify-sha256",
        action="store_true",
        help="Also re-hash every manifest file (slow on the full corpus)",
    )


def _manifest_problems(data_dir: Path, verify_sha256: bool) -> List[str]:
    manifest = data_dir / "task_splits_manifest.json"
    if not manifest.is_file():
        return [f"missing {manifest} (run `laris data partition`)"]
    from laris.corpus.splits.physical import _compute_file_sha256

    problems: List[str] = []
    entries = json.loads(manifest.read_text(encoding="utf-8")).get("partitioned_datasets", [])
    print(f"manifest: {len(entries)} datasets partitioned")
    for entry in entries:
        for split, name in entry["files"].items():
            path = Path(name)
            if not path.is_file():
                problems.append(f"{entry['dataset_id']}/{split}: missing {path}")
            elif path.stat().st_size != entry["bytes"][split]:
                problems.append(f"{entry['dataset_id']}/{split}: size differs from manifest")
            elif verify_sha256 and _compute_file_sha256(path) != entry["sha256"][split]:
                problems.append(f"{entry['dataset_id']}/{split}: sha256 differs from manifest")
    return problems


def _task_problems(data_dir: Path) -> List[str]:
    problems: List[str] = []
    for task, subdirs in TASK_DATASET_DIRS.items():
        for split in SPLITS:
            found = {
                sub: sorted((data_dir / sub).glob(f"{split}*.parquet"))
                for sub in subdirs
                if (data_dir / sub).is_dir()
            }
            rows = {
                sub: sum(pq.ParquetFile(p).metadata.num_rows for p in paths)
                for sub, paths in found.items()
                if paths
            }
            summary = ", ".join(f"{sub}={n}" for sub, n in rows.items()) or "none"
            print(f"{task:<10} {split:<5} {summary}")
            if not rows:
                problems.append(f"task '{task}' has no {split} data")
    return problems


def run(args: argparse.Namespace) -> int:
    problems = _manifest_problems(args.data_dir, args.verify_sha256)
    problems += _task_problems(args.data_dir)
    if importlib.util.find_spec("sentencepiece") is None:
        problems.append("sentencepiece is not installed (pip install -e '.[training]')")
    if problems:
        print("\n[NOT READY]")
        for problem in problems:
            print(f" - {problem}")
        return 1
    print("\n[READY] processed data and tooling are in place; no training was run.")
    return 0
