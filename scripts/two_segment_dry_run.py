"""Loader dry run of the two-segment MLM rows (T194): no model, no training, no optimizer.

Builds the real streaming loader on the partitioned MLM shards with the two-segment options,
draws MLM batches only, and prints the share of two-segment rows and the order-class shares as
JSON. The tokenizer only encodes text (it is not fitted).

Usage (isolated HOME):
    HOME=$(mktemp -d) .venv/bin/python -I scripts/two_segment_dry_run.py \\
        --tokenizer-model artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model \\
        --mlm-pair-fraction 0.5 --order-task --batches 200 [--split train] [--out report.json]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from laris.shared.language.loading.dataloader import (  # noqa: E402
    TASK_DATASET_DIRS,
    StreamingParquetMultiTaskDataLoader,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default="data/processed")
    parser.add_argument("--tokenizer-model", required=True)
    parser.add_argument("--normalize-input", action="store_true")
    parser.add_argument("--split", default="train", choices=("train", "val"))
    parser.add_argument("--mlm-pair-fraction", type=float, required=True)
    parser.add_argument("--order-task", action="store_true")
    parser.add_argument("--order-class-shares", type=float, nargs=3, default=(1 / 3, 1 / 3, 1 / 3))
    parser.add_argument("--batches", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seq-len", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    import sentencepiece as spm

    tokenizer = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
    if args.normalize_input:
        from laris.shared.language.tokenization.normalized import NormalizedSentencePiece

        tokenizer = NormalizedSentencePiece(tokenizer)
    data = Path(args.data_dir)
    mlm_dirs = [d for d in TASK_DATASET_DIRS["mlm"] if (data / d).is_dir()]
    paths = [p for d in mlm_dirs for p in sorted((data / d).glob(f"{args.split}*.parquet"))]
    if not paths:
        print(f"[ERROR] No {args.split} MLM shards under {data}")
        return 1
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=data,
        task_paths={"mlm": paths},
        tokenizer=tokenizer,
        vocab_size=tokenizer.get_piece_size(),
        seq_len=args.seq_len,
        batch_size=args.batch_size,
        seed=args.seed,
        split=args.split,
        require_real_data=True,
        mlm_pair_fraction=args.mlm_pair_fraction,
        order_task=args.order_task,
        order_class_shares=tuple(args.order_class_shares),
    )
    for _ in range(args.batches):
        loader.generate_batch("mlm")
    report = {
        "split": args.split,
        "seq_len": args.seq_len,
        "batches": args.batches,
        "batch_size": args.batch_size,
        "seed": args.seed,
        "tokenizer_model": args.tokenizer_model,
        "mlm_shards": [str(p) for p in paths],
        **loader.two_segment_report(),
    }
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
