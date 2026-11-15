"""Loader dry run of source- and label-balanced NLI and paraphrase batches (T196).

No model, no training, no optimizer. Builds the real streaming loader on the partitioned train
shards with `label_balanced_tasks`, draws batches of the balanced tasks (formatted and tokenized
as in training), and prints as JSON the label share per source and per batch next to each
source's data prior. With `--plain` it also draws the same number of batches without balancing
and reports their per-batch label shares for comparison. The tokenizer only encodes text.

Usage (isolated HOME):
    HOME=$(mktemp -d) .venv/bin/python -I scripts/label_balance_dry_run.py \\
        --tokenizer-model artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model \\
        --batches 500 --plain [--out report.json]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from laris.shared.language.loading.dataloader import (  # noqa: E402
    TASK_DATASET_DIRS,
    StreamingParquetMultiTaskDataLoader,
)

LABEL_KEYS = {"nli": "nli_labels", "paraphrase": "para_labels"}


def _task_paths(data: Path, tasks: List[str]) -> Dict[str, List[Path]]:
    return {
        task: [
            p
            for d in TASK_DATASET_DIRS[task]
            if (data / d).is_dir()
            for p in sorted((data / d).glob("train*.parquet"))
        ]
        for task in tasks
    }


def _batch_shares(loader: StreamingParquetMultiTaskDataLoader, task: str, n: int) -> Dict[str, Any]:
    """Per-batch label share (mean, min, max) over `n` formatted batches."""
    shares: Dict[str, List[float]] = {}
    for _ in range(n):
        batch = loader.generate_batch(task)
        labels = [int(v) for v in batch.labels[LABEL_KEYS[task]].tolist()]
        counts = Counter(labels)
        for label in sorted(set(shares) | {str(k) for k in counts}):
            shares.setdefault(label, []).append(counts[int(label)] / len(labels))
    return {
        label: {"mean": sum(v) / n, "min": min(v + [0.0] * (n - len(v))), "max": max(v)}
        for label, v in sorted(shares.items())
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default="data/processed")
    parser.add_argument("--tokenizer-model", required=True)
    parser.add_argument("--normalize-input", action="store_true")
    parser.add_argument("--tasks", nargs="+", default=["nli", "paraphrase"])
    parser.add_argument("--batches", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seq-len", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--plain", action="store_true", help="also report unbalanced batches")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    import sentencepiece as spm

    tokenizer = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
    if args.normalize_input:
        from laris.shared.language.tokenization.normalized import NormalizedSentencePiece

        tokenizer = NormalizedSentencePiece(tokenizer)
    data = Path(args.data_dir)
    paths = _task_paths(data, args.tasks)
    empty = [task for task, found in paths.items() if not found]
    if empty:
        print(f"[ERROR] No train shards for {empty} under {data}")
        return 1
    common: Dict[str, Any] = dict(
        data_dir=data,
        task_paths=paths,
        tokenizer=tokenizer,
        vocab_size=tokenizer.get_piece_size(),
        seq_len=args.seq_len,
        batch_size=args.batch_size,
        seed=args.seed,
        split="train",
        require_real_data=True,
    )
    loader = StreamingParquetMultiTaskDataLoader(**common, label_balanced_tasks=args.tasks)
    formatted = {task: _batch_shares(loader, task, args.batches) for task in args.tasks}
    report: Dict[str, Any] = {
        "split": "train",
        "batches_per_task": args.batches,
        "batch_size": args.batch_size,
        "seed": args.seed,
        "tokenizer_model": args.tokenizer_model,
        "shards": {task: [str(p) for p in found] for task, found in paths.items()},
        "balanced": loader.label_balance_report(),
        "balanced_formatted_batch_label_share": formatted,
    }
    if args.plain:
        plain = StreamingParquetMultiTaskDataLoader(**common)
        report["plain_batch_label_share"] = {
            task: _batch_shares(plain, task, args.batches) for task in args.tasks
        }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
