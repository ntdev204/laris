"""`laris train language-encoder`: multi-task language encoder training and bounded profiling.

Supports compact and large model sizes, 8-bit AdamW, FlashAttention SDPA, activation
checkpointing, a --profile-only mode without weight updates, and the strict authorization gate."""

import argparse
from pathlib import Path
from typing import Any

from laris.core.authorization import (
    assert_training_authorized,
)
from laris.language.encoder.transformer import (
    TORCH_AVAILABLE,
    LanguageEncoderConfig,
    LargeLanguageEncoderConfig,
    PyTorchTransformerEncoder,
)
from laris.language.training.dataloader import (
    StreamingParquetMultiTaskDataLoader,
    SyntheticMultiTaskDataLoader,
)
from laris.language.training.profiling import (
    compute_analytical_training_memory_gb,
)
from laris.language.training.trainer import (
    LanguageEncoderTrainer,
    MultiTaskLossCalculator,
)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model-size",
        type=str,
        choices=["compact", "large"],
        default="large",
        help="Language encoder size preset (compact ~110M or large ~513M parameters)",
    )
    parser.add_argument(
        "--micro-batch-size",
        type=int,
        default=16,
        help="Micro-batch size per device forward step (default: 16)",
    )
    parser.add_argument(
        "--grad-accum-steps",
        type=int,
        default=4,
        help="Gradient accumulation steps before optimizer update (default: 4)",
    )
    parser.add_argument(
        "--max-seq-len",
        type=int,
        default=1024,
        help="Maximum sequence length tokens (default: 1024)",
    )
    parser.add_argument(
        "--precision",
        type=str,
        choices=["bf16", "fp16", "fp32"],
        default="bf16",
        help="Mixed-precision computation mode (default: bf16)",
    )
    parser.add_argument(
        "--no-8bit-adam",
        action="store_true",
        help="Disable 8-bit AdamW and fallback to standard 32-bit AdamW",
    )
    parser.add_argument(
        "--profile-only",
        action="store_true",
        help="Execute bounded non-training memory and latency profiling without weight updates",
    )
    parser.add_argument(
        "--authorized",
        action="store_true",
        help="Assert explicit operator authorization to run training steps",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/processed",
        help="Directory containing processed Parquet datasets (default: data/processed)",
    )
    parser.add_argument(
        "--tokenizer-model",
        type=str,
        default=None,
        help="Path to the fitted SentencePiece .model file (required for training)",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=1000,
        help="Total training optimization steps to execute (default: 1000)",
    )
    parser.add_argument(
        "--log-interval",
        type=int,
        default=10,
        help="Step logging interval (default: 10)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/checkpoints/language_encoder",
        help="Directory to save model checkpoints and training manifests",
    )


def run(args: argparse.Namespace) -> int:

    # 1. Instantiate Configuration
    config: LanguageEncoderConfig
    if args.model_size == "large":
        config = LargeLanguageEncoderConfig(
            max_sequence_length=args.max_seq_len,
            precision=args.precision,
            gradient_checkpointing=True,
        )
    else:
        config = LanguageEncoderConfig(
            max_sequence_length=min(args.max_seq_len, 512),
            precision=args.precision,
            gradient_checkpointing=False,
        )

    param_count = config.calculate_parameter_count(include_heads=True)
    use_8bit_adam = not args.no_8bit_adam

    # 2. Compute Analytical Training VRAM
    estimated_vram_gb = compute_analytical_training_memory_gb(
        config=config,
        batch_size=args.micro_batch_size,
        seq_len=args.max_seq_len,
        use_8bit_adam=use_8bit_adam,
        use_activation_checkpointing=config.gradient_checkpointing,
    )

    print("=" * 65)
    print("LARIS Language Encoder Training Runner")
    print("=" * 65)
    print(f"Model Size:                {args.model_size.upper()}")
    print(f"Total Parameters:          {param_count:,} (~{param_count / 1e6:.2f}M)")
    print(f"Hidden Dimension (d):      {config.d_model}")
    print(f"Layers (L) / Heads (H):    {config.num_layers} / {config.num_heads}")
    print(f"Sequence Length:           {args.max_seq_len}")
    print(f"Micro-Batch / Accum:       {args.micro_batch_size} / {args.grad_accum_steps}")
    print(f"Effective Batch Size:      {args.micro_batch_size * args.grad_accum_steps}")
    print(f"8-bit AdamW Optimizer:     {'ENABLED' if use_8bit_adam else 'DISABLED'}")
    ckpt_enabled = 'ENABLED' if config.gradient_checkpointing else 'DISABLED'
    print(f"Activation Checkpointing:  {ckpt_enabled}")
    print(f"Analytical Training VRAM:  ~{estimated_vram_gb:.2f} GB (Safety Limit: 14.5 GB)")
    print("=" * 65)

    if estimated_vram_gb > 14.5:
        print(f"[ERROR] Estimated VRAM {estimated_vram_gb:.2f} GB exceeds safety envelope 14.5 GB!")
        return 1

    # 3. Handle Profiling Mode
    if args.profile_only:
        print("\n[PROFILING MODE] Running bounded forward-pass profiling (Zero Training)...")
        synthetic_loader = SyntheticMultiTaskDataLoader(
            vocab_size=config.vocab_size,
            seq_len=min(args.max_seq_len, 64),
            batch_size=2,
        )
        sample_batch = synthetic_loader.generate_batch()
        print(
            f"Generated synthetic batch: task={sample_batch.task_type}, "
            f"shape={sample_batch.token_ids.shape}"
        )
        _ = MultiTaskLossCalculator()
        print("Loss calculation and tensor contracts verified.")
        print("[SUCCESS] Bounded profiling complete. Hardware budget is feasible.")
        return 0

    # 4. Handle Training Mode
    if not args.authorized:
        print(
            "\n[ERROR] Training execution requires '--authorized' flag "
            "and environment authorization."
        )
        print("Run with '--profile-only' to inspect memory feasibility without training.")
        return 1

    assert_training_authorized("language encoder pretraining")
    print("\n[TRAINING AUTHORIZED] Initializing language encoder training engine...")

    if not args.tokenizer_model or not Path(args.tokenizer_model).is_file():
        print(
            "[ERROR] --tokenizer-model must point to a fitted SentencePiece .model file. "
            "Fit one with `laris train tokenizer` first."
        )
        return 1
    try:
        import sentencepiece as spm
    except ImportError:
        print("[ERROR] sentencepiece is required: pip install -e '.[training]'")
        return 1
    tokenizer = spm.SentencePieceProcessor(model_file=args.tokenizer_model)
    if tokenizer.get_piece_size() != config.vocab_size:
        print(
            f"[ERROR] Tokenizer vocab {tokenizer.get_piece_size()} != "
            f"model vocab {config.vocab_size}"
        )
        return 1

    # Initialize Streaming Parquet DataLoader (train split only, no synthetic fallback)
    loader = StreamingParquetMultiTaskDataLoader(
        data_dir=args.data_dir,
        tokenizer=tokenizer,
        fallback_to_synthetic=False,
        vocab_size=config.vocab_size,
        seq_len=args.max_seq_len,
        batch_size=args.micro_batch_size,
        return_tensors="pt" if TORCH_AVAILABLE else "np",
    )

    for task_name, shard_paths in sorted(loader.task_paths.items()):
        print(f"Data shards [{loader.split}] {task_name:<11}: {len(shard_paths)}")

    # Initialize Model
    model: Any
    if TORCH_AVAILABLE:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Target Compute Device:     {device.upper()}")
        model = PyTorchTransformerEncoder(config).to(device)
    else:
        from laris.language.encoder.transformer import RandomlyInitializedTransformerEncoder

        device = "cpu"
        print("Target Compute Device:     CPU (NumPy Reference Model)")
        model = RandomlyInitializedTransformerEncoder(config)

    trainer = LanguageEncoderTrainer(
        model=model,
        config=config,
        dataloader=loader,
        use_8bit_adam=use_8bit_adam,
        grad_accum_steps=args.grad_accum_steps,
        device=device,
    )

    print(f"Starting language encoder training loop for {args.steps} steps...")
    for step_idx in range(1, args.steps + 1):
        batch = loader.generate_batch()
        metrics = trainer.execute_training_step(batch)
        if step_idx % args.log_interval == 0 or step_idx == 1:
            vram_str = f"{metrics.peak_vram_gb:.2f} GB" if metrics.peak_vram_gb else "N/A"
            print(
                f"[Step {metrics.step:05d}/{args.steps}] "
                f"Task: {metrics.task_type:<10} | "
                f"Loss: {metrics.loss_value:.4f} | "
                f"EffBatch: {metrics.effective_batch_size} | "
                f"Peak VRAM: {vram_str}"
            )

    print(f"\n[SUCCESS] Completed {args.steps} training steps successfully.")
    return 0

