#!/usr/bin/env python3
"""CLI utility for Wikipedia clean corpus extraction and SentencePiece 32k BPE tokenizer fitting.

Adheres to DOC-SPEC-MOD-001 (Boundary B), ADR-002, and Issue #232.
Enforces:
- Anti-leakage: extracts exclusively from verified physical TRAIN partitions.
- Governance authorization gate: requires --authorized or LARIS_TOKENIZER_TRAINING_AUTHORIZED=1.
"""

import argparse
import os
import sys
from pathlib import Path

from laris.core.authorization import (
    is_tokenizer_training_authorized,
)
from laris.language.schemas import DEFAULT_TARGET_VOCAB_SIZE
from laris.language.tokenization.trainer import (
    TokenizerTrainerConfig,
    TokenizerTrainingPipeline,
    extract_clean_wikipedia_corpus,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LARIS Bilingual SentencePiece Tokenizer Runner"
    )
    parser.add_argument(
        "--train-shards",
        nargs="+",
        type=Path,
        default=None,
        help="Path to physical TRAIN Parquet files",
    )
    parser.add_argument(
        "--corpus-text-out",
        type=Path,
        default=Path("data/cache/wikipedia_train_corpus.txt"),
        help="Destination plain text corpus file (default: data/cache/wikipedia_train_corpus.txt)",
    )
    parser.add_argument(
        "--vocab-size",
        type=int,
        default=DEFAULT_TARGET_VOCAB_SIZE,
        help=f"Target vocabulary size (default: {DEFAULT_TARGET_VOCAB_SIZE})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/tokenizer"),
        help="Directory to save tokenizer artifacts (default: artifacts/tokenizer)",
    )
    parser.add_argument(
        "--model-prefix",
        type=str,
        default="laris_spm_32k",
        help="Prefix for model files (default: laris_spm_32k)",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=None,
        help="Maximum articles to extract for tokenizer fitting",
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Explicitly assert repository owner authorization for tokenizer fitting",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Only extract clean corpus text, do not run SentencePiece fitting",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("=" * 60)
    print("LARIS BILINGUAL TOKENIZER EXTRACTION & FIT RUNNER")
    print(f"Target Vocabulary Size: {args.vocab_size}")
    print(f"Output Directory:       {args.output_dir}")
    print(f"Model Prefix:           {args.model_prefix}")
    print("=" * 60)

    # 1. Resolve physical train shards
    train_shards = args.train_shards
    if not train_shards:
        candidates = [
            Path("data/processed/wikipedia_vi/train.parquet"),
            Path("data/processed/wikipedia_en/train.parquet"),
        ]
        train_shards = [c for c in candidates if c.is_file()]

    if not train_shards:
        print(
            "[ERROR] No physical TRAIN Parquet shards found. "
            "Run scripts/partition_datasets.py first.",
            file=sys.stderr,
        )
        return 1

    print(f"\n[1/3] Extracting clean text from {len(train_shards)} TRAIN shards...")
    count = extract_clean_wikipedia_corpus(
        parquet_paths=train_shards,
        output_text_path=args.corpus_text_out,
        max_articles=args.max_articles,
    )
    print(f"[SUCCESS] Extracted {count} articles to {args.corpus_text_out}")

    if args.extract_only:
        print("[INFO] --extract-only flag specified. Skipping SentencePiece fitting.")
        return 0

    # 2. Check authorization
    if args.authorized:
        os.environ["LARIS_TOKENIZER_TRAINING_AUTHORIZED"] = "1"

    print("\n[2/3] Checking governance authorization gate...")
    if not is_tokenizer_training_authorized():
        print(
            "[STOPPED] Tokenizer fitting requires explicit authorization. "
            "Pass --authorized or set LARIS_TOKENIZER_TRAINING_AUTHORIZED=1.",
            file=sys.stderr,
        )
        return 2

    # 3. Execute SentencePiece Fitting
    print("\n[3/3] Executing SentencePiece BPE 32k training...")
    cfg = TokenizerTrainerConfig(
        vocab_size=args.vocab_size,
        model_type="bpe",
        character_coverage=0.9995,
        input_corpus_paths=[args.corpus_text_out],
        output_dir=args.output_dir,
    )
    pipeline = TokenizerTrainingPipeline(cfg)
    try:
        model_file = pipeline.execute_training(
            force_authorized=True,
            model_prefix=args.model_prefix,
        )
        print(f"\n[SUCCESS] Tokenizer trained successfully: {model_file}")
        return 0
    except Exception as exc:
        print(f"\n[ERROR] Tokenizer fitting failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
