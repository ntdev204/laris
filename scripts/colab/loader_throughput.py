#!/usr/bin/env python3
"""Milliseconds per micro-batch of the training data path, with and without worker processes (T213).

Loader only: no model, no GPU, no backward step. It builds the training loader as the CLI does
from a training YAML, then times `--batches` micro-steps for the plain loader and for each
`--workers` value of `PrefetchingLoader`. Run it on the machine that trains (a Colab VM: 12 cores).

Usage (from the repository root):
    python3 scripts/colab/loader_throughput.py \
        --config configs/language_encoder/english_r1_stage1_rerun.yaml \
        --tokenizer artifacts/tokenizer/english-r1-56k-nd/laris_spm_en_56k_nd.model --workers 2 4 8
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any, List

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

import sentencepiece as spm  # noqa: E402

from laris.shared.config.schemas import TrainingConfig  # noqa: E402
from laris.shared.language.loading.dataloader import StreamingParquetMultiTaskDataLoader  # noqa: E402
from laris.shared.language.loading.prefetch import PrefetchingLoader  # noqa: E402
from laris.shared.language.tokenization.normalized import NormalizedSentencePiece  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--micro-batch-size", type=int, default=None)
    parser.add_argument("--max-seq-len", type=int, default=1024)
    parser.add_argument("--vocab-size", type=int, default=56000)
    parser.add_argument("--workers", type=int, nargs="*", default=[2, 4, 8])
    parser.add_argument("--batches", type=int, default=150)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    hyper = TrainingConfig(**yaml.safe_load(args.config.read_text())["training"])
    micro = args.micro_batch_size or hyper.micro_batch_size
    tokenizer: Any = NormalizedSentencePiece(
        spm.SentencePieceProcessor(model_file=str(args.tokenizer))
    )

    def build(seed: int) -> StreamingParquetMultiTaskDataLoader:
        return StreamingParquetMultiTaskDataLoader(
            split="train", data_dir="data/processed", tokenizer=tokenizer,
            fallback_to_synthetic=False,
            require_real_data=True, vocab_size=args.vocab_size, seq_len=args.max_seq_len,
            batch_size=micro, return_tensors="pt", seed=seed, trim_padding=True,
            length_pool_batches=8,
            dataset_sampling_exponents=hyper.dataset_sampling_exponents,
            dataset_sampling_weights=hyper.dataset_sampling_weights,
            alpha=hyper.task_sampling_alpha, task_sampling_floor=hyper.task_sampling_floor,
            include_retrieval_pairs=hyper.loss_lambda_retrieval > 0,
            include_retrieval_task=hyper.retrieval_task,
            retrieval_batch_size=hyper.retrieval_batch_size,
            retrieval_max_sequence_length=hyper.retrieval_max_sequence_length,
            mlm_pair_fraction=hyper.mlm_pair_fraction, order_task=hyper.order_task,
            order_class_shares=hyper.order_class_shares,
            label_balanced_tasks=hyper.label_balanced_tasks,
            include_contrastive_sim_task=hyper.contrastive_sim_task,
            contrastive_sim_batch_size=hyper.contrastive_sim_batch_size,
            contrastive_sim_max_sequence_length=hyper.contrastive_sim_max_sequence_length,
            contrastive_sim_row_shares=hyper.contrastive_sim_row_shares,
            contrastive_sim_row_weights=hyper.contrastive_sim_row_weights,
        )  # fmt: skip

    k = hyper.tasks_per_step

    def take(source: Any) -> List[Any]:
        return [source.generate_batch()] if k == 1 else source.generate_step_batches(k)

    def time_source(source: Any) -> float:
        for _ in range(args.warmup):
            take(source)
        start = time.perf_counter()
        for _ in range(args.batches):
            take(source)
        return float((time.perf_counter() - start) / args.batches * 1000.0)

    print(
        f"{args.config.name}: micro-batch {micro}, {k} task(s) per micro-step"
    )
    plain = build(args.seed)
    base = time_source(plain)
    print(f"  plain loader (1 process): {base:7.1f} ms per micro-step")
    for n in args.workers:
        prefetch = PrefetchingLoader(build, plain, n, k, 4, args.seed)
        try:
            ms = time_source(prefetch)
        finally:
            prefetch.close()
        print(f"  {n:>2} workers: {ms:7.1f} ms per micro-step ({base / ms:.1f}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
