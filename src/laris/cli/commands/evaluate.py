"""`laris evaluate language-encoder`: score a checkpoint on the held-out val/test split."""

import argparse
from pathlib import Path

from laris.language.evaluation.evaluator import EVAL_SPLITS
from laris.language.evaluation.runner import EXIT_USAGE, evaluate_checkpoint


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--checkpoint", required=True, help="Checkpoint dir (e.g. <run>/best)")
    parser.add_argument("--tokenizer-model", required=True, help="SentencePiece .model file")
    parser.add_argument("--split", choices=list(EVAL_SPLITS), default="test")
    parser.add_argument("--data-dir", default="data/processed")
    parser.add_argument("--config", default="configs/evaluation/language_encoder.yaml")
    parser.add_argument("--output", default=None, help="JSON report path")
    parser.add_argument("--max-samples", type=int, default=2000, help="Samples per dataset")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default=None, help="cuda or cpu (default: auto)")


def run(args: argparse.Namespace) -> int:
    checkpoint = Path(args.checkpoint)
    output = (
        Path(args.output)
        if args.output
        else Path("artifacts/evaluations/language_encoder")
        / f"{checkpoint.parent.name}-{checkpoint.name}-{args.split}.json"
    )
    try:
        code, _ = evaluate_checkpoint(
            checkpoint,
            Path(args.data_dir),
            args.split,
            Path(args.config),
            output=output,
            tokenizer_model=Path(args.tokenizer_model),
            max_samples=args.max_samples,
            batch_size=args.batch_size,
            seed=args.seed,
            device=args.device,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        return EXIT_USAGE
    return code
