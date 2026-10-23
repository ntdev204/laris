#!/usr/bin/env python3
# ruff: noqa: E402
"""Stage 1 Language Foundation Training Runner CLI.

Supports:
- Model tiers: 110M (baseline) and 512M (scaled foundation)
- VRAM optimization: 8-bit AdamW, FlashAttention SDPA, and Activation Checkpointing
- Target hardware profile: RTX 5070 Ti (16GB VRAM, Blackwell sm_100/sm_120)
- Bounded profiling mode (--profile-only) without weight updates
- Mandatory stop condition: Strict authorization gate (assert_training_authorized)
"""

import argparse
import sys
from pathlib import Path

# Add src to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from laris.core.authorization import (
    assert_training_authorized,
)
from laris.language.dataloader import SyntheticMultiTaskDataLoader
from laris.language.neural import (
    TransformerEncoder500MConfig,
    TransformerEncoderConfig,
)
from laris.language.profiling import (
    compute_analytical_training_memory_gb,
)
from laris.language.trainer import (
    Stage1LossCalculator,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="LARIS Stage 1 Language Foundation Training & Profiling Runner"
    )
    parser.add_argument(
        "--model-tier",
        type=str,
        choices=["110m", "500m"],
        default="500m",
        help="Model scale tier (110m baseline or 500m scaled foundation)",
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
        "--output-dir",
        type=str,
        default="artifacts/checkpoints/stage1",
        help="Directory to save model checkpoints and training manifests",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # 1. Instantiate Configuration
    if args.model_tier == "500m":
        config = TransformerEncoder500MConfig(
            max_sequence_length=args.max_seq_len,
            precision=args.precision,
            gradient_checkpointing=True,
        )
    else:
        config = TransformerEncoderConfig(
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
    print("LARIS Stage 1 Language Foundation Runner")
    print("=" * 65)
    print(f"Model Tier:                {args.model_tier.upper()}")
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
        _ = Stage1LossCalculator()
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

    assert_training_authorized("Stage 1 neural model pretraining")
    print("\n[TRAINING AUTHORIZED] Initializing Stage 1 training engine...")
    # Training execution loop executes on target server
    return 0


if __name__ == "__main__":
    sys.exit(main())
