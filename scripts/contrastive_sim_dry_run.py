"""Dry run of the contrastive similarity batches on the real relation pairs (T199).

Reads the T197 pair file and encodes text with the tokenizer; no model, no forward pass, no
training. Reports the row kinds drawn against their target shares and the batch geometry.

    python scripts/contrastive_sim_dry_run.py \\
        --tokenizer-model artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model \\
        --batches 200 --batch-size 64 --output reports/verification/T199-contrastive-dry-run.json
"""

import argparse
import json
from pathlib import Path

import sentencepiece as spm

from laris.shared.language.loading.dataloader import (
    CONTRASTIVE_SIM_DATASET_DIR,
    CONTRASTIVE_SIM_TASK,
    StreamingParquetMultiTaskDataLoader,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tokenizer-model", required=True)
    parser.add_argument("--data-dir", default="data/processed")
    parser.add_argument("--batches", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--seq-len", type=int, default=128)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    tokenizer = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
    shards = sorted((Path(args.data_dir) / CONTRASTIVE_SIM_DATASET_DIR).glob("train*.parquet"))
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=args.data_dir, tokenizer=tokenizer, vocab_size=tokenizer.get_piece_size(),
        seq_len=args.seq_len, batch_size=8, seed=args.seed, return_tensors="np",
        include_contrastive_sim_task=True, contrastive_sim_batch_size=args.batch_size,
        trim_padding=True, task_paths={CONTRASTIVE_SIM_TASK: shards},
    )  # fmt: skip
    hard, width, extra_known, weight = [], [], [], []
    for _ in range(args.batches):
        labels = loader.generate_batch(CONTRASTIVE_SIM_TASK).labels
        negatives = labels.get("contrastive_sim_negative_ids")
        hard.append(0 if negatives is None else len(negatives))
        width.append(labels["contrastive_sim_anchor_ids"].shape[1])
        known = labels["contrastive_sim_known_positives"]
        extra_known.append(int(known.sum()) - known.shape[0])
        weight.append(float(labels["contrastive_sim_weights"].mean()))
    n = len(hard)
    result = {
        "batches": n, "batch_size": args.batch_size, "seed": args.seed,
        "rows": loader.contrastive_sim_report()[CONTRASTIVE_SIM_TASK],
        "hard_negatives_per_batch_mean": sum(hard) / n,
        "anchor_width_mean": sum(width) / n,
        "known_positive_cells_beyond_targets_per_batch_mean": sum(extra_known) / n,
        "mean_row_weight": sum(weight) / n,
    }  # fmt: skip
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
